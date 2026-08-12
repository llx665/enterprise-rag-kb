"""会话记忆滚动摘要测试：超阈值压缩、幂等、LLM 异常降级、get_session_memory。"""
import pytest
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import ChatSession, Message, User
from app.services import memory


class _Resp:
    def __init__(self, content: str):
        self.content = content


class _FakeCompressLLM:
    """摘要 LLM 桩：返回固定摘要。"""

    async def ainvoke(self, messages):
        return _Resp(content="用户咨询星辰X1 Pro，确认支持100W快充，已下单。")


class _BoomCompressLLM:
    """摘要 LLM 桩：抛异常模拟摘要服务不可用。"""

    async def ainvoke(self, messages):
        raise RuntimeError("compress service down")


async def _admin_id() -> int:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        return admin.id


async def _make_session_with_messages(n: int) -> tuple[int, list[int]]:
    """创建会话并写入 n 条消息，返回 (session_id, 消息 id 列表按顺序)。"""
    async with SessionLocal() as db:
        session = ChatSession(user_id=await _admin_id(), title="长对话")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        msgs = [
            Message(
                session_id=session.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"消息{i}",
            )
            for i in range(n)
        ]
        db.add_all(msgs)
        await db.commit()
        ids = [m.id for m in msgs]
        return session.id, ids


@pytest.mark.asyncio
async def test_maybe_compress_updates_summary(client, monkeypatch):
    """超阈值时把窗口外消息折叠进摘要，summary_until_id 推进到折叠边界。"""
    monkeypatch.setattr(memory, "get_llm", lambda: _FakeCompressLLM())
    n = settings.MEMORY_SUMMARY_TRIGGER + 4  # 12 + 4 = 16
    session_id, ids = await _make_session_with_messages(n)

    async with SessionLocal() as db:
        s = await db.get(ChatSession, session_id)
        await memory.maybe_compress(db, s)

        assert s.summary == "用户咨询星辰X1 Pro，确认支持100W快充，已下单。"
        cutoff = n - settings.MEMORY_RECENT_LIMIT  # 6
        assert s.summary_until_id == ids[cutoff - 1]  # 折叠到前 6 条的最后一条


@pytest.mark.asyncio
async def test_maybe_compress_idempotent(client, monkeypatch):
    """summary_until_id 单调推进：第二次压缩不再重复折叠，摘要与边界不变。"""
    calls = {"n": 0}

    class _CountingLLM:
        async def ainvoke(self, messages):
            calls["n"] += 1
            return _Resp(content="摘要")

    monkeypatch.setattr(memory, "get_llm", lambda: _CountingLLM())
    session_id, _ = await _make_session_with_messages(settings.MEMORY_SUMMARY_TRIGGER + 4)

    async with SessionLocal() as db:
        s = await db.get(ChatSession, session_id)
        await memory.maybe_compress(db, s)
        first = (s.summary, s.summary_until_id)
        await memory.maybe_compress(db, s)
        second = (s.summary, s.summary_until_id)

    assert calls["n"] == 1  # 第二次未触发新压缩
    assert first == second


@pytest.mark.asyncio
async def test_maybe_compress_llm_error_keeps_old(client, monkeypatch):
    """摘要 LLM 异常：保留旧摘要、不抛错、until_id 不推进。"""
    monkeypatch.setattr(memory, "get_llm", lambda: _BoomCompressLLM())
    session_id, _ = await _make_session_with_messages(settings.MEMORY_SUMMARY_TRIGGER + 4)

    async with SessionLocal() as db:
        s = await db.get(ChatSession, session_id)
        await memory.maybe_compress(db, s)  # 不应抛异常
        assert s.summary is None
        assert s.summary_until_id is None


@pytest.mark.asyncio
async def test_maybe_compress_below_threshold_noop(client, monkeypatch):
    """消息数未超阈值：不调用 LLM、摘要保持为空。"""
    calls = {"n": 0}

    class _CountingLLM:
        async def ainvoke(self, messages):
            calls["n"] += 1
            return _Resp(content="不应触发")

    monkeypatch.setattr(memory, "get_llm", lambda: _CountingLLM())
    session_id, _ = await _make_session_with_messages(5)

    async with SessionLocal() as db:
        s = await db.get(ChatSession, session_id)
        await memory.maybe_compress(db, s)
        assert calls["n"] == 0
        assert s.summary is None


@pytest.mark.asyncio
async def test_get_session_memory_recent_order(client):
    """返回 (摘要, 最近 N 条按时间升序的原文)，且能排除指定消息。"""
    n = 15
    session_id, ids = await _make_session_with_messages(n)

    async with SessionLocal() as db:
        s = await db.get(ChatSession, session_id)
        s.summary = "历史摘要"
        s.summary_until_id = ids[4]
        await db.commit()

        summary, recent = await memory.get_session_memory(db, s)
        assert summary == "历史摘要"
        assert len(recent) == settings.MEMORY_RECENT_LIMIT
        # 最近 N 条 = 末尾 10 条，按 id 升序
        assert [m["content"] for m in recent] == [f"消息{i}" for i in range(n - 10, n)]

        # exclude_id 排除当前提问（最新一条）：窗口整体前移，仍取最近 N 条
        _, recent_no_newest = await memory.get_session_memory(db, s, exclude_id=ids[-1])
        assert len(recent_no_newest) == settings.MEMORY_RECENT_LIMIT
        contents = [m["content"] for m in recent_no_newest]
        assert "消息14" not in contents  # 被排除
        assert recent_no_newest[-1]["content"] == "消息13"  # 窗口前移到下一条
