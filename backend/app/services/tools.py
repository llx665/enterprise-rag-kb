"""Agent 工具集：计算 / 天气 / 日历农历 / 知识库检索。

每个工具都是 LangChain Tool，供 LangGraph Agent（create_react_agent）调用：
- calculate          安全数学计算（AST 白名单求值，杜绝 eval 注入）
- get_weather        实时天气 + 未来 3 天预报（Open-Meteo 免费 API，无需 Key）
- get_calendar       公历 + 星期 + 农历日期
- get_month_calendar 月历表格
- retrieve_knowledge 复用混合检索，让 Agent 也能回答知识库问题
"""
import ast
import calendar as _cal
import math
import operator
import time
from datetime import datetime

import httpx
from langchain_core.tools import tool

from .retriever import hybrid_retrieve

# ==========================================================
# 1. 安全数学计算（AST 白名单，不执行任意代码）
# ==========================================================
_SAFE_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_SAFE_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_SAFE_FUNCS = {
    "sqrt": math.sqrt, "pow": pow, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "log": math.log, "log10": math.log10, "ln": math.log, "exp": math.exp,
    "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
    "factorial": math.factorial, "pi": math.pi, "e": math.e, "tau": math.tau,
}


def _eval_ast(node):
    """递归求值 AST，只允许白名单内的运算与函数。"""
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
        return _SAFE_BINOPS[type(node.op)](_eval_ast(node.left), _eval_ast(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARY:
        return _SAFE_UNARY[type(node.op)](_eval_ast(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _SAFE_FUNCS:
        return _SAFE_FUNCS[node.func.id](*[_eval_ast(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _SAFE_FUNCS:
        return _SAFE_FUNCS[node.id]
    raise ValueError("表达式包含不支持的运算")


@tool
def calculate(expression: str) -> str:
    """计算数学表达式。输入必须是合法的数学表达式（用数字和小数点），支持 + - * / // % ** 和括号，
    以及 sqrt/pow/sin/cos/tan/log/ln/abs/round/floor/ceil/factorial/pi/e 等函数。
    示例：(2+3)*4、2**10、sqrt(16)、sin(pi/2)、100*0.85、1200*0.9-50。
    请把中文里的数字和运算词转换成表达式，如“二加三”写成 2+3，“一千二打八五折”写成 1200*0.85。"""
    expr = (expression or "").strip()
    expr = (
        expr.replace("×", "*").replace("÷", "/").replace("^", "**")
        .replace("（", "(").replace("）", ")").replace("．", ".")
        .replace("π", "pi").replace("％", "/100")
    )
    if not expr:
        return "表达式为空"
    try:
        result = _eval_ast(ast.parse(expr, mode="eval"))
    except Exception as e:
        return f"无法解析该表达式，请写成数学表达式（如 2+3、100*0.85）：{e}"
    if isinstance(result, float):
        result = round(result, 10)
        if result.is_integer():
            result = int(result)
    return f"{expr} = {result}"


# ==========================================================
# 2. 实时天气（Open-Meteo，免费免 Key；结果缓存 30 分钟）
# ==========================================================
_WMO_CODE_ZH = {
    0: "☀️ 晴", 1: "🌤️ 基本晴", 2: "⛅ 多云", 3: "☁️ 阴",
    45: "🌫️ 雾", 48: "🌫️ 冻雾", 51: "🌦️ 毛毛雨", 53: "🌦️ 小雨", 55: "🌧️ 中雨",
    61: "🌧️ 小雨", 63: "🌧️ 中雨", 65: "🌧️ 大雨", 66: "🌧️ 冻雨", 67: "🌧️ 冻雨",
    71: "❄️ 小雪", 73: "❄️ 中雪", 75: "❄️ 大雪", 77: "❄️ 雪粒",
    80: "🌧️ 阵雨", 81: "🌧️ 阵雨", 82: "⛈️ 强阵雨",
    85: "🌨️ 阵雪", 86: "🌨️ 强阵雪",
    95: "⛈️ 雷阵雨", 96: "⛈️ 雷阵雨伴冰雹", 99: "⛈️ 强雷阵雨伴冰雹",
}

_WEATHER_CACHE: dict[str, tuple[float, str]] = {}


@tool
async def get_weather(city: str) -> str:
    """查询指定城市今天的实时天气与未来 3 天天气预报。city 为中文城市名，如“北京”“上海”“广州”“成都”。"""
    city = (city or "").strip().replace("市", "")
    if not city:
        return "请提供要查询的城市名"
    now_ts = time.time()
    cached = _WEATHER_CACHE.get(city)
    if cached and now_ts - cached[0] < 1800:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "zh", "format": "json"},
            )
            geo.raise_for_status()
            results = (geo.json().get("results") or [])
            if not results:
                return f"未找到城市「{city}」，请确认城市名是否正确"
            loc = results[0]
            lat, lon, name = loc["latitude"], loc["longitude"], loc.get("name", city)

            f = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current_weather": "true",
                    "daily": "temperature_2m_max,temperature_2m_min,weathercode,"
                             "precipitation_probability_max,wind_speed_10m_max",
                    "timezone": "auto", "forecast_days": 3,
                },
            )
            f.raise_for_status()
            d = f.json()

        cur = d.get("current_weather") or {}
        daily = d.get("daily") or {}
        dates = daily.get("time") or []
        _code = lambda c: _WMO_CODE_ZH.get(c, f"天气代码{c}")
        _at = lambda key, i: daily.get(key, [])[i] if len(daily.get(key, [])) > i else None

        parts = [f"{name}今日天气"]
        if cur:
            parts.append(f"实时：{cur.get('temperature')}°C，{_code(cur.get('weathercode'))}")
        for i, label in zip(range(3), ["今天", "明天", "后天"]):
            if i >= len(dates):
                break
            tmax, tmin, wcode = _at("temperature_2m_max", i), _at("temperature_2m_min", i), _at("weathercode", i)
            precip, wind = _at("precipitation_probability_max", i), _at("wind_speed_10m_max", i)
            line = f"{label}：{tmax}°C / {tmin}°C，{_code(wcode) if wcode is not None else '-'}"
            if precip is not None:
                line += f"，降水概率 {precip}%"
            if wind is not None:
                line += f"，最大风速 {wind}km/h"
            parts.append(line)
        text = "\n".join(parts)
        _WEATHER_CACHE[city] = (now_ts, text)
        return text
    except httpx.HTTPError as e:
        return f"天气服务暂时不可用，请稍后再试（{e.__class__.__name__}）"


# ==========================================================
# 3. 日历 / 农历（zhdate）
# ==========================================================
try:
    from zhdate import ZhDate
except ImportError:
    ZhDate = None

_WEEK = "一二三四五六日"


@tool
def get_calendar(date: str = "today") -> str:
    """查询日期信息：公历日期、星期几、农历日期。date 参数为 'today'（今天）或 'YYYY-MM-DD'（如 2026-08-11）。
    适合回答“今天几号”“星期几”“农历几号”等问题。"""
    date = (date or "today").strip().lower()
    try:
        if date in ("today", "今天", "now", ""):
            dt = datetime.now()
        else:
            s = date.replace("-", "").replace("/", "")
            dt = datetime.strptime(s, "%Y%m%d")
        week = _WEEK[dt.weekday()]
        if ZhDate:
            lunar = f"农历{ZhDate.from_datetime(dt).chinese()}"
        else:
            lunar = "（农历组件未安装）"
        return f"{dt.year}年{dt.month}月{dt.day}日，星期{week}，{lunar}"
    except Exception as e:
        return f"日期格式有误，请用 today 或 YYYY-MM-DD：{e}"


@tool
def get_month_calendar(year: int | None = None, month: int | None = None) -> str:
    """查看某个月份的日历表。year/month 缺省时为当前月份。适合回答“这个月的日历”“下个月有哪些日期”等问题。"""
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    try:
        start_weekday = _cal.monthrange(y, m)[0]  # 0=周一
        ndays = _cal.monthrange(y, m)[1]
        today = now.day if (y == now.year and m == now.month) else 0
        cells = ["　"] * start_weekday + [str(i) for i in range(1, ndays + 1)]
        header = " ".join(_WEEK)
        rows = []
        for i in range(0, len(cells), 7):
            week_cells = cells[i:i + 7]
            week_cells += ["　"] * (7 - len(week_cells))
            rows.append(" ".join((f"*{c}*" if c.isdigit() and int(c) == today else c) for c in week_cells))
        return f"{y}年{m}月日历（*加星* 为今天）：\n{header}\n" + "\n".join(rows)
    except Exception as e:
        return f"无法生成日历：{e}"


# ==========================================================
# 4. 知识库检索（复用混合检索，让 Agent 也能答商品问题）
# ==========================================================
@tool
async def retrieve_knowledge(query: str) -> str:
    """检索电商知识库。当用户询问商品参数、价格、型号、功能介绍、售后政策、退换货、
    物流配送、会员等级、优惠活动等知识库中的内容时使用。输入为要检索的关键问题。"""
    hits = await hybrid_retrieve(query, top_k=6)
    if not hits:
        return "知识库中没有找到相关内容。"
    lines = []
    for i, h in enumerate(hits, start=1):
        lines.append(f"[{i}] 来源：{h['doc_name']}\n{h['content']}")
    return "\n\n".join(lines)
