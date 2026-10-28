"""Bounded DOCX body extraction using python-docx."""

import io
from pathlib import PurePosixPath
import re
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from docx import Document
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

MAX_DOCX_BYTES = 10 * 1024 * 1024
MAX_DOCX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_DOCX_DECOMPRESSED_BYTES = 24 * 1024 * 1024
MAX_DOCX_ENTRIES = 2000
MAX_DOCX_COMPRESSION_RATIO = 1000
MAX_DOCX_BODY_ELEMENTS = 100_000
MAX_DOCX_EXTRACTED_CHARS = 2_000_000
MAX_DOCX_TABLE_DEPTH = 16


def _preflight(content: bytes) -> None:
    if len(content) > MAX_DOCX_BYTES:
        raise ValueError('DOCX 文件超过 10 MiB 限制。')
    with ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_DOCX_ENTRIES:
            raise ValueError('DOCX ZIP 成员数量超过 2000 个限制。')
        seen = set()
        total = 0
        for entry in entries:
            name = entry.filename
            if ('\\' in name or '\0' in entry.orig_filename or PurePosixPath(name).is_absolute()
                    or ':' in name or any(part in {'.', '..'} for part in name.split('/'))):
                raise ValueError('DOCX 包含不安全的 ZIP 成员路径。')
            if name.casefold() in seen:
                raise ValueError('DOCX 包含重复 ZIP 成员名称。')
            seen.add(name.casefold())
            if entry.flag_bits & 1:
                raise ValueError('暂不支持加密 DOCX，请先解密。')
            if entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
                raise ValueError('DOCX 使用了不支持的 ZIP 压缩方式。')
            if entry.file_size > MAX_DOCX_MEMBER_BYTES:
                raise ValueError('DOCX 单个 ZIP 成员解压超过 8 MiB 限制。')
            total += entry.file_size
            if total > MAX_DOCX_DECOMPRESSED_BYTES:
                raise ValueError('DOCX ZIP 成员累计解压超过 24 MiB 限制。')
            if entry.file_size > 1024 * 1024 and entry.file_size > max(entry.compress_size, 1) * MAX_DOCX_COMPRESSION_RATIO:
                raise ValueError('DOCX ZIP 成员压缩比异常，超过 1000:1 限制。')
            if PurePosixPath(name).name.casefold().startswith('vbaproject'):
                raise ValueError('暂不支持包含宏的 Word 文件。')
        if 'word/document.xml' not in {entry.filename for entry in entries}:
            raise ValueError('DOCX 缺少正文 word/document.xml。')
        actual_total = 0
        for entry in entries:
            with archive.open(entry) as member:
                payload = member.read(MAX_DOCX_MEMBER_BYTES + 1)
            actual_total += len(payload)
            if len(payload) > MAX_DOCX_MEMBER_BYTES or actual_total > MAX_DOCX_DECOMPRESSED_BYTES:
                raise ValueError('DOCX 实际解压内容超过处理限制。')
            if len(payload) != entry.file_size:
                raise ValueError('DOCX ZIP 成员长度与记录不一致。')
            if entry.filename.casefold().endswith(('.xml', '.rels')):
                # Also catches UTF-16/32 declarations; no custom XML extraction.
                if re.search(rb'<!\s*(?:DOCTYPE|ENTITY)\b', payload.replace(b'\0', b''), re.IGNORECASE):
                    raise ValueError('DOCX 不允许 DTD 或外部实体声明。')
            if entry.filename == '[Content_Types].xml' and b'macroenabled' in payload.lower():
                raise ValueError('暂不支持包含宏的 Word 文件。')


class _TextBudget:
    def __init__(self):
        self.used = 0

    def take(self, size: int) -> None:
        if self.used + size > MAX_DOCX_EXTRACTED_CHARS:
            raise ValueError('DOCX 正文文字及分隔符超过 200 万字符限制。')
        self.used += size


def _row_text(row, budget: _TextBudget, depth: int = 1) -> str:
    if depth > MAX_DOCX_TABLE_DEPTH:
        raise ValueError('DOCX 表格嵌套深度超过 16 层限制。')
    values = []
    # python-docx row.cells repeats a cell gridSpan times and follows vMerge.
    # Use its physical tc elements and maintained cell wrapper exactly once.
    for tc in row._tr.tc_lst:
        cell = _Cell(tc, row.table)
        parts = []
        for block in cell.iter_inner_content():
            if isinstance(block, Paragraph):
                text = block.text.strip()
                budget.take(len(text))
                if text:
                    parts.append(text)
            elif isinstance(block, Table):
                # Nested tables remain in their containing cell and outer row.
                for child in block.rows:
                    text = _row_text(child, budget, depth + 1)
                    if text:
                        parts.append(text)
        budget.take(max(len(parts) - 1, 0))
        values.append('\n'.join(parts))
    budget.take(max(len(values) - 1, 0))
    return '\t'.join(values).strip()


def extract_docx_sections(content: bytes) -> list[tuple[str, str]]:
    try:
        _preflight(content)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('DOCX 压缩文件损坏或不是受支持的 DOCX 格式。') from exc
    try:
        # python-docx 1.2 uses resolve_entities=False in both XML parsers;
        # lxml defaults no_network=True and load_dtd=False. External OPC
        # relationships are skipped by its package reader, not fetched.
        document = Document(io.BytesIO(content))
        for count, _ in enumerate(document.element.body.iter(), 1):
            if count > MAX_DOCX_BODY_ELEMENTS:
                raise ValueError('DOCX 正文结构超过 100000 个 XML 节点限制。')
        budget = _TextBudget()
        sections = []
        paragraph_number = table_number = 0
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                paragraph_number += 1
                text = block.text.strip()
                budget.take(len(text))
                if text:
                    sections.append((f'第 {paragraph_number} 段', text))
            elif isinstance(block, Table):
                table_number += 1
                for row_number, row in enumerate(block.rows, 1):
                    text = _row_text(row, budget)
                    if text:
                        sections.append((f'表 {table_number} · 第 {row_number} 行', text))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('DOCX 正文解析失败，文件可能已损坏或格式不受支持。') from exc
    if not sections:
        raise ValueError('DOCX 未提取到正文文字；空文档或仅含图片暂不支持，可先进行 OCR。')
    return sections
