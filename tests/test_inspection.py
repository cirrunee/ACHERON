import json
from pathlib import Path
import struct
import zipfile

import pytest
from acheron.project import open_project, Project
from acheron.inspection import inspect_file, detect_format, SCAN_BYTES
from acheron.ai.evidence import build_context, parse_result
from acheron.report import report_chunks, ReportOptions, write_report


@pytest.mark.parametrize('name,payload,kind', [
    ('readme.txt', b'Hello file inspection!\n', 'Text / source / data file'),
    ('renamed.exe', b'{"enabled": true}', 'Text / source / data file'),
    ('empty.dat', b'', 'Empty file'),
    ('binary.data', b'\xff\xff\0\x80\x01\xfe', 'Unknown binary format'),
    ('app.elf', b'\x7fELF\x02\x01' + bytes(50), 'ELF executable / object'),
    ('image.png', b'\x89PNG\r\n\x1a\n' + bytes(8) + struct.pack('>II', 80, 90), 'PNG image'),
    ('wasm.data', b'\0asm\x01\0\0\0', 'WebAssembly'),
    ('broken.exe', b'MZbroken', 'Windows PE / DOS executable'),
])
def test_any_readable_file_opens_without_false_decompilation(tmp_path, name, payload, kind):
    path = tmp_path / name
    path.write_bytes(payload)
    project = open_project(path, inspect_fallback=True)
    assert project.image['kind'] == 'file'
    assert project.image['inspection']['format'] == kind
    assert not project.functions
    text = ''.join(report_chunks(project))
    assert kind in text and 'No code was decompiled' in text
    saved = tmp_path / (name + '.acheron')
    project.save(saved)
    path.unlink()
    assert Project.load(saved).snapshot() == project.snapshot()


def test_zip_office_preview_and_no_extraction(tmp_path):
    path = tmp_path / 'office.docx'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', '<document><p><t>Budget review</t></p></document>')
        archive.writestr('../escape.txt', 'Never extracted')
    project = inspect_file(path)
    data = project.image['inspection']
    assert data['format'] == 'Word document (DOCX)'
    assert 'Budget review' in data['text']
    assert len(data['entries']) == 2
    assert not (tmp_path.parent / 'escape.txt').exists()
    assert 'Budget review' in ''.join(report_chunks(project))


def test_scan_limit_and_utf16_strings(tmp_path):
    path = tmp_path / 'large.bin'
    path.write_bytes(b'\xff\0\x80\0' + 'Wide string'.encode('utf-16-le') + b'\0' * (SCAN_BYTES + 100))
    project = inspect_file(path)
    assert project.image['inspection']['sample_bytes'] == SCAN_BYTES
    assert any(row['text'] == 'Wide string' and row['encoding'] == 'UTF-16LE' for row in project.image['inspection']['strings'])
    assert any('first 8 MB' in note for note in project.diagnostics)
    assert project.binary['size'] == path.stat().st_size


def test_file_ai_context_offsets_and_export(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text('{"name": "demo", "enabled": true}', encoding='utf-8')
    project = inspect_file(path)
    before = project.snapshot()
    context = build_context(project, None)
    assert context['scope'] == 'file' and context['instruction_count'] == 0
    assert 'FILE BYTE OFFSETS' in context['limits']
    assert str(path) not in json.dumps(context)
    result = parse_result(json.dumps({'summary': 'A test explanation', 'findings': [{'title': 'Configuration', 'explanation': 'Test only', 'confidence': 'low', 'evidence_ids': ['E001', 'E999']}], 'limitations': ['Synthetic result']}), context, 'local', 'test-model')
    project.hypotheses.extend(result['findings'])
    project.annotations.append({'address': None, 'kind': 'charon-run', 'value': result['run']})
    assert result['findings'][0]['function_address'] is None
    assert result['findings'][0]['source_kind'] == 'file_offset'
    assert project.snapshot() == before
    text = ''.join(report_chunks(project))
    assert 'file offset 0x0' in text and 'Unresolved model citation: E999' in text
    assert 'A test explanation' in text


def test_inspect_cli_produces_simple_file_and_source_is_preserved(tmp_path, capsys):
    from acheron.cli import main
    path = tmp_path / 'notes.md'
    path.write_text('Readable source document.', encoding='utf-8')
    report = tmp_path / 'report.txt'
    assert main(['inspect', str(path), '--output', str(report)]) == 0
    assert 'Readable source document.' in report.read_text(encoding='utf-8')
    assert path.read_text() == 'Readable source document.'
    assert main(['inspect', str(path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['image']['kind'] == 'file'
