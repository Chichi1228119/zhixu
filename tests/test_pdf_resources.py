import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject, DictionaryObject, NameObject, RectangleObject,
)

from app.ingestion import IngestionError, parse_document


def pdf_with_forms(*, count=1, padding=0, depth=1, cycle=False, shared=False, image=False):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    }))

    def form(text):
        stream = DecodedStreamObject()
        stream.set_data(text)
        stream.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                       NameObject('/BBox'): RectangleObject([0, 0, 100, 100]),
                       NameObject('/Resources'): DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})})
        return writer._add_object(stream.flate_encode())

    roots = []
    for _ in range(1 if shared else count):
        leaf = form(b'BT /F1 12 Tf 10 50 Td (Form policy.) Tj ET\n' + b' ' * padding
                    + (b' /Loop Do' if cycle else b''))
        root = leaf
        for _ in range(depth - 1):
            parent = form(b'/Child Do')
            parent.get_object()['/Resources'][NameObject('/XObject')] = DictionaryObject({NameObject('/Child'): root})
            root = parent
        if cycle:
            leaf.get_object()['/Resources'][NameObject('/XObject')] = DictionaryObject({NameObject('/Loop'): root})
            # A resource cycle must be refused before pypdf can skip it and return partial text.
        roots.append(root)
    for index in range(count):
        page = writer.add_blank_page(width=100, height=100)
        xobjects = DictionaryObject({NameObject('/Root'): roots[0 if shared else index]})
        if image:
            # Invalid compressed image data is harmless to text extraction and must not be decoded.
            picture = DecodedStreamObject()
            picture.set_data(b'not-an-image')
            picture[NameObject('/Subtype')] = NameObject('/Image')
            encoded = picture.flate_encode()
            encoded._data = b'not-a-valid-deflate-stream'
            xobjects[NameObject('/Picture')] = writer._add_object(encoded)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): xobjects})
        contents = DecodedStreamObject()
        contents.set_data(b'/Root Do' + (b' /Picture Do' if image else b''))
        page[NameObject('/Contents')] = writer._add_object(contents)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_nested_form_streams_share_document_decompression_budget():
    content = pdf_with_forms(count=13, padding=2 * 1024 * 1024, depth=2)
    assert len(content) < 50 * 1024
    with pytest.raises(IngestionError, match='累计'):
        parse_document('nested.pdf', content)


def test_single_form_stream_has_same_eight_mib_limit_as_page():
    with pytest.raises(IngestionError):
        parse_document('large-form.pdf', pdf_with_forms(padding=9 * 1024 * 1024))


def test_unknown_non_image_xobject_subtype_cannot_skip_preflight():
    writer = PdfWriter(clone_from=io.BytesIO(pdf_with_forms()))
    xobject = writer.pages[0]['/Resources']['/XObject']['/Root']
    xobject[NameObject('/Subtype')] = NameObject('/Unknown')
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(IngestionError, match='XObject'):
        parse_document('unknown-subtype.pdf', output.getvalue())


def test_cyclic_form_resources_are_rejected_before_extraction():
    with pytest.raises(IngestionError, match='循环'):
        parse_document('cycle.pdf', pdf_with_forms(cycle=True, depth=2))


def test_form_resource_depth_is_bounded():
    with pytest.raises(IngestionError, match='深度'):
        parse_document('deep.pdf', pdf_with_forms(depth=20))


def test_cached_shared_form_subtree_cannot_bypass_depth_limit():
    writer = PdfWriter(clone_from=io.BytesIO(pdf_with_forms(depth=4)))
    xobjects = writer.pages[0]['/Resources']['/XObject']
    root = xobjects.raw_get('/Root')
    for _ in range(13):
        wrapper = DecodedStreamObject()
        wrapper.set_data(b'/Child Do')
        wrapper.update({NameObject('/Subtype'): NameObject('/Form'),
                        NameObject('/BBox'): RectangleObject([0, 0, 100, 100]),
                        NameObject('/Resources'): DictionaryObject({
                            NameObject('/XObject'): DictionaryObject({NameObject('/Child'): root}),
                        })})
        root = writer._add_object(wrapper)
    xobjects[NameObject('/Deep')] = root
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(IngestionError, match='深度'):
        parse_document('shared-deep.pdf', output.getvalue())


def test_form_at_depth_limit_still_extracts_text():
    parsed = parse_document('allowed-depth.pdf', pdf_with_forms(depth=16))
    assert parsed['chunks'][0]['text'] == 'Form policy.'


def test_shared_indirect_form_is_counted_once_and_preserves_pages():
    parsed = parse_document('shared.pdf', pdf_with_forms(count=13, padding=2 * 1024 * 1024, shared=True, depth=2))
    assert len(parsed['chunks']) == 13
    assert [chunk['location'] for chunk in parsed['chunks']] == [f'第 {index} 页' for index in range(1, 14)]
    assert all(chunk['text'] == 'Form policy.' for chunk in parsed['chunks'])


def test_text_extraction_does_not_decode_image_xobjects():
    parsed = parse_document('image.pdf', pdf_with_forms(image=True))
    assert parsed['chunks'][0]['text'] == 'Form policy.'
