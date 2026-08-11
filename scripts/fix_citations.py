"""修复历史消息中被 GBK 误编码的引用文档名（乱码）。

背景：早期有文档经 GBK 编码上传，python-multipart 按 latin-1 解码，
导致文件名存入数据库时变成乱码（如 ÉÌÆ·ÖªÊ¶¿â.md）。
虽然知识库文档本身已修复，但历史消息 citations 里存的还是乱码名。
本脚本扫描 messages 表，把乱码名还原为正确中文，并校正 doc_id。

用法：
    cd backend && .venv/Scripts/python.exe ../scripts/fix_citations.py
"""
import json
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DB = "dev.db"


def fix_mojibake(name: str) -> str:
    """把 latin-1 误读的 GBK 字节还原为中文；非乱码原样返回。"""
    if not name:
        return name
    try:
        decoded = name.encode("latin-1").decode("gbk")
    except Exception:
        return name
    # 还原后必须包含中文才算乱码（避免误伤正常的 latin-1 名字）
    if not any("一" <= ch <= "鿿" for ch in decoded):
        return name
    return decoded


def main() -> None:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # 当前文档 id -> filename 映射（用于校正 doc_id，以及生成正文乱码->正确串映射）
    docs = cur.execute("SELECT id, filename FROM documents").fetchall()
    doc_by_name = {fn: did for did, fn in docs}
    moji_map: dict[str, str] = {}
    for did, fn in docs:
        try:
            moji = fn.encode("gbk").decode("latin-1")  # 正确的名字经 GBK 上传会变成的乱码形态
        except Exception:
            continue
        if moji != fn:
            moji_map[moji] = fn

    rows = cur.execute(
        "SELECT id, content, citations FROM messages "
        "WHERE citations IS NOT NULL AND citations != ''"
    ).fetchall()

    changed_msgs = fixed_cites = fixed_doc_ids = changed_content = 0
    for mid, content, cits_json in rows:
        try:
            cites = json.loads(cits_json)
        except Exception:
            continue

        # 引用里的 doc_name 还原
        modified = False
        for c in cites:
            old_name = c.get("doc_name", "")
            new_name = fix_mojibake(old_name)
            if new_name != old_name:
                print(f"  消息#{mid}: 引用乱码 {old_name!r} -> {new_name!r}")
                c["doc_name"] = new_name
                fixed_cites += 1
                modified = True
                if new_name in doc_by_name and doc_by_name[new_name] != c.get("doc_id"):
                    print(f"          校正 doc_id {c.get('doc_id')} -> {doc_by_name[new_name]}")
                    c["doc_id"] = doc_by_name[new_name]
                    fixed_doc_ids += 1
        if modified:
            cur.execute(
                "UPDATE messages SET citations = ? WHERE id = ?",
                (json.dumps(cites, ensure_ascii=False), mid),
            )
            changed_msgs += 1

        # 回答正文里若混入乱码文件名，一并替换
        content = content or ""
        new_content = content
        for moji, correct in moji_map.items():
            if moji in new_content:
                new_content = new_content.replace(moji, correct)
                print(f"  消息#{mid}: 正文乱码 {moji!r} -> {correct!r}")
                changed_content += 1
        if new_content != content:
            cur.execute("UPDATE messages SET content = ? WHERE id = ?", (new_content, mid))

    conn.commit()
    print(
        f"\n修复完成：消息 {changed_msgs} 条，引用 {fixed_cites} 处，"
        f"校正 doc_id {fixed_doc_ids} 个，正文乱码 {changed_content} 处"
    )
    conn.close()


if __name__ == "__main__":
    main()
