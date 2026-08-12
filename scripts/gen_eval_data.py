"""生成 RAGAS 评估数据集：对 eval_golden.json 逐条执行「检索 + 生成」，落盘 eval_dataset.json。

在**应用 venv**（backend/.venv）运行，直接 import backend 服务（不开 HTTP、不依赖 Qdrant 在线）：
    cd backend && .venv/Scripts/python.exe ../scripts/gen_eval_data.py

产出 eval_output/eval_dataset.json：
    [{"question", "ground_truth", "contexts", "context_docs", "answer"}]
其中 contexts 是检索命中的子块内容（RAGAS context_* 指标用），context_docs 是来源文档名
（hit@k 统计用），answer 是 RAG 链路生成的真实回答。

用法：
    python gen_eval_data.py            # 全量评估
    python gen_eval_data.py --limit 3  # 只评估前 3 条（调试用）
"""
import argparse
import asyncio
import json
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 允许 import backend 包（scripts/ 与 backend/ 同级）
BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, BACKEND_DIR)

GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_golden.json")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_output")
OUT_PATH = os.path.join(OUT_DIR, "eval_dataset.json")


async def build_row(
    question: str,
    ground_truth: str,
    retrieve=None,
    llm=None,
) -> dict:
    """单条评估数据：检索 -> 上下文 -> LLM 生成。

    retrieve / llm 参数可注入（单测用），缺省走真实服务。
    """
    from app.services import rag_chain

    hits = await (retrieve or rag_chain.retrieve)(question)
    contexts = [h.get("content", "") for h in hits]
    context_docs = [h.get("doc_name", "") for h in hits]
    context_text = rag_chain.format_context(hits)
    messages = rag_chain.build_messages(question, [], context_text)
    resp = await (llm or rag_chain.get_llm()).ainvoke(messages)
    answer = (getattr(resp, "content", "") or "").strip()
    return {
        "question": question,
        "ground_truth": ground_truth,
        "contexts": contexts,
        "context_docs": context_docs,
        "answer": answer,
    }


async def main(limit: int | None) -> None:
    golden = json.loads(open(GOLDEN_PATH, encoding="utf-8").read())
    if limit:
        golden = golden[:limit]

    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    total_llm = 0.0
    for i, item in enumerate(golden, start=1):
        t0 = time.perf_counter()
        print(f"[{i}/{len(golden)}] {item['question'][:40]}…", flush=True)
        row = await build_row(item["question"], item["ground_truth"])
        latency = time.perf_counter() - t0
        total_llm += latency
        row["latency_s"] = round(latency, 2)
        rows.append(row)
        print(f"    命中: {row['context_docs'][:3]} | 延迟 {row['latency_s']}s", flush=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    avg = total_llm / max(len(rows), 1)
    print(f"\n✅ 已生成 {len(rows)} 条评估数据 -> {OUT_PATH}")
    print(f"   平均单条延迟: {avg:.2f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 RAGAS 评估数据集")
    parser.add_argument("--limit", type=int, default=None, help="只评估前 N 条")
    args = parser.parse_args()
    asyncio.run(main(args.limit))
