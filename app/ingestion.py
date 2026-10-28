"""Bounded text extraction with source locations preserved."""

import io
import re
from pathlib import PurePosixPath

from pypdf import PdfReader, apply_configuration
from pypdf.generic import DictionaryObject
from .docx_ingestion import extract_docx_sections

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_PDF_DECOMPRESSED_BYTES = 24 * 1024 * 1024
MAX_PDF_FORM_DEPTH = 16
MAX_EXTRACTED_CHARS = 2_000_000


class IngestionError(ValueError):
    """The uploaded file cannot be accepted as a text document."""


class _PdfContentBudget:
    """Bound decoded text streams, not process memory or extraction time."""

    def __init__(self):
        self.total = 0
        self.forms = {}
        self.active = set()

    def add(self, stream):
        size = len(stream.get_data()) if stream is not None else 0
        if size > 8 * 1024 * 1024:
            raise IngestionError('PDF 单个内容流解压超过 8 MiB 限制。')
        self.total += size
        if self.total > MAX_PDF_DECOMPRESSED_BYTES:
            raise IngestionError('PDF 内容流累计解压超过 24 MiB 限制。')

    def check_forms(self, resources, depth=1):
        resources = resources.get_object()
        xobjects = resources.get('/XObject', DictionaryObject()).get_object()
        height = 0
        for reference in xobjects.values():
            form = reference.get_object()
            if form.get('/Subtype') == '/Image':
                continue
            if form.get('/Subtype') != '/Form':
                raise IngestionError('PDF 包含不支持的非图像 XObject 内容流。')
            indirect = getattr(form, 'indirect_reference', None)
            key = (id(indirect.pdf), indirect.idnum, indirect.generation) if indirect else id(form)
            if key in self.active:
                raise IngestionError('PDF Form 内容流存在循环引用。')
            cached_height = self.forms.get(key)
            if depth + (cached_height or 1) - 1 > MAX_PDF_FORM_DEPTH:
                raise IngestionError('PDF Form 内容流嵌套深度超过 16 层限制。')
            if cached_height is not None:
                height = max(height, cached_height)
                continue
            self.active.add(key)
            self.add(form)
            child_height = self.check_forms(form.get('/Resources', DictionaryObject()), depth + 1)
            self.active.remove(key)
            self.forms[key] = child_height + 1
            height = max(height, child_height + 1)
        return height


def split_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError('分块长度须为正数，重叠须小于分块长度。')
    result = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        part = text[start:end].strip()
        if part:
            result.append(part)
        if end == len(text):
            break
        start = end - overlap
    return result


def parse_document(filename: str, content: bytes) -> dict:
    filename = PurePosixPath(filename.replace('\\', '/')).name
    kind = PurePosixPath(filename).suffix.lower().lstrip('.')
    if kind not in {'txt', 'md', 'pdf', 'docx'}:
        raise IngestionError('仅支持 TXT、Markdown、DOCX 和可提取文字的 PDF。')
    if len(content) > MAX_FILE_BYTES:
        raise IngestionError('文件超过 10 MB 限制。')
    if not content:
        raise IngestionError('文件为空。')
    sections = []
    if kind == 'docx':
        try:
            sections = extract_docx_sections(content)
        except ValueError as error:
            raise IngestionError(str(error)) from None
        if sum(len(text) for _, text in sections) > MAX_EXTRACTED_CHARS:
            raise IngestionError('DOCX 提取文字超过处理上限。')
        if not sections:
            raise IngestionError('DOCX 未提取到可用文字。')
    elif kind == 'pdf':
        try:
            with apply_configuration(zlib_maximum_output_length=8 * 1024 * 1024,
                                     lzw_maximum_output_length=8 * 1024 * 1024,
                                     run_length_maximum_output_length=8 * 1024 * 1024,
                                     array_based_stream_maximum_output_length=8 * 1024 * 1024):
                reader = PdfReader(io.BytesIO(content))
                if reader.is_encrypted:
                    raise IngestionError('暂不支持加密 PDF，请先解密。')
                if len(reader.pages) > MAX_PDF_PAGES:
                    raise IngestionError('PDF 超过 200 页限制。')
                extracted = 0
                budget = _PdfContentBudget()
                for index, page in enumerate(reader.pages, 1):
                    stream = page.get_contents()
                    budget.add(stream)
                    budget.check_forms(page.get('/Resources', DictionaryObject()))
                    text = (page.extract_text() or '').strip()
                    extracted += len(text)
                    if extracted > MAX_EXTRACTED_CHARS:
                        raise IngestionError('PDF 提取文字超过处理上限。')
                    if text:
                        sections.append((f'第 {index} 页', text))
        except IngestionError:
            raise
        except Exception as exc:
            raise IngestionError('PDF 无法解析，可能已损坏或超出解压限制。') from exc
        if not sections:
            raise IngestionError('PDF 未提取到文字，扫描件暂不支持，请先 OCR。')
    else:
        text = None
        for encoding in ('utf-8-sig', 'gb18030'):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', text):
            raise IngestionError('文件不是可识别的 UTF-8 或 GB18030 文本。')
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        if len(text) > MAX_EXTRACTED_CHARS:
            raise IngestionError('文字超过处理上限。')
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        pending = []
        first_heading = 0
        for i, paragraph in enumerate(paragraphs, 1):
            if kind == 'md' and all(re.match(r'^#{1,6}\s', line) for line in paragraph.splitlines()):
                if not pending:
                    first_heading = i
                pending.append(paragraph)
                continue
            location = first_heading if pending else i
            sections.append((f'第 {location} 段', '\n\n'.join([*pending, paragraph])))
            pending = []
        if pending:
            sections.append((f'第 {first_heading} 段', '\n\n'.join(pending)))
        if not sections:
            raise IngestionError('文件没有可用文字。')
    chunks = [{'location': location, 'text': part} for location, text in sections for part in split_text(text)]
    return {'filename': filename, 'kind': kind, 'chunks': chunks}
