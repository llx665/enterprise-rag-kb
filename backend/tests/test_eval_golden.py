"""RAGAS golden 数据校验：schema 合法 + expected_docs 对应 demo_data 真实文件。"""
import json
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
DEMO_DIR = SCRIPTS_DIR.parent / "demo_data"


def _golden() -> list[dict]:
    return json.loads(
        (SCRIPTS_DIR / "eval_golden.json").read_text(encoding="utf-8")
    )


def test_golden_is_nonempty_list():
    data = _golden()
    assert isinstance(data, list)
    assert len(data) >= 10, "golden 至少 10 条才有统计意义"


def test_each_entry_schema():
    for i, item in enumerate(_golden()):
        assert isinstance(item, dict), f"第 {i} 条应为对象"
        # question / ground_truth：非空字符串
        assert isinstance(item.get("question"), str) and item["question"].strip(), (
            f"第 {i} 条 question 缺失或为空"
        )
        assert isinstance(item.get("ground_truth"), str) and item["ground_truth"].strip(), (
            f"第 {i} 条 ground_truth 缺失或为空"
        )
        # expected_docs：非空字符串列表
        docs = item.get("expected_docs")
        assert isinstance(docs, list) and docs, f"第 {i} 条 expected_docs 应为非空列表"
        assert all(isinstance(d, str) and d for d in docs), (
            f"第 {i} 条 expected_docs 含非字符串项"
        )
        # ground_truth 是模型答案级参考答案：应明显长于一句
        assert len(item["ground_truth"]) >= 30, (
            f"第 {i} 条 ground_truth 过短，应为自然语言参考答案"
        )


def test_expected_docs_exist_in_demo_data():
    real_files = {p.name for p in DEMO_DIR.iterdir() if p.is_file()}
    assert real_files, "demo_data 目录为空？"
    for i, item in enumerate(_golden()):
        for doc in item["expected_docs"]:
            assert doc in real_files, (
                f"第 {i} 条 expected_docs={doc} 不在 demo_data：{sorted(real_files)}"
            )


def test_questions_unique():
    qs = [item["question"] for item in _golden()]
    assert len(qs) == len(set(qs)), "golden 问题重复，hit@k 会互相干扰"


def test_covers_multiple_docs():
    """覆盖面：至少 6 个不同来源文档有 golden。"""
    docs = {d for item in _golden() for d in item["expected_docs"]}
    assert len(docs) >= 6, f"golden 覆盖面过窄：{sorted(docs)}"
