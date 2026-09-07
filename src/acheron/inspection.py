"""Bounded, read-only inspection for arbitrary regular files. No content execution."""
from collections import Counter
import codecs
import hashlib
import math
from pathlib import Path
import re
import stat
import struct
import zipfile
from xml.etree import ElementTree

from .model import AnalysisError, Limits

SCAN_BYTES = 8 * 1024 * 1024
TEXT_CHARS = 64000
MAX_STRINGS = 2000
MAX_ENTRIES = 2000


def detect_format(data, filename=''):
    signatures = ((b'MZ', 'Windows PE / DOS executable'), (b'\x7fELF', 'ELF executable / object'),
                  (b'\x00asm', 'WebAssembly'), (b'%PDF-', 'PDF document'),
                  (b'SQLite format 3\0', 'SQLite database'), (b'\x89PNG\r\n\x1a\n', 'PNG image'),
                  (b'\xff\xd8\xff', 'JPEG image'), (b'GIF87a', 'GIF image'), (b'GIF89a', 'GIF image'),
                  (b'PK\x03\x04', 'ZIP archive'), (b'PK\x05\x06', 'ZIP archive'),
                  (b'7z\xbc\xaf\x27\x1c', '7-Zip archive'), (b'Rar!\x1a\x07', 'RAR archive'),
                  (b'\x1f\x8b', 'GZIP archive'), (b'BZh', 'BZIP2 archive'),
                  (b'\xfd7zXZ\x00', 'XZ archive'), (b'\xd0\xcf\x11\xe0', 'OLE compound document'),
                  (b'fLaC', 'FLAC audio'), (b'OggS', 'Ogg media'), (b'ID3', 'MP3 audio'),
                  (b'\xca\xfe\xba\xbe', 'Java class / Mach-O universal'),
                  (b'dex\n', 'Android DEX bytecode'), (b'\x00\x00\x01\x00', 'Windows icon'))
    for magic, name in signatures:
        if data.startswith(magic):
            return name
    if data[:4] in (b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', b'\xbe\xba\xfe\xca'):
        return 'Mach-O executable / object'
    if data[:4] == b'RIFF' and len(data) >= 12:
        return {b'WAVE': 'WAV audio', b'WEBP': 'WebP image', b'AVI ': 'AVI video'}.get(data[8:12], 'RIFF media')
    if data[4:8] == b'ftyp':
        return 'MP4 / ISO media'
    if data[257:262] == b'ustar':
        return 'TAR archive'
    return 'Empty file' if not data else 'Unknown binary format'


def readable_text(data):
    if not data:
        return '', 'UTF-8'
    candidates = ['utf-8-sig']
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        candidates = ['utf-16']
    elif data[:4096].count(b'\0') > len(data[:4096]) // 5:
        candidates = ['utf-16-le', 'utf-16-be']
    for encoding in candidates:
        try:
            # An inspection prefix can end in the middle of a multibyte character.
            text = codecs.getincrementaldecoder(encoding)(errors='strict').decode(data, final=False)
        except UnicodeError:
            continue
        if sum(not (c.isprintable() or c in '\r\n\t') for c in text) <= len(text) * .01:
            return text[:TEXT_CHARS], encoding
    return '', ''


def scan_strings(data):
    rows = []
    for encoding, pattern in (('ASCII', rb'[\x20-\x7e]{4,}'), ('UTF-16LE', rb'(?:[\x20-\x7e]\x00){4,}'), ('UTF-16BE', rb'(?:\x00[\x20-\x7e]){4,}')):
        for match in re.finditer(pattern, data):
            if len(rows) >= MAX_STRINGS:
                return sorted(rows, key=lambda r: r['offset']), True
            raw = match.group()[:1000 if encoding == 'ASCII' else 2000]
            text = raw.decode('ascii' if encoding == 'ASCII' else encoding.lower())
            rows.append({'offset': match.start(), 'text': text, 'encoding': encoding, 'truncated': len(match.group()) > len(raw)})
    return sorted(rows, key=lambda r: r['offset']), False


def archive_details(path, total, notes):
    """Bound central-directory allocation before using ZipFile. Never extract entries."""
    with path.open('rb') as stream:
        stream.seek(max(0, total - 65557))
        tail = stream.read(65557)
    start = tail.rfind(b'PK\x05\x06')
    if start < 0 or len(tail) - start < 22:
        raise ValueError('ZIP directory footer missing or truncated')
    _, disk, cd_disk, disk_count, count, cd_size, cd_offset, comment = struct.unpack_from('<4s4H2IH', tail, start)
    if disk or cd_disk or count != disk_count or count == 65535 or cd_size == 0xffffffff or cd_offset == 0xffffffff:
        raise ValueError('ZIP64 or multi-volume listing is not available; bytes and strings remain accessible')
    if count > MAX_ENTRIES or cd_size > 4 * 1024 * 1024 or cd_offset + cd_size > total or start + 22 + comment != len(tail):
        raise ValueError('ZIP directory exceeds inspection limits or is malformed')
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ValueError('ZIP entry count exceeds inspection limit')
        rows = [{'name': i.filename[:1000], 'size': i.file_size, 'compressed': i.compress_size, 'encrypted': bool(i.flag_bits & 1)} for i in infos]
        names = {i.filename for i in infos}
        kind, members = 'ZIP archive', []
        if 'word/document.xml' in names:
            kind, members = 'Word document (DOCX)', ['word/document.xml']
        elif 'ppt/presentation.xml' in names:
            kind, members = 'PowerPoint presentation (PPTX)', sorted(n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml', n))[:8]
        elif 'xl/workbook.xml' in names:
            kind, members = 'Excel workbook (XLSX)', ['xl/sharedStrings.xml'] if 'xl/sharedStrings.xml' in names else []
        elif 'AndroidManifest.xml' in names and 'classes.dex' in names:
            kind = 'Android package (APK)'
        elif 'META-INF/MANIFEST.MF' in names:
            kind = 'Java archive (JAR)'
        elif 'mimetype' in names or 'META-INF/container.xml' in names:
            kind = 'Document / book ZIP container'
        parts, remaining = [], 2 * 1024 * 1024
        for name in members:
            info = archive.getinfo(name)
            if info.flag_bits & 1 or info.file_size > remaining or info.file_size > max(info.compress_size, 1) * 200:
                notes.append(f'Skipped oversized, highly compressed or encrypted document part: {name}')
                continue
            with archive.open(info) as stream:
                data = stream.read(remaining + 1)
            remaining -= len(data)
            if remaining < 0 or b'\0' in data or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                notes.append('Document XML could not be safely previewed within limits.')
                break
            document = ElementTree.fromstring(data)
            values = [element.text for element in document.iter() if element.tag.rsplit('}', 1)[-1] == 't' and element.text]
            parts.append(name + '\n' + '\n'.join(values))
        if kind.startswith('Excel'):
            notes.append('Spreadsheet preview shows shared text only; formulas, cells and macros are not evaluated.')
        if kind.startswith(('Word', 'PowerPoint')):
            notes.append('Document text preview omits layout, images, comments and some document parts.')
        return kind, rows, '\n\n'.join(parts)[:TEXT_CHARS]


def inspect_file(path, *, progress=None, limits=Limits(), reason=''):
    from .project import Project
    path = Path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise AnalysisError('Choose a regular file. Folders and device streams cannot be inspected.')
    report = progress or (lambda message: None)
    digest, sampled, total = hashlib.sha256(), bytearray(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            total += len(chunk)
            if len(sampled) < SCAN_BYTES:
                sampled.extend(chunk[:SCAN_BYTES - len(sampled)])
            if total % (16 * 1024 * 1024) == 0:
                report(f'Reading file and computing fingerprint · {total // (1024 * 1024)} MB')
    if path.stat().st_mtime_ns != info.st_mtime_ns or total != info.st_size:
        raise AnalysisError('The file changed while being read. Try again after it finishes saving.')
    data = bytes(sampled)
    kind = detect_format(data, path.name)
    notes = [reason] if reason else []
    text, encoding = readable_text(data[:min(len(data), TEXT_CHARS * 2)])
    if text and kind == 'Unknown binary format':
        kind = 'Text / source / data file'
    rows, strings_truncated = scan_strings(data)
    properties = {'Detected format': kind, 'File size': f'{total:,} bytes', 'Text encoding': encoding or 'Not identified'}
    if data[:2] == b'MZ' and len(data) == total:
        from .pe import PELoader
        try:
            pe = PELoader().load(data, limits)
            properties.update({'PE architecture': pe.architecture, 'PE bitness': str(pe.bitness), 'Entry address': hex(pe.entry),
                               'Imported symbols': str(len(pe.imports)), 'Exported symbols': str(len(pe.exports))})
            if pe.directories[14][1]:
                kind = 'Windows .NET / mixed-mode assembly'
                properties['Detected format'] = kind
        except AnalysisError:
            pass
    entries = []
    if kind == 'ZIP archive':
        try:
            kind, entries, document_text = archive_details(path, total, notes)
            properties['Detected format'] = kind
            if document_text:
                text = document_text
                properties['Text encoding'] = 'Extracted document XML text'
        except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError, RuntimeError, ElementTree.ParseError) as exc:
            notes.append(f'Archive listing: {exc}')
    if kind == 'PNG image' and len(data) >= 24:
        width, height = struct.unpack_from('>II', data, 16)
        properties['Image dimensions'] = f'{width} × {height} pixels (header)'
    elif kind == 'GIF image' and len(data) >= 10:
        width, height = struct.unpack_from('<HH', data, 6)
        properties['Image dimensions'] = f'{width} × {height} pixels (header)'
    elif kind == 'ELF executable / object' and len(data) >= 20:
        properties['ELF class'] = {1: '32-bit', 2: '64-bit'}.get(data[4], 'Unknown')
        properties['Byte order'] = {1: 'Little endian', 2: 'Big endian'}.get(data[5], 'Unknown')
    elif kind == 'WebAssembly' and len(data) >= 8:
        properties['WASM version'] = str(int.from_bytes(data[4:8], 'little'))
    counts = Counter(data)
    entropy = -sum((n / len(data)) * math.log2(n / len(data)) for n in counts.values()) if data else 0
    properties['Byte entropy in inspected range'] = f'{entropy:.3f} bits/byte (does not identify encryption)'
    properties['Bytes inspected for strings'] = f'{len(data):,} of {total:,}'
    if len(data) < total:
        notes.append(f'Text and strings scan is limited to the first {SCAN_BYTES // 1024 // 1024} MB. SHA-256 covers the entire file.')
    if len(data) > TEXT_CHARS or len(text) >= TEXT_CHARS:
        notes.append('Text preview is bounded; it may contain only the beginning of the file or document.')
    if strings_truncated:
        notes.append(f'Strings limited to {MAX_STRINGS} entries; individual strings are limited to 1000 characters.')
    notes.append('File inspection does not execute content, evaluate scripts, or claim source-code recovery. Compressed/encrypted content may need its own decoder or key.')
    preview = {'format': kind, 'properties': properties, 'text': text, 'strings': rows, 'entries': entries,
               'hex': data[:65536].hex(), 'sample_bytes': len(data), 'total_bytes': total}
    image = {'kind': 'file', 'architecture': 'not decoded', 'bitness': 0, 'entry': 0, 'image_base': 0, 'image_size': total,
             'imports': [], 'exports': [], 'sections': [], 'inspection': preview}
    report('Preparing file inspection')
    return Project({'path': str(path.resolve()), 'filename': path.name, 'size': total, 'sha256': digest.hexdigest()}, image, [], [], notes, limits)
