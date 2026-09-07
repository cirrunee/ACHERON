from pathlib import Path

import pytest

from acheron import AnalysisError, Limits, analyze
from acheron.dataflow import analyze as flow
from acheron.discovery import Discovery
from acheron.pe import PELoader
from acheron.pseudocode import render_with_map
from acheron.x64 import X64Architecture
from .helpers import pe

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
BASE = 0x140001000


def recover(code: str, limits: Limits = Limits()):
    image = PELoader().load(pe(bytes.fromhex(code)))
    discovery = Discovery(image, X64Architecture(), limits)
    return discovery, discovery.run()


def test_decoder_widths_rip_memory_partial_registers_and_opaque_simd():
    image = PELoader().load(pe(bytes.fromhex("b8 ffffffff b0 01 488b05 10000000 0f58c1 c3")))
    arch = X64Architecture()
    first = arch.decode(image, BASE)
    assert first.operands[0].width == 32
    assert first.writes == ("rax",)
    assert "rax" not in first.reads
    partial = arch.decode(image, BASE + 5)
    assert "rax" in partial.reads and "rax" in partial.writes
    load = arch.decode(image, BASE + 7)
    assert load.operands[1].displacement == BASE + 14 + 16
    assert arch.lift(load).opcode == "load"
    vector = arch.decode(image, BASE + 14)
    assert not arch.lift(vector).supported


def test_diamond_and_reaching_definitions():
    # test ecx,ecx; je B; mov eax,1; jmp join; B: mov eax,2; join: ret
    _, functions = recover("85c9 7407 b801000000 eb05 b802000000 c3")
    function = functions[0]
    assert len(function.blocks) == 4
    assert [(e.kind, e.target) for e in function.blocks[0].edges] == [("true", BASE + 11), ("false", BASE + 4)]
    result = flow(function)
    assert set(result["use_def"][f"{BASE + 16:#x}:rax"]) == {f"{BASE + 11:#x}:rax", f"{BASE + 4:#x}:rax"}
    assert "rcx" in result["liveness"][hex(BASE)]["in"]
    assert set(result["reaching_in"][hex(BASE + 16)]["rax"]) == {f"{BASE + 4:#x}:rax", f"{BASE + 11:#x}:rax"}


def test_loop_fixed_point_and_backward_edge():
    # eax=0; loop: eax+=1; cmp eax,ecx; jl loop; ret
    _, functions = recover("31c0 83c001 39c8 7cf9 c3")
    function = functions[0]
    assert len(function.blocks) == 3
    assert any(e.target == BASE + 2 for b in function.blocks for e in b.edges)
    result = flow(function)
    assert set(result["use_def"][f"{BASE + 2:#x}:rax"]) == {f"{BASE:#x}:rax", f"{BASE + 2:#x}:rax"}


def test_recursive_call_seed_and_call_graph():
    discovery, functions = recover("e801000000 c3 b82a000000 c3")
    assert [f.address for f in functions] == [BASE, BASE + 6]
    assert any(e.source == "direct-call" for e in functions[1].evidence)
    assert (BASE, BASE, BASE + 6, "call") in discovery.references
    assert all(i.address < BASE + 6 for b in functions[0].blocks for i in b.instructions)


def test_call_clobbers_prevent_false_def_use():
    _, functions = recover("b801000000 e801000000 c3 c3")
    function = functions[0]
    result = flow(function)
    assert result["use_def"][f"{BASE + 10:#x}:rax"] == [f"{BASE + 5:#x}:rax"]


def test_indirect_and_overlapping_control_flow_are_explicit():
    _, functions = recover("ffe0")
    assert functions[0].blocks[0].edges[0].target is None
    assert not functions[0].complete
    assert "unresolved_transfer" in functions[0].decompile()
    _, functions = recover("b800000000 ebfa")  # jmp into immediate of mov
    assert any("Overlapping" in d for d in functions[0].diagnostics)
    assert not functions[0].blocks[-1].edges[0].internal


def test_budget_exhaustion_is_error_not_success():
    with pytest.raises(AnalysisError, match="budget"):
        recover("909090c3", Limits(max_instructions=2))
    _, functions = recover("31c0 83c001 39c8 7cf9 c3")
    with pytest.raises(AnalysisError, match="budget"):
        flow(functions[0], Limits(max_flow_steps=1))


def test_pseudocode_preserves_width_flags_and_all_source_addresses():
    _, functions = recover("b0ff 83c001 7501 c3 c3")
    function = functions[0]
    text, mapping = render_with_map(function)
    assert "insert_bits(rax, 0, 8, 0xff)" in text
    assert "rax = zext64(" in text
    assert "flags_add32" in text and "condition_ne(rflags)" in text
    assert "NOT original source" in text
    assert set(mapping) == {i.address for b in function.blocks for i in b.instructions}
    assert all(1 <= line <= len(text.splitlines()) for lines in mapping.values() for line in lines)


@pytest.mark.parametrize("filename", ["known_O0.exe", "known_O1.exe"])
def test_compiled_known_source_functions_and_cfg(filename):
    project = analyze(FIXTURES / filename)
    names = {f.name for f in project.functions}
    assert {"choose", "sum_to", "add_pair", "invoke"} <= names
    assert len(project.functions) == 5
    assert all(f.blocks for f in project.functions)
    assert all(all(d.startswith("Function boundary transfer") for d in f.diagnostics) for f in project.functions)
    assert len(project.references) >= 3
    add = next(f for f in project.functions if f.name == "add_pair")
    assert any(op.opcode in ("add", "address") for b in add.blocks for op in b.air)
    if filename == "known_O0.exe":
        choose = next(f for f in project.functions if f.name == "choose")
        assert len(choose.blocks) == 4
        loop = next(f for f in project.functions if f.name == "sum_to")
        assert any(e.internal and e.target <= b.address for b in loop.blocks for e in b.edges)


def test_x86_analysis_is_supported(tmp_path):
    binary = tmp_path / "x86.exe"
    binary.write_bytes(pe(bits=32))
    project = analyze(binary)
    assert project.image['bitness'] == 32
    assert project.functions[0].bitness == 32
    assert project.functions[0].blocks[0].instructions[0].mnemonic == 'ret'
