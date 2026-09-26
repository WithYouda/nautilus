"""Text-only extraction for task material uploads."""
from __future__ import annotations

from io import BytesIO
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

from .learning_domain import DomainError

TEXT_EXTENSIONS = {'.txt', '.md', '.markdown', '.json', '.csv', '.tsv', '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.xml', '.yaml', '.yml', '.sql', '.sh', '.rs', '.go', '.java', '.c', '.cpp', '.h'}


def extract_material_text(filename: str, raw: bytes) -> str:
    name = PurePath(filename.replace('\\', '/')).name
    if not name or name in {'.', '..'} or len(name) > 300:
        raise DomainError('invalid_material_title', 422)
    suffix = PurePath(name).suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        try:
            content = raw.decode('utf-8-sig')
        except UnicodeDecodeError as error:
            raise DomainError('material_file_encoding', 422) from error
    elif suffix == '.docx':
        content = _docx_text(raw)
    elif suffix == '.pdf':
        content = _pdf_text(raw)
    else:
        raise DomainError('material_file_unsupported', 422)
    if not content.strip():
        raise DomainError('material_file_no_text', 422)
    return content


def _docx_text(raw: bytes) -> str:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            xml = archive.read('word/document.xml')
        root = ElementTree.fromstring(xml)
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        lines = []
        for paragraph in root.iter(ns + 'p'):
            fragments = []
            for node in paragraph.iter():
                if node.tag == ns + 't':
                    fragments.append(node.text or '')
                elif node.tag == ns + 'tab':
                    fragments.append('\t')
                elif node.tag in {ns + 'br', ns + 'cr'}:
                    fragments.append('\n')
            line = ''.join(fragments)
            if line.strip():
                lines.append(line)
        return '\n'.join(lines)
    except (BadZipFile, KeyError, ElementTree.ParseError, RuntimeError, ValueError) as error:
        raise DomainError('material_file_unreadable', 422) from error


def _pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(raw), strict=False)
        if reader.is_encrypted:
            raise DomainError('material_file_encrypted', 422)
        parts = []
        for page in reader.pages:
            part = page.extract_text() or ''
            parts.append(part)
        return '\n'.join(parts)
    except DomainError:
        raise
    except Exception as error:
        raise DomainError('material_file_unreadable', 422) from error
