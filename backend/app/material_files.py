"""Validate original material files and prepare text or page-image derivatives."""
from __future__ import annotations

from contextlib import closing, contextmanager
from io import BytesIO
from pathlib import PurePath
from threading import Lock
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree

from PIL import Image, ImageOps

from .learning_domain import DomainError

TEXT_EXTENSIONS = {'.txt', '.md', '.markdown', '.json', '.csv', '.tsv', '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.xml', '.yaml', '.yml', '.sql', '.sh', '.rs', '.go', '.java', '.c', '.cpp', '.h'}
IMAGE_EXTENSIONS = {
    '.png': ('PNG', 'image/png'),
    '.jpg': ('JPEG', 'image/jpeg'),
    '.jpeg': ('JPEG', 'image/jpeg'),
    '.webp': ('WEBP', 'image/webp'),
}
DOCX_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
TEXT_MEDIA_TYPES = {
    '.md': 'text/markdown', '.markdown': 'text/markdown',
    '.json': 'application/json', '.csv': 'text/csv', '.tsv': 'text/tab-separated-values',
    '.html': 'text/html', '.css': 'text/css', '.xml': 'application/xml',
    '.yaml': 'application/yaml', '.yml': 'application/yaml',
    '.js': 'text/javascript', '.jsx': 'text/javascript',
}
# PDFium is not thread-safe, even when separate documents are being rendered.
_PDF_RENDER_LOCK = Lock()


def prepare_material_file(filename: str, raw: bytes) -> dict:
    """Keep page boundaries and expose when the original still needs image input.

    This does not run OCR. ``needs_processing`` allows direct vision as well as
    an optional OCR route; extracted text from only part of a PDF is not a full
    document body. The caller remains responsible for retaining ``raw``.
    """
    name = PurePath(filename.replace('\\', '/')).name
    if not name or name in {'.', '..'} or len(name) > 300:
        raise DomainError('invalid_material_title', 422)
    suffix = PurePath(name).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        image_format, media_type = IMAGE_EXTENSIONS[suffix]
        with _validated_image(raw, image_format):
            pass
        return {
            'input_kind': 'image', 'media_type': media_type, 'content': None,
            'pages': [{'number': 1, 'text': ''}], 'needs_processing': True,
        }
    if suffix == '.pdf':
        pages = _pdf_pages(raw)
        needs_processing = any(not page['text'].strip() for page in pages)
        content = None if needs_processing else '\n\n'.join(
            f"[第 {page['number']} 页]\n{page['text']}" for page in pages
        )
        return {
            'input_kind': 'pdf', 'media_type': 'application/pdf', 'content': content,
            'pages': pages, 'needs_processing': needs_processing,
        }
    content = extract_material_text(filename, raw)
    return {
        'input_kind': 'text',
        'media_type': DOCX_MEDIA_TYPE if suffix == '.docx' else TEXT_MEDIA_TYPES.get(suffix, 'text/plain'),
        'content': content, 'pages': [], 'needs_processing': False,
    }


def render_material_page(raw: bytes, media_type: str, page_number: int = 1) -> tuple[bytes, str]:
    """Render one original page as PNG without replacing or modifying ``raw``."""
    if type(page_number) is not int or page_number < 1:
        raise DomainError('material_file_page_invalid', 422)
    image_formats = {value[1]: value[0] for value in IMAGE_EXTENSIONS.values()}
    if media_type in image_formats:
        if page_number != 1:
            raise DomainError('material_file_page_not_found', 404)
        with _validated_image(raw, image_formats[media_type]) as original:
            try:
                with ImageOps.exif_transpose(original) as oriented:
                    # PNG cannot encode JPEG CMYK pixels; preserve alpha when present.
                    with oriented.convert('RGBA' if 'A' in oriented.getbands() or 'transparency' in oriented.info else 'RGB') as image:
                        output = BytesIO()
                        image.save(output, format='PNG')
                        return output.getvalue(), 'image/png'
            except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError):
                raise DomainError('material_file_unreadable', 422) from None
    if media_type != 'application/pdf':
        raise DomainError('material_file_unsupported', 422)
    # Check encryption before PDFium; even empty-password encrypted files remain
    # explicit errors rather than silently producing an unlocked derivative.
    try:
        with closing(_pdf_reader(raw)) as reader:
            if not len(reader.pages):
                raise DomainError('material_file_no_pages', 422)
        import pypdfium2 as pdfium
        with _PDF_RENDER_LOCK:
            with pdfium.PdfDocument(raw) as document:
                if not len(document):
                    raise DomainError('material_file_no_pages', 422)
                if page_number > len(document):
                    raise DomainError('material_file_page_not_found', 404)
                with closing(document.get_page(page_number - 1)) as page:
                    with closing(page.render(scale=2)) as bitmap:
                        with bitmap.to_pil() as image:
                            output = BytesIO()
                            image.save(output, format='PNG')
                            return output.getvalue(), 'image/png'
    except DomainError:
        raise
    except Exception:
        raise DomainError('material_file_unreadable', 422) from None


@contextmanager
def _validated_image(raw: bytes, image_format: str):
    """Verify the file structure and decode pixels, retaining Pillow safeguards."""
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format != image_format:
                raise DomainError('material_file_unsupported', 422)
            image.verify()
        # verify() does not decode pixels and requires reopening before load().
        with Image.open(BytesIO(raw)) as image:
            image.load()
            yield image
    except DomainError:
        raise
    except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError):
        raise DomainError('material_file_unreadable', 422) from None


def _pdf_reader(raw: bytes):
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(raw), strict=False)
        if reader.is_encrypted:
            raise DomainError('material_file_encrypted', 422)
        return reader
    except DomainError:
        raise
    except Exception:
        raise DomainError('material_file_unreadable', 422) from None


def _pdf_pages(raw: bytes) -> list[dict]:
    try:
        with closing(_pdf_reader(raw)) as reader:
            pages = [
                {'number': number, 'text': page.extract_text() or ''}
                for number, page in enumerate(reader.pages, 1)
            ]
        if not pages:
            raise DomainError('material_file_no_pages', 422)
        return pages
    except DomainError:
        raise
    except Exception:
        raise DomainError('material_file_unreadable', 422) from None


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
