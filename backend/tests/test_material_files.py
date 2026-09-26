"""File uploads use isolated synthetic conversations and never retain raw bytes."""
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.learning_domain import DomainError
from app.material_files import extract_material_text
from test_ai_conversations import make_client, authorize, create_task, start_conversation


def docx(text: str, padding: int = 0) -> bytes:
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + ' ' * padding + '<w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


def text_pdf(text: str) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=100)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f'BT /F1 12 Tf 20 50 Td ({text}) Tj ET'.encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_text_and_docx_extraction_boundaries():
    assert extract_material_text('notes.md', b'\xef\xbb\xbfhello') == 'hello'
    assert extract_material_text('notes.docx', docx('hello')) == 'hello'
    assert extract_material_text('notes.pdf', text_pdf('hello')) == 'hello'
    long_text = 'a' * 70001
    assert extract_material_text('long.txt', long_text.encode()) == long_text
    assert extract_material_text('long.docx', docx(long_text)) == long_text
    assert extract_material_text('long.pdf', text_pdf(long_text)) == long_text
    for name, content, code in [
        ('notes.png', b'pixels', 'material_file_unsupported'),
        ('notes.txt', b'\xff', 'material_file_encoding'),
        ('notes.txt', b'  ', 'material_file_no_text'),
    ]:
        with pytest.raises(DomainError, match=code):
            extract_material_text(name, content)


def test_docx_tabs_and_line_breaks():
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>A</w:t><w:tab/><w:t>B</w:t><w:br/><w:t>C</w:t></w:r></w:p></w:body></w:document>')
    assert extract_material_text('notes.docx', output.getvalue()) == 'A\tB\nC'


def test_pdf_without_text_and_encrypted_pdf_are_explicit():
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    with pytest.raises(DomainError, match='material_file_no_text'):
        extract_material_text('blank.pdf', output.getvalue())
    writer.encrypt('password')
    output = BytesIO()
    writer.write(output)
    with pytest.raises(DomainError, match='material_file_encrypted'):
        extract_material_text('protected.pdf', output.getvalue())


def test_upload_auth_large_file_and_extracted_storage(tmp_path):
    with make_client(tmp_path, lambda request: None) as client:
        authorize(client)
        conversation = start_conversation(client, create_task(client))
        path = f'/api/materials/conversation/{conversation}/upload'
        headers = {'X-Filename': 'notes%20one.docx', 'Content-Type': 'application/octet-stream'}
        response = client.post(path, headers=headers, content=docx('SYNTHETIC_PRIVATE_TEXT', padding=6 * 1024 * 1024))
        assert response.status_code == 201, response.text
        assert response.json()['title'] == 'notes one.docx'
        assert response.json()['content'] == 'SYNTHETIC_PRIVATE_TEXT'
        assert client.post('/api/materials/conversation/not-owned/upload', headers=headers, content=b'x').status_code == 404


def test_long_materials_and_more_than_eight_are_saved_and_frozen(tmp_path):
    with make_client(tmp_path, lambda request: None) as client:
        authorize(client)
        cid = start_conversation(client, create_task(client))
        base = f'/api/materials/conversation/{cid}'
        body = '完整正文' * 20000
        ids = []
        for index in range(9):
            response = client.post(base, json={'title': f'资料{index}', 'content': body})
            assert response.status_code == 201, response.text
            ids.append(response.json()['id'])
        identity = client.app.state.auth.ensure_local_identity()
        frozen = client.app.state.materials.freeze(identity, 'conversation', cid,
            {'mode': 'reference', 'version_ids': ids})
        assert len(frozen['materials']) == 9
        assert all(item['content'] == body for item in frozen['materials'])
        assert len(client.get(base).json()['versions']) == 9
