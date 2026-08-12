"""文本分块服务（标题感知 + 中文递归分块 + 代码语言感知分块 + 父子分块）。

两级分块策略（企业级 RAG 召回质量的关键）：
1. 先按 Markdown 标题（# ~ ####）或代码顶层定义（class/def/func…）把长文档切成分节
   —— 保证每个知识单元（如"某一商品的参数表"或"某个函数/类的接口规范"）是语义完整的整体；
2. 对超长分节再用 LangChain 递归字符分块器按中文标点 / 代码换行层级切小，
   兼顾块内语义完整性与向量检索的细粒度。

父子分块（small-to-big）：`split_text_structured` 返回 `ChunkItem{parent, child}`，
子块参与向量检索（细粒度、定位准），父块全文作为 LLM 上下文（语义完整、不丢上下文）。
普通文档的父块=标题分节，代码文档的父块=顶层定义块。

非 Markdown / 非代码文档（txt/pdf/docx）无标题结构，自动退化为纯递归分块。
"""
from dataclasses import dataclass
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings

# 标题行：^ 顶格 + 1~4 个 # + 空格 + 标题文字
HEADING_RE = re.compile(r"^(#{1,4})\s+\S.*$", re.MULTILINE)
# 过短分节（不含标题 < 该字数）合并进上一节，避免碎片化
MERGE_THRESHOLD = 120

# 中文优化的递归分隔符：先按段落，再按句号/叹号/问号/分号/逗号层级切
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", "、", " ", ""]
# 代码递归分隔符：按空行/换行/分号切，避免把代码行拦腰截断
CODE_SEPARATORS = ["\n\n", "\n", ";", " ", ""]

# 各语言顶层定义正则（^ 顶格匹配，避免误切缩进的方法/内层函数）
_TOPLEVEL_RE = {
    "python": re.compile(r"^(?:class\s|def\s|async\s+def\s)", re.MULTILINE),
    "javascript": re.compile(
        r"^(?:class\s|function\s|async\s+function\s|export\s(?:default\s+)?(?:class|function))",
        re.MULTILINE,
    ),
    "typescript": re.compile(
        r"^(?:class\s|function\s|async\s+function\s|interface\s|type\s|enum\s|export\s)",
        re.MULTILINE,
    ),
    "java": re.compile(r"^(?:class\s|interface\s|enum\s|@\w)", re.MULTILINE),
    "go": re.compile(r"^(?:func\s|type\s|var\s|const\s)", re.MULTILINE),
    "cpp": re.compile(
        r"^(?:class\s|struct\s|enum\s|namespace\s|using\s|[A-Za-z_][\w:<>,\s]*\s+\w+\s*\()",
        re.MULTILINE,
    ),
    "c": re.compile(
        r"^(?:struct\s|enum\s|union\s|typedef\s|[A-Za-z_][\w:<>,\s]*\s+\w+\s*\()",
        re.MULTILINE,
    ),
    "csharp": re.compile(r"^(?:class\s|struct\s|interface\s|enum\s|namespace\s)", re.MULTILINE),
    "rust": re.compile(r"^(?:fn\s|struct\s|enum\s|impl\s|trait\s|mod\s)", re.MULTILINE),
    "ruby": re.compile(r"^(?:class\s|module\s|def\s)", re.MULTILINE),
    "php": re.compile(r"^(?:class\s|function\s|interface\s|trait\s)", re.MULTILINE),
    "swift": re.compile(r"^\s*(?:class|struct|enum|protocol|extension|func)\s", re.MULTILINE),
    "kotlin": re.compile(r"^\s*(?:class|interface|object|fun\s|data\s+class)", re.MULTILINE),
}


@dataclass
class ChunkItem:
    """父子分块单元：parent=父块全文（供 LLM 上下文），child=被检索/被引用的子块。"""

    parent: str
    child: str


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


def _recursive_split(
    section: str,
    chunk_size: int,
    chunk_overlap: int,
    separators: list[str] | None = None,
) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators or SEPARATORS,
        length_function=len,
    )
    return [c for c in splitter.split_text(section) if c.strip()]


def _split_code(text: str, language: str) -> list[str]:
    """按语言顶层定义切块：每个顶层 class/def/function 为一个语义块。

    - 块首自然保留「签名行 + docstring / 注释」，检索到即可定位到函数名；
    - 文件头（模块 docstring / import 段）作为独立块，避免丢失；
    - 未知语言或无顶层定义时回退为整块返回。
    """
    pattern = _TOPLEVEL_RE.get(language)
    if pattern is None:
        return [text.strip()]
    matches = list(pattern.finditer(text))
    if not matches:
        return [text.strip()]

    # 切分边界：文件头 + 各顶层定义起始点
    bounds = [0] + [m.start() for m in matches] + [len(text)]
    blocks: list[str] = []
    for i in range(len(bounds) - 1):
        seg = text[bounds[i] : bounds[i + 1]].strip()
        if seg:
            blocks.append(seg)
    return blocks or [text.strip()]


def split_text_structured(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    language: str | None = None,
) -> list[ChunkItem]:
    """结构化分块，返回父子单元列表。

    - 代码文档（language 命中）：父块=顶层定义块，子块=超长定义再切；
    - 普通文档：父块=标题分节（或整段），子块=超长分节的递归切片；
    - 未超长时 parent == child（父子同块）。
    """
    chunk_size = chunk_size or settings.CHUNK_SIZE
    chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP

    items: list[ChunkItem] = []
    if language is not None and language in _TOPLEVEL_RE:
        for block in _split_code(text, language):
            if len(block) <= chunk_size:
                items.append(ChunkItem(parent=block, child=block))
            else:
                for child in _recursive_split(
                    block, chunk_size, chunk_overlap, separators=CODE_SEPARATORS
                ):
                    items.append(ChunkItem(parent=block, child=child))
        return items

    sections = _split_by_heading(text)
    sections = _merge_tiny(sections)
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= chunk_size:
            items.append(ChunkItem(parent=section, child=section))
        else:
            for child in _recursive_split(section, chunk_size, chunk_overlap):
                items.append(ChunkItem(parent=section, child=child))
    return items


def split_text(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    language: str | None = None,
) -> list[str]:
    """扁平分块（兼容旧接口）：返回子块文本列表。"""
    return [i.child for i in split_text_structured(text, chunk_size, chunk_overlap, language)]
