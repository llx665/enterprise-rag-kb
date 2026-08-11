"""Agent 工具单元测试：安全计算 / 日历农历 / 天气。

不发起真实网络请求：天气测试直接种缓存，验证缓存命中分支。
"""
import time

from app.services.tools import _WEATHER_CACHE, calculate, get_calendar, get_month_calendar, get_weather


# ---------- 安全计算 ----------
def test_calculate_basic():
    r = calculate.invoke({"expression": "(2+3)*4"})
    assert "20" in r


def test_calculate_power():
    r = calculate.invoke({"expression": "2**10"})
    assert "1024" in r


def test_calculate_discount_chain():
    # 星辰 X1 Pro 满减 + 折后价（对应 Agent 演示场景）
    r = calculate.invoke({"expression": "1200*0.85-50"})
    assert "970" in r


def test_calculate_functions():
    r = calculate.invoke({"expression": "sqrt(16)+sin(pi/2)"})
    assert "5" in r


def test_calculate_chinese_symbols():
    # 中文运算符与全角符号归一化：10*5/2**2 = 12.5
    r = calculate.invoke({"expression": "10×5÷2^2"})
    assert "12.5" in r


def test_calculate_rejects_unsafe():
    # AST 白名单：任何非白名单节点都被拒绝，绝不允许执行任意代码
    unsafe = ["__import__('os')", "1;2", "open('x')", "a.b", "lambda:1"]
    for expr in unsafe:
        r = calculate.invoke({"expression": expr})
        assert "无法解析" in r or "不支持的运算" in r, f"{expr!r} 应当被拒绝，实际返回 {r!r}"


def test_calculate_empty():
    r = calculate.invoke({"expression": "  "})
    assert "空" in r


# ---------- 日历 / 农历 ----------
def test_calendar_today():
    r = get_calendar.invoke({"date": "today"})
    assert "年" in r and "月" in r and "日" in r
    assert "星期" in r and "农历" in r


def test_calendar_specific_date():
    # 2026-08-11 是星期二
    r = get_calendar.invoke({"date": "2026-08-11"})
    assert "2026年8月11日" in r and "星期二" in r and "农历" in r


def test_calendar_invalid_date():
    r = get_calendar.invoke({"date": "2026-13-99"})
    assert "有误" in r or "无法" in r


def test_month_calendar():
    r = get_month_calendar.invoke({"year": 2026, "month": 8})
    assert "2026年8月日历" in r
    assert "一 二 三 四 五 六 日" in r  # 表头为空格分隔
    assert "31" in r  # 8 月有 31 天


def test_month_calendar_default():
    r = get_month_calendar.invoke({})
    assert "日历" in r


# ---------- 天气（不触网，验证缓存命中） ----------
async def test_weather_empty_city():
    r = await get_weather.ainvoke({"city": ""})
    assert "城市" in r


async def test_weather_cache_hit():
    # 直接种 30 分钟有效缓存，命中时不发起网络请求
    _WEATHER_CACHE["北京"] = (time.time(), "北京今日天气：实时 31°C，☀️ 晴")
    r = await get_weather.ainvoke({"city": "北京"})
    assert r == "北京今日天气：实时 31°C，☀️ 晴"
