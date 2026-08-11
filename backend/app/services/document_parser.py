"""文档解析服务：将上传文件提取为纯文本。

支持格式：PDF / Word(.docx) / Excel(.xlsx) / 纯文本 / Markdown。
"""
from pathlib import Path

from docx import Document as DocxDocument
from openpyxl import load_workbook
from pypdf import PdfReader

SUPPORTED_EXTS = {"pdf", "docx", "xlsx", "txt", "md"}


def parse_document(filename: str, path: Path) -> str:
    """按扩展名分发到对应解析器，返回提取后的纯文本。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"不支持的文件类型: .{ext}")
    if ext == "pdf":
        return _parse_pdf(path)
    if ext == "docx":
        return _parse_docx(path)
    if ext == "xlsx":
        return _parse_xlsx(path)
    # txt / md 直接读取（尝试多种编码，保证中文不乱码）
    return _parse_text(path)


def _parse_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)
    return "\n\n".join(pages)


def _parse_docx(path: Path) -> str:
    doc = DocxDocument(str(path))
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    # 表格内容
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _parse_xlsx(path: Path) -> str:
    wb = load_workbook(str(path), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"## 工作表: {ws.title}")
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                rows.append(" | ".join(cells))
        parts.append("\n".join(rows))
    wb.close()
    return "\n\n".join(parts)


def _parse_text(path: Path) -> str:
    # 依次尝试 UTF-8 / GBK / latin-1，避免中文编码问题
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="latin-1", errors="ignore")
