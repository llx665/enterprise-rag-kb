"""Self-RAG 测试：disabled / pass / revise / 非法 JSON / LLM 异常 五分支。"""
import pytest

from app.config import settings
from app.services import self_rag


class _Chunk:
    def __init__(self, content: str):
        self.content = content


class _Resp:
    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    """可编排的 LLM 桩：astream 依次返回草稿，ainvoke 依次返回 critic JSON。

    raise_drafts / raise_critics 分别指定第几次调用抛异常（独立计数）。
    """

    def __init__(
        self,
        drafts: list[str],
        critics: list[str] | None = None,
        raise_drafts: set[int] | None = None,
        raise_critics: set[int] | None = None,
    ):
        self.drafts = list(drafts)
        self.critics = list(critics or [])
        self.raise_drafts = set(raise_drafts or [])
        self.raise_critics = set(raise_critics or [])
        self.draft_i = 0
        self.critic_i = 0
        self.bound_with = None

    def bind(self, **kwargs):
        self.bound_with = kwargs
        return self

    async def astream(self, messages):
        idx = self.draft_i
        if idx in self.raise_drafts:
            raise RuntimeError("LLM 生成失败")
        self.draft_i += 1
        text = self.drafts[idx] if idx < len(self.drafts) else ""
        for i in range(0, len(text), 8):
            yield _Chunk(content=text[i : i + 8])

    async def ainvoke(self, messages):
        idx = self.critic_i
        if idx in self.raise_critics:
            raise RuntimeError("LLM 调用失败")
        self.critic_i += 1
        text = self.critics[idx] if idx < len(self.critics) else '{"verdict":"pass","issues":[]}'
        return _Resp(content=text)


@pytest.mark.asyncio
async def test_disabled_returns_draft_direct(monkeypatch):
    """SELF_RAG_ENABLED=False：直通草稿，不触发 critic。"""
    monkeypatch.setattr(settings, "SELF_RAG_ENABLED", False)
    fake = FakeLLM(drafts=["草稿答案"])
    monkeypatch.setattr(self_rag, "get_llm", lambda: fake)

    answer, ref = await self_rag.self_rag_answer("q", [], [{"content": "c"}])

    assert answer == "草稿答案"
    assert ref == {"enabled": False, "rounds": 0, "revised": False, "issues": []}
    assert fake.critic_i == 0  # 未调用 critic


@pytest.mark.asyncio
async def test_critic_pass_returns_draft(monkeypatch):
    """critic 判定 pass：原样返回草稿，rounds=1、未重写。"""
    monkeypatch.setattr(settings, "SELF_RAG_ENABLED", True)
    fake = FakeLLM(drafts=["草稿"], critics=['{"verdict":"pass","issues":[]}'])
    monkeypatch.setattr(self_rag, "get_llm", lambda: fake)

    answer, ref = await self_rag.self_rag_answer("q", [], [{"content": "c"}])

    assert answer == "草稿"
    assert ref["enabled"] is True
    assert ref["revised"] is False
    assert ref["rounds"] == 1
    assert fake.bound_with == {"response_format": {"type": "json_object"}}  # critic 走 JSON 模式


@pytest.mark.asyncio
async def test_critic_revise_then_pass(monkeypatch):
    """第一轮 revise、第二轮 pass：返回修正稿，记录问题清单。"""
    monkeypatch.setattr(settings, "SELF_RAG_ENABLED", True)
    fake = FakeLLM(
        drafts=["初稿", "修正稿"],
        critics=[
            '{"verdict":"revise","issues":["快充功率与资料不符"]}',
            '{"verdict":"pass","issues":[]}',
        ],
    )
    monkeypatch.setattr(self_rag, "get_llm", lambda: fake)

    answer, ref = await self_rag.self_rag_answer("q", [], [{"content": "c"}])

    assert answer == "修正稿"
    assert ref["revised"] is True
    assert ref["issues"] == ["快充功率与资料不符"]
    assert ref["rounds"] == 2


@pytest.mark.asyncio
async def test_critic_bad_json_degrades_to_pass(monkeypatch):
    """critic 返回非法 JSON：解析兜底失败降级为 pass，保留草稿不阻塞。"""
    monkeypatch.setattr(settings, "SELF_RAG_ENABLED", True)
    fake = FakeLLM(drafts=["草稿"], critics=["模型抽风了，输出一堆废话不是 JSON"])
    monkeypatch.setattr(self_rag, "get_llm", lambda: fake)

    answer, ref = await self_rag.self_rag_answer("q", [], [{"content": "c"}])

    assert answer == "草稿"
    assert ref["revised"] is False
    assert ref["rounds"] == 1


@pytest.mark.asyncio
async def test_critic_llm_error_keeps_draft(monkeypatch):
    """critic LLM 调用抛异常：保留草稿，不抛给上层。"""
    monkeypatch.setattr(settings, "SELF_RAG_ENABLED", True)
    fake = FakeLLM(drafts=["草稿"], raise_critics={0})  # 第一个 ainvoke（critic）抛异常
    monkeypatch.setattr(self_rag, "get_llm", lambda: fake)

    answer, ref = await self_rag.self_rag_answer("q", [], [{"content": "c"}])

    assert answer == "草稿"
    assert ref["revised"] is False
    assert ref["rounds"] == 1  # 已尝试一轮 critic


@pytest.mark.asyncio
async def test_revise_llm_error_keeps_old_draft(monkeypatch):
    """重写阶段 LLM 异常：保留旧草稿（带 revised 标记），不抛错。"""
    monkeypatch.setattr(settings, "SELF_RAG_ENABLED", True)
    fake = FakeLLM(
        drafts=["初稿", "修正稿"],
        critics=['{"verdict":"revise","issues":["补充售后条款"]}'],
        raise_drafts={1},  # 第二次 astream（重写）抛异常
    )
    monkeypatch.setattr(self_rag, "get_llm", lambda: fake)

    answer, ref = await self_rag.self_rag_answer("q", [], [{"content": "c"}])

    assert answer == "初稿"
    assert ref["revised"] is True


@pytest.mark.asyncio
async def test_first_generate_error_propagates(monkeypatch):
    """首次生成 LLM 异常：向上抛出（无草稿可降级，由调用方兜底）。"""
    monkeypatch.setattr(settings, "SELF_RAG_ENABLED", True)
    fake = FakeLLM(drafts=["草稿"], raise_drafts={0})  # 第一个 astream（首次生成）抛异常
    monkeypatch.setattr(self_rag, "get_llm", lambda: fake)

    with pytest.raises(RuntimeError, match="生成失败"):
        await self_rag.self_rag_answer("q", [], [{"content": "c"}])


@pytest.mark.asyncio
async def test_on_stage_callback_reports_stages(monkeypatch):
    """on_stage 回调按 生成->核对->重写 依次触发。"""
    monkeypatch.setattr(settings, "SELF_RAG_ENABLED", True)
    fake = FakeLLM(
        drafts=["初稿", "修正稿"],
        critics=['{"verdict":"revise","issues":["x"]}', '{"verdict":"pass","issues":[]}'],
    )
    monkeypatch.setattr(self_rag, "get_llm", lambda: fake)

    stages: list[str] = []

    async def on_stage(stage: str) -> None:
        stages.append(stage)

    await self_rag.self_rag_answer("q", [], [{"content": "c"}], on_stage=on_stage)

    assert stages == ["generating", "criticizing", "revising", "criticizing"]
