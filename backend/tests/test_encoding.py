"""文件名乱码还原工具测试：GBK 字节被 latin-1 误读场景。"""
from app.utils.encoding import build_moji_map, fix_mojibake


def test_fix_mojibake_chinese():
    # '商品知识库.md' 经 GBK 上传被 latin-1 误读后的形态
    moji = "商品知识库.md".encode("gbk").decode("latin-1")
    assert moji != "商品知识库.md"  # 确实已乱码
    assert fix_mojibake(moji) == "商品知识库.md"


def test_fix_mojibake_normal_name_untouched():
    # 正常 ASCII 名字不应被误伤
    assert fix_mojibake("manual.pdf") == "manual.pdf"


def test_fix_mojibake_not_valid_gbk():
    # 无法按 GBK 解码的串原样返回
    assert fix_mojibake("abc") == "abc"
    assert fix_mojibake("") == ""


def test_build_moji_map_roundtrip():
    filenames = ["商品知识库.md", "产品手册.md", "README.md"]
    moji_map = build_moji_map(filenames)
    # 纯 ASCII 文件不进映射
    assert "README.md" not in moji_map
    # 中文文件可双向还原
    for fn in filenames:
        if "README" not in fn:
            moji = fn.encode("gbk").decode("latin-1")
            assert moji_map[moji] == fn
            assert fix_mojibake(moji) == fn
