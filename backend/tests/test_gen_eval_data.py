"""gen_eval_data.build_row 单测：注入假 retrieve/LLM，断言输出结构。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import gen_eval_data  # noqa: E402

build_row = gen_eval_data.build_row

FAKE_HITS = [
    {"content": "星辰X1 Pro 支持 100W 有线快充。", "doc_name": "手机数码.md"},
    {"content": "电池 5500mAh。", "doc_name": "手机数码.md"},
]


class _FakeRetrieve:
    """桩化检索：固定命中列表。"""

    async def __call__(self, question: str):
        assert question  # 透传问题
        return FAKE_HITS


class _FakeResp:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    """桩化 LLM：记录 messages，返回固定回答。"""

    def __init__(self):
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return _FakeResp(content="星辰X1 Pro 支持 100W 有线快充，电池 5500mAh。")


@pytest.mark.asyncio
async def test_build_row_structure_and_passthrough():
    llm = _FakeLLM()
    row = await build_row(
        "星辰X1 Pro 支持多少瓦快充？",
        "参考答案：支持 100W。",
        retrieve=_FakeRetrieve(),
        llm=llm,
    )

    assert row["question"] == "星辰X1 Pro 支持多少瓦快充？"
    assert row["ground_truth"] == "参考答案：支持 100W。"
    # contexts 取自命中的 content，context_docs 取自 doc_name
    assert row["contexts"] == ["星辰X1 Pro 支持 100W 有线快充。", "电池 5500mAh。"]
    assert row["context_docs"] == ["手机数码.md", "手机数码.md"]
    # answer 来自注入 LLM，且去掉了空白
    assert row["answer"] == "星辰X1 Pro 支持 100W 有线快充，电池 5500mAh。"
    assert "latency_s" not in row  # 延迟在 main() 里补，build_row 不加

    # LLM 拿到的是「系统提示(含检索上下文) + 当前问题」的消息序列
    assert len(llm.calls) == 1
    msgs = llm.calls[0]
    # 当前问题作为最后一条 human 消息
    assert any(
        getattr(m, "content", None) == "星辰X1 Pro 支持多少瓦快充？"
        for m in msgs
        if getattr(m, "type", "") == "human"
    )
    # 检索到的上下文拼进系统提示
    assert any(
        "星辰X1 Pro 支持 100W 有线快充。" in getattr(m, "content", "")
        for m in msgs
        if getattr(m, "type", "") == "system"
    )
