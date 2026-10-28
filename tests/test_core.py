import io
import sqlite3

import pytest
from pypdf import PdfWriter

from app.ingestion import IngestionError, parse_document, split_text
from app.service import KnowledgeService


@pytest.fixture
def service(tmp_path):
    return KnowledgeService(tmp_path / 'knowledge.sqlite3')


def test_import_encoding_deduplication_and_persistence(service):
    content = '远程办公申请需提前两个工作日提交。'.encode('gb18030')
    doc = service.import_document('办公规则.txt', content)
    again = service.import_document('同一文件.txt', content)
    assert not doc['existing'] and again['existing']
    assert doc['id'] == again['id']
    assert doc['kind'] == 'txt' and doc['byte_size'] == len(content)
    assert len(service.documents()) == 1
    assert service.document(doc['id'])['chunks'][0]['text'] == content.decode('gb18030')
    assert len(KnowledgeService(service.db_path).documents()) == 1


@pytest.mark.parametrize('name,content', [('x.exe', b'hello'), ('empty.txt', b'  \n'), ('bad.txt', b'\x00\x01\x02'), ('big.md', b'a' * (10 * 1024 * 1024 + 1)), ('x.pdf', b'not pdf')], ids=['unsupported', 'empty', 'binary', 'oversized', 'malformed-pdf'])
def test_rejects_invalid_documents(service, name, content):
    with pytest.raises(IngestionError):
        service.import_document(name, content)
    assert service.documents() == []


def test_scanned_pdf_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    data = io.BytesIO()
    writer.write(data)
    with pytest.raises(IngestionError, match='扫描|文字'):
        parse_document('scan.pdf', data.getvalue())


def _text_pdf():
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    for text in ['First page travel policy.', 'Second page annual leave.']:
        page = writer.add_blank_page(width=400, height=400)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 20 350 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    data = io.BytesIO()
    writer.write(data)
    return data.getvalue()


def test_pdf_preserves_page_locations(service):
    doc = service.import_document('manual.pdf', _text_pdf())
    chunks = service.document(doc['id'])['chunks']
    assert [c['location'] for c in chunks] == ['第 1 页', '第 2 页']
    assert 'Second page' in chunks[1]['text']


def test_long_paragraph_splitting_terminates_and_covers_text():
    text = '甲乙丙丁' * 1000
    parts = split_text(text, chunk_size=120, overlap=30)
    assert 1 < len(parts) < 60
    assert all(0 < len(p) <= 120 for p in parts)
    assert parts[0] == text[:120] and parts[-1].endswith(text[-30:])
    with pytest.raises(ValueError):
        split_text(text, chunk_size=100, overlap=100)


@pytest.mark.parametrize('strategy', ['hybrid', 'bm25', 'tfidf'])
def test_search_numeric_question_and_verbatim_citations(service, strategy):
    doc = service.import_document('差旅规则.md', '出差住宿标准：上海每晚报销上限为 600 元。\n\n火车票只报销二等座。'.encode())
    result = service.ask('上海出差住宿报销上限是多少？', strategy=strategy)
    assert result['status'] == 'answered'
    assert result['mode'] == 'extractive' and result['usage'] is None
    assert '[1]' in result['answer']
    assert result['sources'][0]['document_id'] == doc['id']
    assert result['sources'][0]['text'] in result['answer']
    assert result['sources'][0]['id'] not in result['answer']
    assert result['metrics']['generation_ms'] == 0
    assert result['metrics']['total_ms'] >= result['metrics']['retrieval_ms'] >= 0
    assert result['trace'] and result['warning']


