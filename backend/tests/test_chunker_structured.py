"""父子分块（small-to-big）测试：标题分节=父块、子块⊆父块、无标题退化、超长再切。"""
from app.services.chunker import ChunkItem, split_text, split_text_structured

MD_DOC = """# 商品 X1 Pro

## 核心参数

星辰 X1 Pro 搭载 5000mAh 电池，支持 100W 有线快充与 50W 无线快充。

屏幕为 6.8 英寸 2K 分辨率，刷新率 120Hz。

## 价格信息

8+256G 版本售价 3999 元，12+512G 版本售价 4999 元。

## 售后政策

支持 7 天无理由退货，15 天换货，1 年保修。
"""


def test_structured_by_heading():
    """按标题分节，每节的 child 都挂在同一父块（标题分节全文）。"""
    items = split_text_structured(MD_DOC)
    assert items, "应至少产生一个分块"
    assert all(isinstance(i, ChunkItem) for i in items)
    for i in items:
        assert i.child in i.parent, "子块必须是父块的子串"
        assert i.parent.strip().startswith("#"), "父块以标题开头"


def test_short_section_parent_equals_child():
    """未超长分节 parent == child（父子同块），内容完整。"""
    items = split_text_structured(MD_DOC, chunk_size=2000)
    for i in items:
        assert i.parent == i.child


def test_parent_contains_child_content():
    """父块完整包含子块内容（LLM 上下文不缺上下文）。"""
    items = split_text_structured(MD_DOC)
    # 找 100W 快充相关的子块，父块应含完整价格上下文
    charging = next(i for i in items if "100W" in i.child)
    assert "5000mAh" in charging.parent


def test_no_heading_degrades_to_flat():
    """无标题纯文本退化为单父块递归切分。"""
    plain = "这是一段没有任何标题的普通文本。" * 300
    items = split_text_structured(plain, chunk_size=300, chunk_overlap=30)
    assert items
    # 所有子块属于同一父块（整体），父块是全文
    assert all(i.parent == plain for i in items)


def test_overlong_section_children_share_parent():
    """超长分节被切成多片，所有片共享同一父块。"""
    long_doc = "# 大章节\n\n" + "参数说明：某商品规格。" * 500
    items = split_text_structured(long_doc, chunk_size=200, chunk_overlap=20)
    big_items = [i for i in items if i.parent.startswith("# 大章节")]
    assert len(big_items) > 1
    assert len({i.parent for i in big_items}) == 1  # 同一父块


def test_split_text_returns_children_flat():
    """扁平分块 = 所有 child 的列表（兼容既有调用方）。"""
    flat = split_text(MD_DOC)
    structured = split_text_structured(MD_DOC)
    assert flat == [i.child for i in structured]
