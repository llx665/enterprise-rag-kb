"""问题意图路由：判断用户问题是否需要工具（计算/天气/日历）而非纯知识库检索。

设计动机：纯 RAG 只适合知识库内的问题；引入 Agent 后，把「明确需要工具」的问题
路由给 Agent（可调用计算/天气/日历/检索工具），其余问题走原有高性能 RAG 链路，
两者互补，互不拖慢：
- 商品类问题：走 RAG（混合检索 + 语义缓存 + 引用标注）
- 工具类问题：走 Agent（意图明确，跳过语义缓存，避免“2+2”误命中缓存答案）
"""
import re

# 数学表达式：数字 + 运算符 + 数字（如 2+3、10*0.85、5^2）
_ARITHMETIC = re.compile(r"\d[\s]*[+\-*/×÷^][\s]*\d")

# 强数学意图词：出现即判定为计算类
_MATH_WORDS = [
    "计算", "算一下", "算一算", "帮我算", "等于", "求值",
    "平方", "立方", "次方", "根号", "开方",
    "百分之", "打折", "折后", "折扣", "几成",
    "满减", "凑单", "求和", "多少倍",
]
_MATH_RE = re.compile("|".join(_MATH_WORDS))

# 折扣 / 满减等口语化写法（打85折、打八五折、满300减50）
_DISCOUNT_RE = re.compile(r"打\s*[0-9０-９一二三四五六七八九十.．]+\s*折")
_MANJIAN_RE = re.compile(r"满\s*\d+\s*减\s*\d+")

# 天气意图词
_WEATHER_WORDS = [
    "天气", "气温", "下雨", "下雪", "降雨", "降雪", "台风",
    "雾霾", "空气质量", "风力", "湿度", "天气预报", "会下雨", "会不会下",
]
_WEATHER_RE = re.compile("|".join(_WEATHER_WORDS))

# 日历 / 日期 / 农历 意图词
_CALENDAR_WORDS = [
    "农历", "阴历", "星期几", "礼拜几", "周几", "几号", "几月几日",
    "日历", "几点", "时辰", "黄历", "生肖", "是什么日子", "节假日", "节日",
]
_CALENDAR_RE = re.compile("|".join(_CALENDAR_WORDS))


def is_tool_intent(question: str) -> bool:
    """判断问题是否需要 Agent 工具。

    命中「算术表达式 / 计算词 / 天气词 / 日历词」任一即返回 True。
    纯商品咨询（价格、参数、售后等）不命中，走 RAG。
    """
    q = (question or "").strip()
    if not q:
        return False
    if _ARITHMETIC.search(q):
        return True
    if _MATH_RE.search(q):
        return True
    if _DISCOUNT_RE.search(q) or _MANJIAN_RE.search(q):
        return True
    if _WEATHER_RE.search(q):
        return True
    if _CALENDAR_RE.search(q):
        return True
    return False
