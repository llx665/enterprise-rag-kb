"""Self-RAG 两轮自省：draft 生成 -> critic 事实校验 -> 必要时重写。

背景（超越简历项目的点）：
普通 RAG 只做「检索 -> 一次生成」，答案可能基于过时/矛盾/缺失的参考资料而出现
幻觉。Self-RAG 在生成后多一层 **critic** 校验：对照参考资料逐条核对草稿中的事实
性陈述（数字/型号/参数/价格/政策），发现「无依据 / 矛盾 / 臆测」就带着问题清单
重新生成，最多 SELF_RAG_MAX_ROUNDS 轮。全部降级安全：critic 解析失败、LLM 异常
一律保留当前草稿，不阻塞对话。

使用场景：仅 RAG 链路（知识库问答）；Agent 工具类问题不走此流程。
"""
import json
import re
from typing import Awaitable, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..config import settings
from .rag_chain import build_messages as rag_build_messages
from .rag_chain import format_context, get_llm

# critic：事实核对，要求只输出 JSON
CRITIC_PROMPT = """你是回答质检员。下面有一段候选回答、用户问题与对应的参考资料。

你的任务：逐条核对候选回答中的事实性陈述（数字、型号、参数、价格、政策、因果结论），
对照参考资料判断每条陈述属于哪种情况：
- 有依据：资料中明确支持
- 无依据：资料中找不到对应信息
- 矛盾：与资料内容冲突
- 臆测：超出资料内容的主观推测

判定规则：
- 只要存在「无依据 / 矛盾 / 臆测」中的任意一项，verdict 必须为 "revise"；
- 全部陈述都能在参考资料中找到依据，才判 "pass"。

用户问题：
{question}

参考资料：
{context}

候选回答：
{draft}

请只输出 JSON，格式：{{"verdict": "pass|revise", "issues": ["问题1", "问题2"]}}
- verdict: "pass"（无需修改）或 "revise"（需要修改）
- issues: 列出需要修正的具体问题（verdict=pass 时为空数组）
"""

# 重写：携带质检问题重新生成
REVISE_PROMPT = """你是知识库问答助手。上一版回答经过质检，存在以下问题需要修正：

{issues}

修正要求：
1. 只依据参考资料作答，禁止编造或推测；
2. 修正上述问题，保留回答中正确的部分；
3. 引用资料内容时在句末标注 [序号]，序号对应下方「参考资料」的编号。

参考资料：
{context}

用户问题：
{question}

请重新回答：
"""


async def _generate(messages: list) -> str:
    """调用 LLM 流式生成完整回答（Self-RAG 需要完整草稿才能校验）。"""
    parts: list[str] = []
    async for chunk in get_llm().astream(messages):
        if getattr(chunk, "content", None):
            parts.append(chunk.content)
    return "".join(parts).strip()


async def _critic(question: str, context: str, draft: str) -> dict:
    """critic：对照参考资料核对草稿事实性，返回 {"verdict","issues"}。

    解析失败（非法 JSON / 模型异常）一律降级为 pass，避免自省环节阻塞主流程。
    """
    llm = get_llm().bind(response_format={"type": "json_object"})
    prompt = CRITIC_PROMPT.format(question=question, context=context, draft=draft)
    resp = await llm.ainvoke([SystemMessage(content=prompt)])
    text = getattr(resp, "content", "")
    data = None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        # 兜底：提取首个 {...} 片段
        m = re.search(r"\{.*\}", text, re.S)
        if m is not None:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, dict):
        return {"verdict": "pass", "issues": []}
    return {
        "verdict": "pass" if data.get("verdict") != "revise" else "revise",
        "issues": data.get("issues", []) or [],
    }


def _build_revise_messages(
    question: str, history: list[dict], context: str, draft: str, issues: list[str]
) -> list:
    """组装重写消息：质检反馈 + 参考资料 + 历史 + 上一版草稿。"""
    feedback = "\n".join(f"- {i}" for i in issues) if issues else "- 回答与参考资料不一致"
    messages: list = [
        SystemMessage(content=REVISE_PROMPT.format(issues=feedback, context=context, question=question))
    ]
    for msg in history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=f"上一版回答：\n{draft}\n\n请按上述修正要求重新回答。"))
    return messages


async def self_rag_answer(
    question: str,
    history: list[dict],
    hits: list[dict],
    on_stage: Callable[[str], Awaitable[None]] | None = None,
    summary: str | None = None,
) -> tuple[str, dict]:
    """Self-RAG 主入口。

    Args:
        question: 用户问题
        history: 多轮对话历史（最近窗口原文）
        hits: 混合检索命中（rag_chain.retrieve 的结果）
        on_stage: 可选回调，阶段变化时通知调用方（"generating"/"criticizing"/"revising"）
        summary: 会话滚动摘要（更早对话的压缩记忆，可空）

    Returns:
        (final_answer, reflection)
        reflection: {"enabled", "rounds", "revised", "issues"} —— 随 SSE done 事件返回，
                    前端可展示"已自动核对事实"标识。
    """
    context = format_context(hits)
    messages = rag_build_messages(question, history, context, summary=summary)
    reflection = {
        "enabled": settings.SELF_RAG_ENABLED,
        "rounds": 0,
        "revised": False,
        "issues": [],
    }

    if not settings.SELF_RAG_ENABLED:
        return await _generate(messages), reflection

    if on_stage is not None:
        await on_stage("generating")
    draft = await _generate(messages)

    for round_no in range(settings.SELF_RAG_MAX_ROUNDS):
        if on_stage is not None:
            await on_stage("criticizing")
        # 先记录本轮自省尝试（即使 critic 异常，也算发起了核对）
        reflection["rounds"] = round_no + 1
        try:
            critic = await _critic(question, context, draft)
        except Exception:  # noqa: BLE001 —— critic 异常降级，保留草稿
            return draft, reflection
        if critic.get("verdict") == "pass":
            return draft, reflection

        # 需要重写
        reflection["revised"] = True
        reflection["issues"] = critic.get("issues", [])
        if on_stage is not None:
            await on_stage("revising")
        try:
            draft = await _generate(
                _build_revise_messages(question, history, context, draft, reflection["issues"])
            )
        except Exception:  # noqa: BLE001 —— 重写失败保留旧草稿
            return draft, reflection

    return draft, reflection
