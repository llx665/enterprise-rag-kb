"""RAGAS 评估：在隔离 .venv-eval 中运行真实 ragas 库，产出评测报告。

为什么隔离：应用后端使用 LangChain 1.3，而 ragas 0.2.x 依赖 langchain-core 0.3.x，
同环境必然冲突。本脚本自举：先用应用 venv 创建 .venv-eval 并安装固定版本依赖，
再**用 .venv-eval 的 python 重新执行自身**完成评测（避免用户手动建环境）。

依赖固定版本（规避应用 langchain 1.3 冲突）：
    ragas>=0.2.10,<0.3
    langchain-core==0.3.*
    langchain-openai==0.2.*
    datasets

用法：
    cd backend && .venv/Scripts/python.exe ../scripts/gen_eval_data.py
    cd backend && .venv/Scripts/python.exe ../scripts/eval_ragas.py            # 全流程
    cd backend && .venv/Scripts/python.exe ../scripts/eval_ragas.py --skip-install  # 复用已有 venv

产出 scripts/eval_output/ragas_report_*.md —— 真实可写进简历/论文的数字。

降级链（任一环节失败不阻塞报告）：
- ragas 装不上 / import 失败 -> 只出 hit@k + 抽样回答（标注"ragas 不可用"）
- 无 EMBEDDING_API_KEY -> 只跑 LLM-only 的 faithfulness，其余指标标注"需向量模型"
- 判分单条失败 -> 该条该指标 NaN，其余正常
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent / "backend"
VENV_DIR = SCRIPT_DIR / ".venv-eval"
if os.name == "nt":
    PYTHON = VENV_DIR / "Scripts" / "python.exe"
else:
    PYTHON = VENV_DIR / "bin" / "python"

OUT_DIR = SCRIPT_DIR / "eval_output"

PINNED_DEPS = [
    "ragas>=0.2.10,<0.3",
    "langchain-core==0.3.*",
    "langchain-openai==0.2.*",
    "datasets",
]


def _load_env(path: Path) -> dict:
    """极简 .env 解析（避免依赖 python-dotenv）。"""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


# ==========================================================
# 自举：创建 .venv-eval 并安装固定版本依赖
# ==========================================================
def ensure_venv() -> bool:
    if PYTHON.exists():
        return False  # 已存在，跳过创建
    print(f"[bootstrap] 创建隔离环境 {VENV_DIR} ...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    return True


def install_deps() -> None:
    print(f"[bootstrap] 安装 RAGAS 依赖（首次较慢）...")
    subprocess.run([str(PYTHON), "-m", "pip", "install", "-q", "--disable-pip-version-check", *PINNED_DEPS], check=True)
    print("[bootstrap] 依赖就绪")


# ==========================================================
# 评测主体（运行在 .venv-eval 的 python 下）
# ==========================================================
def _load_dataset() -> list[dict]:
    path = OUT_DIR / "eval_dataset.json"
    if not path.exists():
        print(f"❌ 缺少评估数据集：{path}。请先运行 gen_eval_data.py。")
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def _load_golden() -> dict[str, list[str]]:
    """question -> expected_docs（hit@k 用）。"""
    path = SCRIPT_DIR / "eval_golden.json"
    mapping: dict[str, list[str]] = {}
    if path.exists():
        for item in json.loads(path.read_text(encoding="utf-8")):
            mapping[item["question"]] = item.get("expected_docs", [])
    return mapping


def _compute_hit_k(data: list[dict], golden: dict[str, list[str]], k: int) -> tuple[float, int]:
    hits = 0
    for row in data:
        expected = golden.get(row["question"], [])
        if not expected:
            continue
        docs = row.get("context_docs", [])[:k]
        if any(e in docs for e in expected):
            hits += 1
    total = sum(1 for r in data if golden.get(r["question"]))
    return (hits / total, total) if total else (0.0, 0)


def _fallback_report(data: list[dict], reason: str) -> None:
    """ragas 不可用时的降级报告：hit@k + 抽样回答。"""
    golden = _load_golden()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lines = [
        "# RAGAS 评估报告（降级）",
        "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 样本数：{len(data)}",
        f"- ⚠️ ragas 不可用：{reason}（未产出 LLM 判分指标，仅统计命中率与延迟）",
        "",
        "## 命中率",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
    ]
    for k in (1, 3, 5):
        val, n = _compute_hit_k(data, golden, k)
        lines.append(f"| hit@{k} | {val:.2%}（{int(val * n)}/{n}） |")
    lat = [r.get("latency_s", 0) for r in data]
    if lat:
        lines.append(f"| 平均单条延迟 | {sum(lat) / len(lat):.2f}s |")
    lines += ["", "## 抽样回答", ""]
    for row in data[:3]:
        lines.append(f"**Q：{row['question']}**")
        lines.append(f"A：{row['answer'][:200]}")
        lines.append("")
    out = OUT_DIR / f"ragas_report_{ts}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ 降级报告已写入 {out}")


def run_eval() -> None:
    env = _load_env(BACKEND_DIR / ".env")
    data = _load_dataset()
    golden = _load_golden()

    api_key = env.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ 未找到 DEEPSEEK_API_KEY（backend/.env），无法判分。")
        sys.exit(1)

    from langchain_openai import ChatOpenAI

    judge = ChatOpenAI(
        model=env.get("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=api_key,
        base_url=env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        temperature=0,
    )

    # 向量模型：SiliconFlow bge-m3；无 Key 则只跑 LLM-only 指标
    embed_key = env.get("EMBEDDING_API_KEY") or os.environ.get("EMBEDDING_API_KEY")
    embeddings = None
    if embed_key:
        from langchain_openai import OpenAIEmbeddings

        embeddings = OpenAIEmbeddings(
            model=env.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
            api_key=embed_key,
            base_url=env.get("EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1"),
            check_embedding_ctx_length=False,
        )
    else:
        print("⚠️ 无 EMBEDDING_API_KEY，只跑 LLM-only 的 faithfulness；context_* / answer_relevancy 需向量模型")

    try:
        from ragas import EvaluationDataset, SingleTurnSample, evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
    except Exception as e:  # noqa: BLE001
        _fallback_report(data, f"{e.__class__.__name__}: {e}")
        return

    metrics = [faithfulness]
    embed_metrics = []
    if embeddings is not None:
        embed_metrics = [answer_relevancy, context_recall, context_precision]
        metrics += embed_metrics

    samples = [
        SingleTurnSample(
            user_input=row["question"],
            response=row["answer"],
            retrieved_contexts=row.get("contexts", []),
            reference=row["ground_truth"],
        )
        for row in data
    ]
    dataset = EvaluationDataset(samples=samples)

    print(f"[eval] 判分模型: deepseek-chat | 向量: {'bge-m3' if embeddings else '无'} | 指标: {[m.name for m in metrics]}")
    t0 = time.perf_counter()
    result = evaluate(dataset, metrics=metrics, llm=judge, embeddings=embeddings)
    elapsed = time.perf_counter() - t0

    df = result.to_pandas()
    _write_report(df, data, golden, embeddings is not None, elapsed)


def _write_report(df, data: list[dict], golden: dict[str, list[str]], has_embeddings: bool, elapsed: float) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 只保留数值型指标列（to_pandas 可能混入 reference/retrieved_contexts 等原始字段）
    metric_cols = [
        c
        for c in df.columns
        if c not in ("question", "user_input", "response", "reference", "retrieved_contexts")
        and _is_numeric_col(df[c])
    ]
    lines = [
        "# RAGAS 评估报告",
        "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 样本数：{len(data)}",
        f"- 判分模型：deepseek-chat（RAGAS judge）",
        f"- 向量模型：{'SiliconFlow bge-m3' if has_embeddings else '未配置（无 embedding 指标）'}",
        f"- 评测耗时：{elapsed:.1f}s",
        "",
        "## 总体指标",
        "",
        "| 指标 | 均值 | 含义 |",
        "|---|---|---|",
    ]
    for col in metric_cols:
        if col in df.columns:
            vals = df[col].dropna()
            if len(vals):
                lines.append(f"| {col} | {vals.mean():.4f} | {_metric_meaning(col)} |")
    # 通过率：以 faithfulness >= 阈值视为该 case 通过（0.8 为默认口径，同时列出 0.7/0.9 供参照）
    if "faithfulness" in df.columns:
        fvals = df["faithfulness"].dropna()
        if len(fvals):
            for th in (0.7, 0.8, 0.9):
                n = int((fvals >= th).sum())
                flag = "（默认口径）" if th == 0.8 else ""
                lines.append(f"| 通过率（faithfulness≥{th}） | {n / len(fvals):.1%}（{n}/{len(fvals)}） | 该阈值下通过的比例 {flag} |")
    lines.append("")
    lines.append("## 命中率（检索召回）")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---|")
    for k in (1, 3, 5):
        val, n = _compute_hit_k(data, golden, k)
        lines.append(f"| hit@{k} | {val:.2%}（{int(val * n)}/{n}） |")
    lat = [r.get("latency_s", 0) for r in data]
    if lat:
        lines.append(f"| 平均单条生成延迟 | {sum(lat) / len(lat):.2f}s |")
    lines += ["", "## 每 case 明细", "", "| 问题 | " + " | ".join(metric_cols) + " |", "|---|" + "---|" * len(metric_cols)]
    # to_pandas() 不一定带 question 列，问题名从源数据 data 取（与样本同序对齐）
    for i, (_, row) in enumerate(df.iterrows()):
        q = data[i]["question"][:30] if i < len(data) else "?"
        cells = []
        for c in metric_cols:
            v = row.get(c)
            cells.append("—" if v is None or (isinstance(v, float) and v != v) else f"{v:.3f}")
        lines.append(f"| {q} | " + " | ".join(cells) + " |")
    out = OUT_DIR / f"ragas_report_{ts}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ 评测完成，报告已写入 {out}")


def _is_numeric_col(series) -> bool:
    """列是否为数值型（ragged 字符串列会混入 to_pandas，需排除）。"""
    import pandas as pd

    try:
        return pd.api.types.is_numeric_dtype(series)
    except Exception:  # noqa: BLE001
        return False


def _metric_meaning(col: str) -> str:
    return {
        "faithfulness": "回答忠于检索上下文的程度（幻觉越低越高）",
        "answer_relevancy": "回答与问题的相关性",
        "context_recall": "检索上下文对标准答案的覆盖度",
        "context_precision": "检索上下文中相关信息的精确度",
    }.get(col, "")


# ==========================================================
# 入口：判断是否运行在 .venv-eval 下
# ==========================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="RAGAS 评估（隔离环境）")
    parser.add_argument("--skip-install", action="store_true", help="跳过依赖安装（复用已有 .venv-eval）")
    args = parser.parse_args()

    # 已运行在 .venv-eval 下：直接评测
    if sys.executable and Path(sys.executable).resolve().parent == PYTHON.resolve().parent:
        run_eval()
        return

    # 首次：创建环境 + 安装依赖 + 用 .venv-eval 重新执行
    OUT_DIR.mkdir(exist_ok=True)
    ensure_venv()
    if not args.skip_install:
        try:
            install_deps()
        except subprocess.CalledProcessError as e:
            # 依赖装不上不阻塞：仍切到 .venv-eval 执行，内部 import 失败会走 hit@k 降级报告
            print(f"⚠️ 依赖安装失败（{e}），尝试继续——若 ragas 缺失将输出降级报告")
    print(f"[bootstrap] 切换至 .venv-eval 执行评测...")
    rc = subprocess.call([str(PYTHON), os.path.abspath(__file__), "--skip-install"])
    sys.exit(rc)


if __name__ == "__main__":
    main()
