"""RAG 检索评测脚本：衡量混合检索（稠密 + BM25 + RRF）的命中率与延迟。

用法（在 backend 目录下运行，需本地 Qdrant 已启动、知识库已入库）：
    cd backend && .venv/Scripts/python.exe ..\\scripts\\eval_rag.py

输出：每个问题的检索命中情况 + 整体 hit@5 与延迟统计（可作为论文/简历数据）。
"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import os  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import asyncio  # noqa: E402

from app.services.retriever import hybrid_retrieve  # noqa: E402

# 用例：(问题, 期望命中的文档名)
CASES = [
    ("七天无理由退货的具体政策是什么", "售后与会员.md"),
    ("星辰 X1 Pro 手机支持多少瓦快充", "手机数码.md"),
    ("对开门冰箱的能效等级是多少", "家用电器.md"),
    ("服装尺码怎么选择", "服饰鞋帽.md"),
    ("生鲜坏了怎么赔付", "食品生鲜.md"),
    ("偏远地区配送要多久", "物流配送.md"),
    ("化妆品备案信息在哪里查", "美妆个护.md"),
    ("会员等级有哪些，如何升级", "售后与会员.md"),
    ("星辰 X1 Pro 的价格是多少", "手机数码.md"),
    ("平台上有哪些商品品类", "商品知识库.md"),
]

TOP_K = 5


async def main() -> None:
    # 预热：首次调用会加载本地 embedding 模型，不计入统计
    print("[warmup] 加载向量模型并首次检索…")
    await hybrid_retrieve("星辰 X1 Pro 手机", top_k=TOP_K)
    print("[warmup] 完成\n")

    rows: list[dict] = []
    for q, expected in CASES:
        t0 = time.perf_counter()
        hits = await hybrid_retrieve(q, top_k=TOP_K)
        ms = (time.perf_counter() - t0) * 1000
        docs = [h["doc_name"] for h in hits]
        hit = expected in docs
        rank = docs.index(expected) + 1 if hit else None
        rows.append({"q": q, "expected": expected, "hit": hit, "rank": rank, "ms": ms, "docs": docs})

    # ---------- 明细表 ----------
    print("=" * 110)
    print(f"{'问题':<28}{'期望文档':<18}{'命中':<6}{'排序':<6}{'延迟ms':<10}")
    print("-" * 110)
    for r in rows:
        print(
            f"{r['q'][:26]:<28}{r['expected']:<18}"
            f"{'✔' if r['hit'] else '✘':<6}"
            f"{(str(r['rank']) if r['rank'] else '-'):<6}"
            f"{r['ms']:<10.0f}"
        )

    # ---------- 命中详情（前3个来源） ----------
    print("\n--- 各问题 Top-3 检索来源 ---")
    for r in rows:
        tops = r["docs"][:3]
        mark = "✔" if r["hit"] else "✘"
        print(f"{mark} {r['q'][:24]:<26} -> " + ", ".join(tops))

    # ---------- 汇总统计 ----------
    n = len(rows)
    n_hit = sum(1 for r in rows if r["hit"])
    latencies = sorted(r["ms"] for r in rows)
    avg = sum(latencies) / n
    p95 = latencies[int(n * 0.95) - 1] if n >= 2 else latencies[-1]
    top1 = sum(1 for r in rows if r["rank"] == 1)

    print("\n" + "=" * 110)
    print("RAG 混合检索评测汇总")
    print("-" * 110)
    print(f"用例数            : {n}")
    print(f"hit@{TOP_K} 命中率     : {n_hit}/{n} = {n_hit / n:.1%}")
    print(f"@1 命中           : {top1}/{n} = {top1 / n:.1%}")
    print(f"平均检索延迟      : {avg:.0f} ms")
    print(f"P95 检索延迟      : {p95:.0f} ms")
    print(f"检索链路          : 稠密(Qdrant+bge-small-zh) + 稀疏(jieba+BM25) + RRF 融合")
    print("=" * 110)


if __name__ == "__main__":
    asyncio.run(main())
