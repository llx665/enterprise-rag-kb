"""文件名编码还原工具。

背景：python-multipart 按 latin-1 解码上传文件名。当文件名原是 GBK 字节
（中文 Windows 上传），会被误存为乱码（如 ÉÌÆ·ÖªÊ¶¿â.md -> 商品知识库.md）。
本模块提供可复用的还原函数，供历史数据修复脚本与单元测试共用。
"""


def fix_mojibake(name: str) -> str:
    """把 latin-1 误读的 GBK 字节还原为中文；非乱码原样返回。"""
    if not name:
        return name
    try:
        decoded = name.encode("latin-1").decode("gbk")
    except Exception:
        return name
    # 还原后必须包含中文才算乱码，避免误伤正常的 latin-1 名字
    if not any("一" <= ch <= "鿿" for ch in decoded):
        return name
    return decoded


def build_moji_map(filenames: list[str]) -> dict[str, str]:
    """构建「乱码形态 -> 正确文件名」映射。

    用于把回答正文里混入的乱码文件名还原为正确名称：
    例如 'ÉÌÆ·ÖªÊ¶¿â.md' -> '商品知识库.md'。与 fix_mojibake 互为逆运算。
    """
    moji_map: dict[str, str] = {}
    for fn in filenames:
        try:
            moji = fn.encode("gbk").decode("latin-1")
        except Exception:
            continue
        if moji != fn:
            moji_map[moji] = fn
    return moji_map
