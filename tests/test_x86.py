import json
from pathlib import Path
import sqlite3

from acheron import analyze
from acheron.discovery import Discovery
from acheron.model import Limits
from acheron.pe import PELoader
from acheron.project import Project
from acheron.x64 import X86Architecture
from acheron.ai.evidence import build_context
from .helpers import pe
from .air_oracle import evaluate

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/known_x86_O0.exe'
BASE = 0x401000


def decode(code):
    image = PELoader().load(pe(bytes.fromhex(code), bits=32))
    return Discovery(image, X86Architecture(), Limits()).run()[0]


def test_32bit_register_aliases_flags_push_and_operand_override():
    function = decode('b8ffffffff b401 6640 6aff 58 83c001 7501 c3 c3')
    instructions = [i for b in function.blocks for i in b.instructions]
    first, high, inc, push = instructions[:4]
    assert first.writes == ('eax',) and 'eax' not in first.reads
    assert 'eax' in high.reads and high.operands[0].offset == 8
    assert inc.mnemonic == 'inc' and inc.operands[0].width == 16
    assert push.operands[0].width == 32 and push.operands[0].value == 0xffffffff
    text = function.decompile()
    assert 'eax = 0xffffffff' in text and 'insert_bits(eax, 8, 8' in text
    assert 'push32(state, 0xffffffff)' in text and 'condition_ne(eflags)' in text
    assert not any(name in text for name in ('rax', 'rsp', 'rflags', 'zext64'))


def test_x86_address_width_absolute_fs_and_16bit_override():
    function = decode('a1 00204000 648b0d 30000000 678b00 c3')
    instructions = function.blocks[0].instructions
    assert instructions[0].operands[1].address_width == 32
    assert instructions[0].operands[1].displacement == 0x402000
    assert instructions[1].operands[1].segment == 'fs'
    assert instructions[2].operands[1].address_width == 16
    text = function.decompile()
    assert 'segment_base(fs) + wrap32(0x30)' in text
    assert 'wrap16(bx + si * 1)' in text


def test_compiled_x86_matches_known_c_and_survives_reload(tmp_path):
    project = analyze(FIXTURE)
    assert len(project.functions) == 5
    functions = {f.name: f for f in project.functions}
    assert len(functions['choose'].blocks) == 4
    for x in (-100, -5, 0, 4, 5, 20, 100):
        assert evaluate(functions['choose'], x) == ((x - 3 if x > 4 else x + 7) & 0xffffffff)
    for a in (-9, 0, 10, 0x7fffffff):
        for b in (-3, 1, 5):
            assert evaluate(functions['add_pair'], a, b) == (a + b) & 0xffffffff
    context = build_context(project, functions['choose'])
    assert context['architecture'] == 'x86' and context['bitness'] == 32
    target = tmp_path / 'x86.acheron'
    project.save(target)
    restored = Project.load(target)
    assert restored.snapshot() == project.snapshot()
    assert restored.function(functions['choose'].address).decompile() == functions['choose'].decompile()


def test_legacy_x64_project_remains_readable(tmp_path):
    project = analyze(FIXTURE.with_name('known_O0.exe'))
    path = tmp_path / 'old.acheron'
    project.save(path)
    snapshot = project.snapshot()
    snapshot['engine'] = '0.1.0'
    for function in snapshot['functions']:
        function.pop('bitness')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE artifacts SET payload=? WHERE stage='snapshot'", (json.dumps(snapshot),))
    restored = Project.load(path)
    assert all(f.bitness == 64 for f in restored.functions)
    assert restored.functions[0].decompile() == project.functions[0].decompile()
