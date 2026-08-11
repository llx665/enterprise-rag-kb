"""LangChain Agent：在纯 RAG 基础上叠加工具调用能力（Agent + RAG 融合）。

能力：
- 数学计算、实时天气、日历农历等通用 AI 能力（对应 DeepSeek 的计算/天气/日历）
- 同时把「知识库混合检索」注册为工具之一，Agent 可先检索知识库再回答，
  实现「RAG 与工具融合」——既懂商品知识，又具备通用工具能力。

实现：
- LangGraph create_react_agent（ReAct 循环），模型为 DeepSeek（OpenAI 兼容，支持 function calling）
- 流式：astream(stream_mode="messages") 逐 token 产出最终回答，
  同时从 agent 节点的 tool_calls 解析出工具调用事件（供前端展示“正在查询天气…”状态）
- 工具调用前模型输出的过渡文字会丢弃，保证保存到数据库的是最终答案
"""
from datetime import datetime
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from .rag_chain import get_llm
from .tools import calculate, get_calendar, get_month_calendar, get_weather, retrieve_knowledge

AGENT_SYSTEM_PROMPT = """你是电商平台的智能客服助手。请根据用户问题选择合适的工具获取信息，再基于工具结果回答：
- 商品参数、价格、型号、功能介绍、售后、退换货、物流、会员、优惠等知识库内容 → 使用 retrieve_knowledge
- 数学计算 → 使用 calculate
- 天气查询 → 使用 get_weather
- 日期、星期、农历、月历 → 使用 get_calendar / get_month_calendar
可以组合使用多个工具（例如先检索价格再计算折扣）。回答使用中文，简洁准确。若工具结果不足，如实说明，不要编造。"""

_TOOLS = [retrieve_knowledge, calculate, get_weather, get_calendar, get_month_calendar]

# 工具名称 -> 中文标签（前端展示“正在做什么”）
TOOL_NAMES_ZH = {
    "retrieve_knowledge": "检索知识库",
    "calculate": "数学计算",
    "get_weather": "查询天气",
    "get_calendar": "查询日期/农历",
    "get_month_calendar": "查看月历",
}

_agent = None


def get_agent():
    """全局单例 Agent（创建一次，复用模型连接）。"""
    global _agent
    if _agent is None:
        _agent = create_react_agent(
            get_llm(),
            _TOOLS,
            prompt=SystemMessage(content=AGENT_SYSTEM_PROMPT),
        )
    return _agent


def format_tool_display(name: str, args: dict) -> str:
    """把工具调用格式化为前端可读的状态文案。"""
    label = TOOL_NAMES_ZH.get(name, name)
    detail = ""
    if name == "get_weather" and args.get("city"):
        detail = str(args["city"])
    elif name == "calculate" and args.get("expression"):
        detail = str(args["expression"])[:40]
    elif name == "get_calendar" and args.get("date"):
        detail = str(args["date"])
    elif name == "get_month_calendar":
        y, m = args.get("year"), args.get("month")
        if y and m:
            detail = f"{y}年{m}月"
    elif name == "retrieve_knowledge" and args.get("query"):
        detail = str(args["query"])[:40]
    return f"{label}：{detail}" if detail else label


async def stream_agent(question: str, history: list[dict]):
    """运行 Agent 并逐事件产出。

    Yields:
        {"type": "tool",  "name": str, "args": dict}  工具调用（完整参数，供前端展示状态）
        {"type": "token", "content": str}             最终回答增量

    流式策略：使用双 stream_mode。
    - "messages"：逐 token 收集模型输出
    - "updates"：每个 agent 步完成后拿到完整的 AIMessage（含工具调用完整参数）

    同一 agent 步内的内容先缓冲，只有在该步未调用工具时才放行（即最终回答），
    因此工具调用前的过渡文字不会串进最终答案，也不会出现空名/重复工具事件。
    """
    agent = get_agent()
    now = datetime.now()
    date_hint = SystemMessage(
        content=(
            f"今天是{now.year}年{now.month}月{now.day}日，"
            f"星期{'一二三四五六日'[now.weekday()]}，当前时间 {now:%H:%M}。"
            "查询日期/农历/时间相关问题时以此为基准。"
        )
    )
    messages: list = [date_hint]
    for msg in history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=question))

    pending_content: list[str] = []  # 当前 agent 步缓冲的内容 token
    async for mode, payload in agent.astream(
        {"messages": messages},
        stream_mode=["updates", "messages"],
        config={"recursion_limit": 25},
    ):
        if mode == "updates":
            if "agent" not in payload:
                continue  # 工具节点结果不需要透传
            agent_msgs = payload["agent"].get("messages", [])
            for m in agent_msgs:
                tool_calls = getattr(m, "tool_calls", None) or []
                if tool_calls:
                    # 本步模型选择调用工具：丢弃过渡文字，产出工具事件
                    pending_content.clear()
                    for tc in tool_calls:
                        name = tc.get("name", "")
                        if name:
                            yield {"type": "tool", "name": name, "args": tc.get("args", {})}
                else:
                    # 本步是最终回答：放行缓冲的 token
                    for p in pending_content:
                        yield {"type": "token", "content": p}
                    pending_content = []
        else:  # mode == "messages"
            chunk, metadata = payload
            if metadata.get("langgraph_node") != "agent":
                continue  # 工具节点的 ToolMessage 无需透传
            if getattr(chunk, "tool_calls", None):
                continue  # 工具调用参数分片，不按 token 透传
            content = getattr(chunk, "content", None)
            if content:
                pending_content.append(content)

    # 兜底：若流提前结束仍残留缓冲，一并放出
    for p in pending_content:
        yield {"type": "token", "content": p}
