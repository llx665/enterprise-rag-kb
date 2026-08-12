# -*- coding: utf-8 -*-
"""本地接口压测：语义缓存命中路径 / 冷路径（真实 LLM 生成）的真实 QPS 与延迟分位。

前置：
- 后端已在本地以压测配置运行（建议 DATABASE_URL 指向带完整分块语料的库，
  RATE_LIMIT_ENABLED=false 关闭业务限流以测量系统真实容量）：
      cd backend
      DATABASE_URL="sqlite+aiosqlite:///./loadtest.db" RATE_LIMIT_ENABLED=false \
        .venv/Scripts/python.exe -m uvicorn app.main:app --port 8001

用法（在 backend/.venv 下运行，依赖 httpx）：
      .venv/Scripts/python.exe ../scripts/load_test.py --base http://127.0.0.1:8001

产出 scripts/eval_output/load_test_report.md —— 缓存命中 QPS / 冷路径 QPS / 延迟分位。

口径说明（保证数字可复现、不夸大）：
- 缓存命中路径：同一批问题重复请求，命中语义缓存（cosine>0.93），不调用 LLM；
  但每次请求仍含 query 向量化（本地 ONNX）、会话/消息落库 —— 是真实接口吞吐。
- 冷路径：全新的、缓存中不存在的问题，走完整 混合检索 + Self-RAG（草稿+自省）+
  DeepSeek LLM —— 吞吐受 LLM 延迟与并发限制，是"首次提问"的真实能力。
- 限流关闭仅用于测量系统容量；真实生产有 20 次/分/用户的业务限流（防配额滥用）。
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).resolve().parent / "eval_output"

# 预热缓存的问题（代表知识库高频提问，逐条真实生成并写入语义缓存）
WARM_QUESTIONS = [
    "星辰 X1 Pro 的电池容量和快充功率是多少？",
    "冷峰 520L 冰箱一天耗电多少度？",
    "平台满多少金额包邮？",
    "防晒霜应该什么时候涂？多久补涂？",
    "金卡会员享受哪些权益？",
    "运动鞋尺码应该怎么选？",
    "羽绒服应该怎么清洗保养？",
    "退货后多久能退款到账？",
    "星辰 Neo 5 支持多大的快充功率？",
    "电子产品的保修期是怎么规定的？",
]

# 冷路径问题（与缓存问题不同，确保未命中缓存）
COLD_QUESTIONS = [
    "视界电视支持免费挂墙安装吗？",
    "酸奶开封后能放几天？",
    "新人首单有什么优惠？",
    "能量块 20000 移动电源能带上飞机吗？",
    "净澈洗衣机保修多久？",
    "平台支持京东白条支付吗？",
    "城市行者休闲夹克多少钱？",
    "红酒应该怎么保存？",
    "OrderStatus 枚举包含哪些订单状态？",
    "水漾保湿精华液多少钱？",
    "商品有质量问题可以免费换新吗？",
    "618 大促期间发货会延迟吗？",
]


def parse_sse(text: str) -> dict:
    """解析一个 SSE 响应块，返回最后一个 done/error 事件负载（或 {}）。"""
    last = {}
    for block in text.split("\n\n"):
        event, data = "message", ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data += line[6:].strip()
        if data:
            try:
                payload = json.loads(data)
                if event in ("done", "error"):
                    last = {"event": event, **payload}
            except json.JSONDecodeError:
                pass
    return last


async def chat_once(client: httpx.AsyncClient, token: str, question: str, timeout: float) -> dict:
    """发一次问答请求，返回 (elapsed_s, cached, answer_len)。"""
    t0 = time.perf_counter()
    try:
        async with client.stream(
            "POST",
            "/api/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"session_id": None, "question": question},
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            body = ""
            async for chunk in resp.aiter_text():
                body += chunk
        elapsed = time.perf_counter() - t0
        last = parse_sse(body)
        if last.get("event") == "error":
            return {"elapsed": elapsed, "cached": False, "answer_len": 0, "error": last.get("detail")}
        return {
            "elapsed": elapsed,
            "cached": bool(last.get("cached")),
            "answer_len": len(body),
        }
    except Exception as e:  # noqa: BLE001
        return {"elapsed": time.perf_counter() - t0, "cached": False, "answer_len": 0, "error": str(e)}


async def run_phase(client, token, questions, concurrency, label):
    """按并发跑一批问题，返回 QPS + 延迟分位。"""
    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    failures = 0

    async def worker(q: str):
        nonlocal failures
        async with sem:
            r = await chat_once(client, token, q, timeout=60)
            if r.get("error"):
                failures += 1
            results.append(r)

    t0 = time.perf_counter()
    await asyncio.gather(*(worker(q) for q in questions))
    wall = time.perf_counter() - t0
    ok = [r for r in results if not r.get("error")]

    lat = sorted(r["elapsed"] for r in ok)
    n = len(ok)
    p = lambda x: lat[min(n - 1, int(x * n))] if lat else 0.0  # noqa: E731
    qps = n / wall if wall > 0 else 0.0
    cached_hits = sum(1 for r in ok if r.get("cached"))
    return {
        "label": label,
        "total": len(questions),
        "ok": n,
        "failures": failures,
        "wall_s": wall,
        "qps": qps,
        "p50": p(0.50),
        "p90": p(0.90),
        "p99": p(0.99),
        "mean": statistics.mean(lat) if lat else 0.0,
        "cache_hits": cached_hits,
    }


def write_report(phases: list[dict], base_url: str) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"load_test_report_{ts}.md"
    lines = [
        "# 压测报告（真实接口 QPS）",
        "",
        f"- 测试时间：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 目标：`{base_url}`（本地 uvicorn，`RATE_LIMIT_ENABLED=false` 测量系统真实容量）",
        f"- 语义缓存：cosine 相似度阈值 {0.93}，命中则不调用 LLM",
        "",
        "## 结果",
        "",
        "| 场景 | 请求数 | 成功 | 失败 | QPS | 平均延迟 | P50 | P90 | P99 | 缓存命中 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for ph in phases:
        lines.append(
            f"| {ph['label']} | {ph['total']} | {ph['ok']} | {ph['failures']} | "
            f"{ph['qps']:.1f} | {ph['mean']*1000:.0f}ms | {ph['p50']*1000:.0f}ms | "
            f"{ph['p90']*1000:.0f}ms | {ph['p99']*1000:.0f}ms | {ph['cache_hits']} |"
        )
    lines += [
        "",
        "## 口径说明",
        "",
        "- **缓存命中路径**：预热后对同一批问题重复请求，全部命中语义缓存（不调用 DeepSeek）；仍包含 query 向量化 + 会话/消息落库，代表接口真实吞吐。",
        "- **冷路径**：全新问题，走混合检索 + Self-RAG（草稿+自省两段生成）+ DeepSeek，吞吐受 LLM 延迟与并发上限约束，代表首次提问的真实能力。",
        "- 生产环境默认开启 20 次/分/用户的业务限流（防配额滥用），此处关闭限流测量的是系统容量上限。",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ 压测报告已写入 {out}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 问答接口压测")
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--concurrency-cache", type=int, default=10)
    parser.add_argument("--cache-requests", type=int, default=60)
    parser.add_argument("--concurrency-cold", type=int, default=4)
    args = parser.parse_args()
    BASE = args.base.rstrip("/")

    async with httpx.AsyncClient(base_url=BASE) as client:
        # ---------- 注册 / 登录专用压测用户 ----------
        import random

        user = f"loadtest_{random.randint(100000, 999999)}"
        try:
            r = await client.post(
                "/api/auth/register", json={"username": user, "password": "loadtest123456"}
            )
            r.raise_for_status()
            print(f"[setup] 注册用户 {user}")
        except httpx.HTTPStatusError as e:
            print(f"[setup] 注册失败（{e.response.status_code}），尝试直接登录")
        r = await client.post("/api/auth/login", json={"username": user, "password": "loadtest123456"})
        r.raise_for_status()
        token = r.json()["access_token"]

        # ---------- Phase 1: 预热语义缓存（逐条真实生成） ----------
        print(f"[warm] 预热 {len(WARM_QUESTIONS)} 条缓存（真实 LLM 生成，约需 30s）...")
        for q in WARM_QUESTIONS:
            res = await chat_once(client, token, q, timeout=120)
            if res.get("error"):
                print(f"[warm] ⚠️ {q[:20]}… 失败: {res['error'][:80]}")
            else:
                print(f"[warm] ✔ {q[:24]}… ({res['elapsed']:.1f}s)")
        # 验证缓存确实写入（重发第一条应命中）
        check = await chat_once(client, token, WARM_QUESTIONS[0], timeout=30)
        print(f"[warm] 缓存验证: 首问重发 -> {'命中' if check.get('cached') else '未命中!'}")

        # ---------- Phase 2: 缓存命中路径吞吐 ----------
        import itertools

        qs_cache = list(itertools.islice(itertools.cycle(WARM_QUESTIONS), args.cache_requests))
        print(f"[cache] 缓存命中路径 {len(qs_cache)} 请求，并发 {args.concurrency_cache} ...")
        ph_cache = await run_phase(client, token, qs_cache, args.concurrency_cache, "缓存命中路径")

        # ---------- Phase 3: 冷路径吞吐（全新问题） ----------
        print(f"[cold] 冷路径 {len(COLD_QUESTIONS)} 请求，并发 {args.concurrency_cold} ...")
        ph_cold = await run_phase(client, token, COLD_QUESTIONS, args.concurrency_cold, "冷路径（真实 LLM 生成）")

    OUT_DIR.mkdir(exist_ok=True)
    write_report([ph_cache, ph_cold], BASE)
    print(
        f"[done] 缓存命中 QPS={ph_cache['qps']:.1f}  p50={ph_cache['p50']*1000:.0f}ms  "
        f"| 冷路径 QPS={ph_cold['qps']:.1f}  p50={ph_cold['p50']*1000:.0f}ms"
    )


if __name__ == "__main__":
    asyncio.run(main())
