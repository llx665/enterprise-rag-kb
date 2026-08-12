"""build_messages 摘要注入测试：有/无 summary 两态，SystemMessage 顺序正确。"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.services.rag_chain import build_messages


def test_build_messages_with_summary():
    """有摘要：主系统提示后紧跟「更早对话摘要」SystemMessage。"""
    messages = build_messages(
        "今天的问题",
        [{"role": "user", "content": "之前问过"}, {"role": "assistant", "content": "之前答过"}],
        "参考资料内容",
        summary="用户之前咨询了手机快充参数",
    )
    assert len(messages) == 5  # 主提示 + 摘要 + 历史2条 + 当前问题
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], SystemMessage)
    assert "更早对话摘要：用户之前咨询了手机快充参数" in messages[1].content
    # 历史消息类型正确
    assert isinstance(messages[2], HumanMessage)
    assert isinstance(messages[3], AIMessage)
    assert isinstance(messages[4], HumanMessage)
    assert messages[4].content == "今天的问题"


def test_build_messages_without_summary():
    """无摘要：不插入摘要 SystemMessage，结构与旧行为一致。"""
    messages = build_messages(
        "今天的问题",
        [{"role": "user", "content": "之前问过"}],
        "参考资料内容",
    )
    assert len(messages) == 3  # 主提示 + 历史1条 + 当前问题
    assert isinstance(messages[0], SystemMessage)
    assert not any("更早对话摘要" in m.content for m in messages if isinstance(m, SystemMessage))


def test_build_messages_empty_summary_skipped():
    """空字符串摘要视为无摘要（聊天链路传空时不影响）。"""
    messages = build_messages("q", [], "ctx", summary="")
    assert len(messages) == 2  # 主提示 + 当前问题
    assert not any(
        isinstance(m, SystemMessage) and "更早对话摘要" in m.content for m in messages
    )