def test_filter_delete_cascade_and_rebuild(service):
    a = service.import_document('a.txt', '采购审批金额上限是 500 元。'.encode())
    b = service.import_document('b.txt', '采购审批金额上限是 900 元。'.encode())
    assert {s['document_id'] for s in service.search('采购审批金额上限', document_ids=[a['id']])} == {a['id']}
    assert service.search('采购审批金额上限', document_ids=['nonexistent']) == []
    assert service.delete_document(a['id']) is True
    assert service.delete_document(a['id']) is False
    assert all(s['document_id'] == b['id'] for s in service.search('采购审批金额上限'))
    with sqlite3.connect(service.db_path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM chunks WHERE document_id=?', (a['id'],)).fetchone()[0] == 0
    with pytest.raises(KeyError):
        service.document(a['id'])


@pytest.mark.parametrize('question', ['', '   ', '火星的天气预报', '公司有没有提供宠物保险？'])
def test_insufficient_evidence_refuses(service, question):
    service.import_document('rules.txt', '公司员工差旅报销需要提交正规发票。'.encode())
    result = service.ask(question)
    assert result['status'] == 'insufficient'
    assert result['sources'] == []
    assert service.search(question) == []


def test_conflicting_rules_are_exposed(service):
    service.import_document('规则一.txt', '上海住宿报销上限为 500 元。'.encode())
    service.import_document('规则二.txt', '上海住宿报销上限为 800 元。'.encode())
    result = service.ask('上海住宿报销上限是多少？')
    assert result['status'] == 'conflict'
    assert len(result['sources']) == 2
    assert '[1]' in result['answer'] and '[2]' in result['answer']


def test_queries_are_parameterized_and_ranking_stable(service):
    service.import_document("weird';DROP TABLE documents;--.txt", b'Annual leave requires manager approval.')
    result = service.search('annual leave manager approval')
    assert result == service.search('annual leave manager approval')
    assert service.search("'; DROP TABLE chunks;--") == []
    assert len(service.documents()) == 1
    assert service.search('annual leave', document_ids=[]) == service.search('annual leave')


def test_invalid_search_options(service):
    with pytest.raises(ValueError):
        service.search('question', strategy='unsupported')
    with pytest.raises(ValueError):
        service.search('question', top_k=0)


def test_pdf_limits_do_not_modify_caller_configuration():
    from pypdf import apply_configuration, get_configuration
    with apply_configuration(zlib_maximum_output_length=75_000_000):
        parse_document('text.pdf', _text_pdf())
        assert get_configuration().zlib_maximum_output_length == 75_000_000


def test_different_rule_topics_are_not_reported_as_conflict(service):
    service.import_document('limits.txt', '上海住宿报销上限为 500 元。\n\n北京住宿报销上限为 800 元。'.encode())
    assert service.ask('住宿报销上限是多少？')['status'] == 'answered'


def test_parallel_import_query_and_delete(service):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as executor:
        docs = list(executor.map(lambda _: service.import_document('rules.txt', '远程办公每周最多两天。'.encode()), range(8)))
        answers = list(executor.map(lambda _: service.ask('远程办公每周最多几天？'), range(8)))
    assert len(service.documents()) == 1
    assert len({d['id'] for d in docs}) == 1
    assert all(a['status'] == 'answered' for a in answers)
    assert service.delete_document(docs[0]['id'])
    assert service.ask('远程办公每周最多几天？')['status'] == 'insufficient'


def test_product_identifiers_are_not_numeric_rule_conflicts(service):
    service.import_document('products.txt', 'SN100 的默认采样间隔为 60 秒。\n\nSN200 的默认采样间隔为 10 秒。'.encode())
    assert service.ask('默认采样间隔是多少？')['status'] == 'answered'


def test_markdown_heading_stays_with_its_evidence(service):
    document = service.import_document('rules.md', '# 工作规则\n\n## 办公网络\n\n访问内部系统必须使用公司 VPN。\n\n## 每日同步\n\n当日 17:30 前更新进展。'.encode())
    chunks = service.document(document['id'])['chunks']
    assert any('办公网络\n\n访问内部系统' in c['text'] for c in chunks)
    assert all(not c['text'].startswith('## ') or '\n\n' in c['text'] for c in chunks)


def test_pdf_page_count_is_bounded():
    writer = PdfWriter()
    for _ in range(201):
        writer.add_blank_page(width=100, height=100)
    data = io.BytesIO()
    writer.write(data)
    with pytest.raises(IngestionError, match='200'):
        parse_document('many.pdf', data.getvalue())


def test_pdf_compressed_stream_is_bounded_before_extraction():
    from pypdf.generic import NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    stream = DecodedStreamObject()
    stream.set_data(b' ' * (9 * 1024 * 1024))
    page[NameObject('/Contents')] = writer._add_object(stream.flate_encode())
    data = io.BytesIO()
    writer.write(data)
    assert len(data.getvalue()) < 10 * 1024 * 1024
    with pytest.raises(IngestionError):
        parse_document('compressed.pdf', data.getvalue())


def _padded_text_pdf(page_count, stream_count=1):
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    font_reference = writer._add_object(font)
    for _ in range(page_count):
        page = writer.add_blank_page(width=400, height=400)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_reference})})
        stream = DecodedStreamObject()
        stream.set_data(b' ' * (2 * 1024 * 1024) + b'BT /F1 12 Tf 20 350 Td (Budget text.) Tj ET')
        reference = writer._add_object(stream.flate_encode())
        page[NameObject('/Contents')] = reference if stream_count == 1 else ArrayObject([reference] * stream_count)
    data = io.BytesIO()
    writer.write(data)
    return data.getvalue()


def test_pdf_cumulative_decompressed_content_is_bounded_before_extraction(service, monkeypatch):
    from pypdf._page import PageObject
    extracted_pages = []
    extract_text = PageObject.extract_text

    def track_extraction(page, *args, **kwargs):
        extracted_pages.append(page)
        return extract_text(page, *args, **kwargs)

    monkeypatch.setattr(PageObject, 'extract_text', track_extraction)
    content = _padded_text_pdf(12)
    assert len(content) < 50 * 1024
    with pytest.raises(IngestionError, match='累计'):
        service.import_document('cumulative.pdf', content)
    assert len(extracted_pages) == 11
    assert service.documents() == []


def test_pdf_below_cumulative_content_budget_preserves_text_and_pages():
    parsed = parse_document('padded.pdf', _padded_text_pdf(2))
    assert [c['location'] for c in parsed['chunks']] == ['第 1 页', '第 2 页']
    assert all(c['text'] == 'Budget text.' for c in parsed['chunks'])


def test_pdf_repeated_indirect_content_streams_share_page_limit():
    with pytest.raises(IngestionError):
        parse_document('array.pdf', _padded_text_pdf(1, stream_count=5))


def test_encrypted_pdf_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt('secret')
    data = io.BytesIO()
    writer.write(data)
    with pytest.raises(IngestionError, match='加密'):
        parse_document('encrypted.pdf', data.getvalue())


def test_explicit_missing_policy_is_refusal_with_auditable_source(service):
    service.import_document('travel.txt', '国内出差餐费补助为 80 元。未规定海外出差补贴。'.encode())
    result = service.ask('海外出差补贴是多少？')
    assert result['status'] == 'insufficient'
    assert result['sources'] and '未规定海外出差补贴' in result['sources'][0]['text']
    assert '[1]' in result['answer']
    assert service.search('海外出差补贴是多少？')


@pytest.mark.parametrize('text', ['设备防护等级为 IP54，售价未公布。', '设备防护等级为 IP54。但售价未公布。', '设备防护等级为 IP54 但售价未公布。'])
def test_missing_other_attribute_does_not_hide_provided_fact(service, text):
    service.import_document('specs.txt', text.encode())
    result = service.ask('设备防护等级是什么？')
    assert result['status'] == 'answered'
    assert 'IP54' in result['answer']
