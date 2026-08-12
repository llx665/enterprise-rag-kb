"""代码文件解析测试：白名单、语言映射、_parse_code 原文返回、上传白名单复用。"""
from pathlib import Path

import pytest

from app.services.document_parser import (
    CODE_EXTS,
    CODE_LANG,
    SUPPORTED_EXTS,
    _parse_code,
    parse_document,
)

SAMPLE_PY = '''"""订单模块：演示代码文件入库。"""


class OrderService:
    """订单服务。"""

    def create_order(self, user_id: int) -> dict:
        """创建订单。"""
        return {"order_no": "ORD001", "status": "pending"}
'''


def test_code_exts_in_whitelist():
    """常见代码扩展名都进上传白名单。"""
    for ext in ("py", "js", "ts", "java", "go", "cpp", "c", "cs", "rs", "php", "swift", "kt"):
        assert ext in SUPPORTED_EXTS
    # 基础文档类型仍在
    assert {"pdf", "docx", "xlsx", "txt", "md"} <= SUPPORTED_EXTS


def test_code_lang_mapping():
    """扩展名 -> 语言 key 映射完整，供分块器按顶层定义切块。"""
    assert CODE_LANG["py"] == "python"
    assert CODE_LANG["js"] == "javascript"
    assert CODE_LANG["ts"] == "typescript"
    assert CODE_LANG["java"] == "java"
    assert CODE_LANG["go"] == "go"
    # 每个代码扩展名都有语言映射（无映射的会退回普通分块，但不应缺失）
    for ext in CODE_EXTS:
        assert ext in CODE_LANG, f"{ext} 缺少 CODE_LANG 映射"


def test_parse_code_returns_original(tmp_path: Path):
    """_parse_code 原样返回源码（含中文 docstring 与注释）。"""
    p = tmp_path / "sample.py"
    p.write_text(SAMPLE_PY, encoding="utf-8")
    assert _parse_code(p) == SAMPLE_PY


def test_parse_document_code_ext(tmp_path: Path):
    """parse_document 对 .py 文件走代码解析，中文不乱码。"""
    p = tmp_path / "sample.py"
    p.write_text(SAMPLE_PY, encoding="utf-8")
    text = parse_document("sample.py", p)
    assert "class OrderService" in text
    assert "订单服务" in text


def test_parse_document_rejects_unknown(tmp_path: Path):
    """未知扩展名仍被拒绝。"""
    p = tmp_path / "evil.xyz"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_document("evil.xyz", p)


def test_upload_whitelist_reuses_supported_exts():
    """上传接口白名单与解析器共用 SUPPORTED_EXTS（kb.py:37 同一常量，无需 HTTP 即可验证）。"""
    from app.api.kb import SUPPORTED_EXTS as kb_supported  # noqa: F401

    assert kb_supported == SUPPORTED_EXTS
