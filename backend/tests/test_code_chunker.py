"""代码文件分块测试：按顶层定义切块、保留签名+docstring、超长再切、父子结构。"""
from dataclasses import is_dataclass

from app.services.chunker import (
    CODE_SEPARATORS,
    ChunkItem,
    _split_code,
    split_text,
    split_text_structured,
)

SAMPLE_PY = '''"""订单模块：演示代码文件入库。"""

import dataclasses

from datetime import datetime


class OrderService:
    """订单服务：负责订单全生命周期。"""

    def create_order(self, user_id: int, items: list[dict]) -> dict:
        """创建订单。

        Args:
            user_id: 下单用户 ID。
            items: 商品明细列表。

        Returns:
            订单字典。
        """
        return {"order_no": "ORD001", "status": "pending"}

    def pay_order(self, order_no: str) -> dict:
        """支付订单。"""
        return {"status": "paid"}


def create_user(username: str) -> dict:
    """创建用户。"""
    return {"username": username}
'''


def test_split_code_blocks_start_at_top_level():
    """每个代码块以顶层定义 / 文件头开始（不被内层缩进误切）。"""
    blocks = _split_code(SAMPLE_PY, "python")
    assert len(blocks) == 3  # 文件头 + class OrderService + create_user
    assert blocks[0].startswith('"""订单模块')  # 文件头独立成块，import/docstring 不丢
    assert "class OrderService" in blocks[1]
    assert blocks[2].lstrip().startswith("def create_user")


def test_split_code_preserves_signature_and_docstring():
    """块内保留签名行 + docstring（检索到即可定位函数名）。"""
    blocks = _split_code(SAMPLE_PY, "python")
    order_block = next(b for b in blocks if b.startswith("class OrderService"))
    assert "def create_order(self, user_id: int, items: list[dict]) -> dict:" in order_block
    assert "创建订单" in order_block
    assert "def pay_order" in order_block


def test_split_code_class_contains_methods():
    """class 块完整包含其方法（父块语义完整）。"""
    blocks = _split_code(SAMPLE_PY, "python")
    order_block = next(b for b in blocks if b.startswith("class OrderService"))
    assert "def create_order" in order_block
    assert "def pay_order" in order_block


def test_split_code_unknown_language_whole_text():
    """无匹配关键词的语言回退为整块，不误切。"""
    assert _split_code(SAMPLE_PY, "go") == [SAMPLE_PY.strip()]


def test_structured_code_parent_is_definition_block():
    """父子结构：child 属于 parent，parent 为完整定义块。"""
    items = split_text_structured(SAMPLE_PY, language="python")
    assert items and all(is_dataclass(i) for i in items)
    assert all(hasattr(i, "parent") and hasattr(i, "child") for i in items)
    assert all(i.child in i.parent for i in items)  # 子块是父块的子串


def test_structured_overlong_child_recut():
    """超长定义块再按代码分隔符切，但每片仍属于同一父块。"""
    long_fn = "def long_function():\n    return " + "x + " * 600 + "x\n"
    items = split_text_structured(
        "# header\n\n" + long_fn, chunk_size=300, chunk_overlap=30, language="python"
    )
    long_items = [i for i in items if "long_function" in i.parent]
    assert len(long_items) > 1  # 被切成多片
    for i in long_items:
        assert "long_function" in i.parent  # 每片父块都是同一函数
        assert i.child in i.parent


def test_split_text_flat_keeps_children():
    """扁平分块（旧接口）返回子块列表，不破坏既有调用方。"""
    children = split_text(SAMPLE_PY, language="python")
    assert isinstance(children, list) and all(isinstance(c, str) for c in children)
    assert all(any(c in b for b in split_text(SAMPLE_PY, language="python")) for c in children)


def test_code_separators_exist():
    """代码分隔符避免把语句拦腰截断。"""
    assert "\n\n" in CODE_SEPARATORS and "\n" in CODE_SEPARATORS


def test_split_text_returns_list_of_str():
    """返回类型兼容：list[str]。"""
    assert isinstance(split_text(SAMPLE_PY), list)
