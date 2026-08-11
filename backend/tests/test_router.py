"""意图路由 is_tool_intent 单元测试：工具类问题 vs 纯 RAG 商品问题。"""
from app.services.router import is_tool_intent


# ---------- 数学 / 计算 ----------
def test_arithmetic_expression():
    assert is_tool_intent("2+3等于多少")
    assert is_tool_intent("10*0.85 是多少")
    assert is_tool_intent("2^10")


def test_math_words():
    assert is_tool_intent("帮我算一下 5 的平方")
    assert is_tool_intent("2的10次方")
    assert is_tool_intent("根号16")
    assert is_tool_intent("100的百分之三十")
    assert is_tool_intent("求和 1 到 10")


def test_discount_and_manjian():
    assert is_tool_intent("星辰X1 Pro 打85折后多少钱")
    assert is_tool_intent("打八五折")
    assert is_tool_intent("满300减50")


# ---------- 天气 ----------
def test_weather():
    assert is_tool_intent("北京今天天气怎么样")
    assert is_tool_intent("上海明天会下雨吗")
    assert is_tool_intent("查一下杭州的空气质量")


# ---------- 日历 / 农历 ----------
def test_calendar():
    assert is_tool_intent("今天是几月几号，农历几号")
    assert is_tool_intent("这个月日历")
    assert is_tool_intent("现在是几点")
    assert is_tool_intent("今天星期几")
    assert is_tool_intent("下个节假日是什么时候")


# ---------- 纯商品咨询：保持走 RAG，不误路由到 Agent ----------
def test_kb_questions_stay_rag():
    assert not is_tool_intent("星辰X1 Pro 的电池续航怎么样")
    assert not is_tool_intent("这款手机支持多少瓦快充")
    assert not is_tool_intent("七天无理由退货政策是什么")
    assert not is_tool_intent("会员等级有哪些")
    assert not is_tool_intent("运费怎么算")


# ---------- 边界 ----------
def test_empty_and_none():
    assert not is_tool_intent("")
    assert not is_tool_intent(None)  # type: ignore[arg-type]
