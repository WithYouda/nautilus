"""Original-file validation and derivatives use only synthetic in-memory inputs."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from zipfile import ZipFile

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest

from app.learning_domain import DomainError
from app.material_files import prepare_material_file, render_material_page


def image_bytes(image_format='PNG', *, size=(12, 8), color='red', orientation=None, mode='RGB'):
    output = BytesIO()
    with Image.new(mode, size, color) as image:
        options = {}
        if orientation is not None:
            exif = Image.Exif()
            exif[274] = orientation
            options['exif'] = exif
        image.save(output, format=image_format, **options)
    return output.getvalue()


def pdf_bytes(*page_texts, encrypted=False, password='password', scan=False):
    writer = PdfWriter()
    for text in page_texts:
        page = writer.add_blank_page(width=120, height=80)
        if text is not None:
            font = DictionaryObject({
                NameObject('/Type'): NameObject('/Font'),
                NameObject('/Subtype'): NameObject('/Type1'),
                NameObject('/BaseFont'): NameObject('/Helvetica'),
            })
            page[NameObject('/Resources')] = DictionaryObject({
                NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)}),
            })
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 12 Tf 15 30 Td ({text}) Tj ET'.encode('ascii'))
            page[NameObject('/Contents')] = writer._add_object(stream)
    if scan:
        output = BytesIO()
        with Image.new('RGB', (120, 80), 'red') as image:
            image.save(output, format='PDF', resolution=72)
        writer.add_page(PdfReader(BytesIO(output.getvalue())).pages[0])
    if encrypted:
        writer.encrypt(password)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def assert_error(code, function, *args, status=422):
    with pytest.raises(DomainError) as failure:
        function(*args)
    assert failure.value.code == code
    assert failure.value.status == status
    assert str(failure.value) == code


def test_text_and_docx_preserve_full_text():
    content = '完整文字\n' * 20000
    prepared = prepare_material_file('notes.md', b'\xef\xbb\xbf' + content.encode('utf-8'))
    assert prepared == {
        'input_kind': 'text', 'media_type': 'text/markdown', 'content': content,
        'pages': [], 'needs_processing': False,
    }
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + content + '</w:t><w:tab/><w:t>end</w:t><w:br/><w:t>next</w:t></w:r></w:p></w:body></w:document>')
    prepared = prepare_material_file('notes.docx', output.getvalue())
    assert prepared['input_kind'] == 'text'
    assert prepared['media_type'].endswith('wordprocessingml.document')
    assert prepared['content'] == content + '\tend\nnext'
    assert not prepared['needs_processing']


def test_complete_pdf_retains_all_page_text_with_page_markers():
    raw = pdf_bytes('first', 'second')
    prepared = prepare_material_file('notes.PDF', raw)
    assert prepared == {
        'input_kind': 'pdf', 'media_type': 'application/pdf',
        'content': '[第 1 页]\nfirst\n\n[第 2 页]\nsecond',
        'pages': [{'number': 1, 'text': 'first'}, {'number': 2, 'text': 'second'}],
        'needs_processing': False,
    }
    assert raw == pdf_bytes('first', 'second')


@pytest.mark.parametrize('texts,scan,expected', [
    ((None,), False, [{'number': 1, 'text': ''}]),
    ((), True, [{'number': 1, 'text': ''}]),
    (('readable',), True, [{'number': 1, 'text': 'readable'}, {'number': 2, 'text': ''}]),
    (('readable', None, 'later'), False, [{'number': 1, 'text': 'readable'}, {'number': 2, 'text': ''}, {'number': 3, 'text': 'later'}]),
])
def test_scanned_blank_and_mixed_pdf_never_claim_partial_text_is_complete(texts, scan, expected):
    prepared = prepare_material_file('notes.pdf', pdf_bytes(*texts, scan=scan))
    assert prepared['content'] is None
    assert prepared['pages'] == expected
    assert prepared['needs_processing'] is True


@pytest.mark.parametrize('extension,image_format,media_type', [
    ('png', 'PNG', 'image/png'), ('jpg', 'JPEG', 'image/jpeg'),
    ('jpeg', 'JPEG', 'image/jpeg'), ('webp', 'WEBP', 'image/webp'),
])
def test_supported_images_validate_actual_bytes_and_render_png(extension, image_format, media_type):
    raw = image_bytes(image_format)
    before = bytes(raw)
    assert prepare_material_file('picture.' + extension, raw) == {
        'input_kind': 'image', 'media_type': media_type, 'content': None,
        'pages': [{'number': 1, 'text': ''}], 'needs_processing': True,
    }
    rendered, rendered_media_type = render_material_page(raw, media_type)
    assert rendered_media_type == 'image/png'
    with Image.open(BytesIO(rendered)) as image:
        assert image.format == 'PNG'
        assert image.size == (12, 8)
        assert image.getpixel((0, 0))[0] > 240
    assert raw == before


@pytest.mark.parametrize('image_format,media_type', [
    ('PNG', 'image/png'), ('JPEG', 'image/jpeg'), ('WEBP', 'image/webp'),
])
def test_preview_respects_exif_orientation(image_format, media_type):
    raw = image_bytes(image_format, size=(20, 10), orientation=6)
    rendered, _ = render_material_page(raw, media_type)
    with Image.open(BytesIO(rendered)) as image:
        assert image.size == (10, 20)
        assert image.getexif().get(274) is None
    with Image.open(BytesIO(raw)) as original:
        assert original.size == (20, 10)
        assert original.getexif().get(274) == 6


def test_preview_preserves_transparency_and_supports_cmyk_jpeg():
    transparent, _ = render_material_page(image_bytes(mode='RGBA', color=(255, 0, 0, 80)), 'image/png')
    with Image.open(BytesIO(transparent)) as image:
        assert image.mode == 'RGBA'
        assert image.getpixel((0, 0))[3] == 80
    cmyk, _ = render_material_page(image_bytes('JPEG', mode='CMYK', color=(0, 255, 255, 0)), 'image/jpeg')
    with Image.open(BytesIO(cmyk)) as image:
        assert image.mode == 'RGB'
        assert image.getpixel((0, 0))[0] > 240


def test_pdf_preview_renders_requested_page_at_scale_two_and_supports_concurrency():
    raw = pdf_bytes('text', scan=True)
    before = bytes(raw)
    def render(number):
        return render_material_page(raw, 'application/pdf', number)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(render, [1, 2, 1, 2]))
    for index, (rendered, media_type) in enumerate(results):
        assert media_type == 'image/png'
        with Image.open(BytesIO(rendered)) as image:
            assert image.size == (240, 160)
            if index % 2:
                assert image.getpixel((120, 80))[:3] == (254, 0, 0)
            else:
                assert image.getpixel((120, 80))[:3] == (255, 255, 255)
    assert raw == before


@pytest.mark.parametrize('name,raw,code', [
    ('notes.txt', b'\xff', 'material_file_encoding'),
    ('notes.txt', b'  ', 'material_file_no_text'),
    ('notes.docx', b'broken archive', 'material_file_unreadable'),
    ('notes.pdf', b'not a PDF', 'material_file_unreadable'),
    ('picture.png', b'not an image', 'material_file_unreadable'),
    ('notes.exe', b'data', 'material_file_unsupported'),
    ('', b'data', 'invalid_material_title'),
])
def test_prepare_errors_are_fixed_codes(name, raw, code):
    assert_error(code, prepare_material_file, name, raw)


def test_image_extension_and_media_type_must_match_actual_supported_format():
    raw = image_bytes('PNG')
    assert_error('material_file_unsupported', prepare_material_file, 'picture.jpg', raw)
    assert_error('material_file_unsupported', render_material_page, raw, 'image/jpeg')
    gif = image_bytes('GIF')
    assert_error('material_file_unsupported', prepare_material_file, 'picture.png', gif)
    assert_error('material_file_unsupported', render_material_page, gif, 'image/gif')


@pytest.mark.parametrize('image_format,extension', [('PNG', 'png'), ('JPEG', 'jpg'), ('WEBP', 'webp')])
def test_truncated_images_are_not_accepted_from_headers_alone(image_format, extension):
    raw = image_bytes(image_format, size=(30, 20))
    assert_error('material_file_unreadable', prepare_material_file, 'picture.' + extension, raw[:len(raw) // 2])


def test_standard_decoder_security_error_is_retained(monkeypatch):
    raw = image_bytes(size=(20, 10))
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 10)
    assert_error('material_file_unreadable', prepare_material_file, 'picture.png', raw)
    assert_error('material_file_unreadable', render_material_page, raw, 'image/png')


def test_encrypted_and_zero_page_pdfs_are_explicit_errors():
    encrypted = pdf_bytes('secret', encrypted=True)
    empty = pdf_bytes()
    for raw, code in [(encrypted, 'material_file_encrypted'), (empty, 'material_file_no_pages')]:
        assert_error(code, prepare_material_file, 'notes.pdf', raw)
        assert_error(code, render_material_page, raw, 'application/pdf')


def test_empty_password_encryption_is_not_silently_opened():
    raw = pdf_bytes('secret', encrypted=True, password='')
    assert_error('material_file_encrypted', prepare_material_file, 'notes.pdf', raw)
    assert_error('material_file_encrypted', render_material_page, raw, 'application/pdf')


def test_corrupt_pdf_page_tree_does_not_escape_as_a_decoder_error():
    raw = pdf_bytes('text').replace(b'/Pages 2 0 R', b'/Pages 0 0 R')
    assert_error('material_file_unreadable', prepare_material_file, 'notes.pdf', raw)
    assert_error('material_file_unreadable', render_material_page, raw, 'application/pdf')


@pytest.mark.parametrize('fail_save', [False, True])
def test_pdf_render_closes_handles_on_success_and_decoder_failure(monkeypatch, fail_save):
    import pypdfium2 as pdfium
    raw = pdf_bytes('first', 'second')
    handles = []
    requested_pages = []
    document_type = pdfium.PdfDocument
    get_page = document_type.get_page
    render = pdfium.PdfPage.render

    def document(*args, **kwargs):
        result = document_type(*args, **kwargs)
        handles.append(result)
        return result

    def page(document, index):
        requested_pages.append(index)
        result = get_page(document, index)
        handles.append(result)
        return result

    def bitmap(page, *args, **kwargs):
        result = render(page, *args, **kwargs)
        handles.append(result)
        return result

    monkeypatch.setattr(pdfium, 'PdfDocument', document)
    monkeypatch.setattr(document_type, 'get_page', page)
    monkeypatch.setattr(pdfium.PdfPage, 'render', bitmap)
    if fail_save:
        def broken_save(*args, **kwargs):
            raise OSError('SYNTHETIC_PRIVATE_DECODER_DETAIL')
        monkeypatch.setattr(Image.Image, 'save', broken_save)
        assert_error('material_file_unreadable', render_material_page, raw, 'application/pdf', 2)
    else:
        assert render_material_page(raw, 'application/pdf', 2)[1] == 'image/png'
    assert requested_pages == [1]
    assert len(handles) == 3
    assert all(handle.raw is None for handle in handles)


@pytest.mark.parametrize('page_number', [0, -1, 1.5, True, '1'])
def test_invalid_page_numbers_have_fixed_errors(page_number):
    assert_error('material_file_page_invalid', render_material_page, image_bytes(), 'image/png', page_number)


def test_missing_pages_and_unsupported_preview_have_fixed_errors():
    assert_error('material_file_page_not_found', render_material_page, image_bytes(), 'image/png', 2, status=404)
    assert_error('material_file_page_not_found', render_material_page, pdf_bytes('one'), 'application/pdf', 2, status=404)
    assert_error('material_file_unreadable', render_material_page, b'broken pdf', 'application/pdf')
    assert_error('material_file_unsupported', render_material_page, b'text', 'text/plain')
