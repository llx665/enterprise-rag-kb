"""文本分块服务（标题感知 + 中文递归分块）。

两级分块策略（企业级 RAG 召回质量的关键）：
1. 先按 Markdown 标题（# ~ ####）把长文档切成分节 —— 保证每个知识单元
   （如"某一商品的参数表"）是语义完整的整体，避免两个主题被硬拼进一块；
2. 对超长分节再用 LangChain 递归字符分块器按中文标点层级切小，
   兼顾块内语义完整性与向量检索的细粒度。

非 Markdown 文档（txt/pdf/docx）无标题结构，自动退化为纯递归分块。
"""
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings

# 标题行：^ 顶格 + 1~4 个 # + 空格 + 标题文字
HEADING_RE = re.compile(r"^(#{1,4})\s+\S.*$", re.MULTILINE)
# 过短分节（不含标题 < 该字数）合并进上一节，避免碎片化
MERGE_THRESHOLD = 120

# 中文优化的递归分隔符：先按段落，再按句号/叹号/问号/分号/逗号层级切
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", "、", " ", ""]


def _split_by_heading(text: str) -> list[str]:
    """按标题切出章节列表（含标题行），无标题则返回整段。"""
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [text]
    sections = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(text[m.start() : end])
    return sections


def _merge_tiny(sections: list[str]) -> list[str]:
    """把过短的章节合并进上一节，避免"一句话"碎片污染检索。"""
    merged: list[str] = []
    for sec in sections:
        body = re.sub(r"^#{1,4}\s+\S.*$", "", sec, flags=re.MULTILINE).strip()
        if merged and len(body) < MERGE_THRESHOLD:
            merged[-1] = merged[-1] + "\n" + sec
        else:
            merged.append(sec)
    return merged


def _recursive_split(section: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=SEPARATORS,
        length_function=len,
    )
    return [c for c in splitter.split_text(section) if c.strip()]


def split_text(text: str, chunk_size: int | None = None, chunk_overlap: int | None = None) -> list[str]:
    chunk_size = chunk_size or settings.CHUNK_SIZE
    chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP

    sections = _split_by_heading(text)
    sections = _merge_tiny(sections)

    chunks: list[str] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= chunk_size:
            chunks.append(section)
        else:
            chunks.extend(_recursive_split(section, chunk_size, chunk_overlap))
    return chunks
