"""iced-x86 decoding adapter and deliberately limited AIR-L lifter."""
from __future__ import annotations

import iced_x86 as ix

from .interfaces import BinaryImage
from .model import AirOp, AnalysisError, Evidence, Instruction, Operand, Status

_REGS = {v: k.lower() for k, v in vars(ix.Register).items() if k.isupper()}
_MNEMONICS = {v: k.lower() for k, v in vars(ix.Mnemonic).items() if k.isupper()}
_FLOWS = {ix.FlowControl.NEXT: "next", ix.FlowControl.CONDITIONAL_BRANCH: "branch",
          ix.FlowControl.UNCONDITIONAL_BRANCH: "jump", ix.FlowControl.INDIRECT_BRANCH: "indirect_jump",
          ix.FlowControl.CALL: "call", ix.FlowControl.INDIRECT_CALL: "indirect_call",
          ix.FlowControl.RETURN: "return"}
_READ = {ix.OpAccess.READ, ix.OpAccess.COND_READ, ix.OpAccess.READ_WRITE, ix.OpAccess.READ_COND_WRITE}
_WRITE = {ix.OpAccess.WRITE, ix.OpAccess.COND_WRITE, ix.OpAccess.READ_WRITE, ix.OpAccess.READ_COND_WRITE}
_IMM_WIDTH = {ix.OpKind.IMMEDIATE8: 8, ix.OpKind.IMMEDIATE8_2ND: 8, ix.OpKind.IMMEDIATE16: 16,
              ix.OpKind.IMMEDIATE32: 32, ix.OpKind.IMMEDIATE64: 64, ix.OpKind.IMMEDIATE8TO16: 16,
              ix.OpKind.IMMEDIATE8TO32: 32, ix.OpKind.IMMEDIATE8TO64: 64, ix.OpKind.IMMEDIATE32TO64: 64}
_BRANCHES = {ix.OpKind.NEAR_BRANCH16, ix.OpKind.NEAR_BRANCH32, ix.OpKind.NEAR_BRANCH64}
GPRS = tuple("rax rcx rdx rbx rsp rbp rsi rdi r8 r9 r10 r11 r12 r13 r14 r15".split())
# Unknown calls are intentionally more conservative than the Windows ABI.
CALL_STATE = tuple(sorted((*GPRS, "rflags", *(f"zmm{i}" for i in range(32)))))
CONDITIONS = {"ja", "jae", "jb", "jbe", "je", "jne", "jg", "jge", "jl", "jle", "jo", "jno", "jp", "jnp", "js", "jns"}


def register(reg: int, bitness: int = 64) -> Operand:
    name = _REGS[reg]
    parent = ix.RegisterExt.full_register32(reg) if bitness == 32 else ix.RegisterExt.full_register(reg)
    return Operand("register", ix.RegisterExt.size(reg) * 8, name,
                   _REGS[parent], 8 if name in ("ah", "bh", "ch", "dh") else 0)


class X64Architecture:
    name = "x86_64"
    bitness = 64
    gprs = GPRS
    flags = 'rflags'
    call_state = CALL_STATE

    def __init__(self) -> None:
        self.formatter = ix.Formatter(ix.FormatterSyntax.NASM)
        self.formatter.hex_prefix = "0x"
        self.formatter.hex_suffix = ""
        self.formatter.uppercase_hex = False
        self.info = ix.InstructionInfoFactory()

    def decode(self, image: BinaryImage, address: int) -> Instruction:
        data = image.code_bytes(address, 15)
        ins = ix.Decoder(self.bitness, data, ip=address).decode()
        if ins.is_invalid:
            raise AnalysisError(f"Invalid or truncated instruction at {address:#x}")
        info = self.info.info(ins)
        operands = []
        for i in range(ins.op_count):
            kind = ins.op_kind(i)
            if kind == ix.OpKind.REGISTER:
                operand = register(ins.op_register(i), self.bitness)
            elif kind in _IMM_WIDTH:
                width = _IMM_WIDTH[kind]
                operand = Operand("constant", width, value=ins.immediate(i) & ((1 << width) - 1))
            elif kind in _BRANCHES:
                operand = Operand("address", {ix.OpKind.NEAR_BRANCH16: 16, ix.OpKind.NEAR_BRANCH32: 32, ix.OpKind.NEAR_BRANCH64: 64}[kind], value=ins.near_branch_target)
            elif kind == ix.OpKind.MEMORY:
                width = ix.MemorySizeExt.size(ins.memory_size) * 8
                displacement = ins.memory_displacement
                base = "" if ins.memory_base == ix.Register.NONE else _REGS[ins.memory_base]
                index = "" if ins.memory_index == ix.Register.NONE else _REGS[ins.memory_index]
                # Same rule as iced's get_address_size_in_bytes: base/index,
                # absolute displacement size, then the decoder's code size.
                regs = [r for r in (ins.memory_base, ins.memory_index) if r != ix.Register.NONE]
                address_width = ix.RegisterExt.size(regs[0]) * 8 if regs else ins.memory_displ_size * 8 if ins.memory_displ_size in (2, 4, 8) else self.bitness
                if ins.is_ip_rel_memory_operand:
                    base, displacement = "", ins.ip_rel_memory_address
                elif base or index:
                    displacement &= (1 << address_width) - 1
                    if displacement & (1 << (address_width - 1)):
                        displacement -= 1 << address_width
                operand = Operand("memory", width, base=base, index=index,
                                  scale=ins.memory_index_scale, displacement=displacement,
                                  segment=_REGS[ins.memory_segment], address_width=address_width)
            else:
                operand = Operand("unknown", text=self.formatter.format_operand(ins, i))
            operands.append(operand)
        reads, writes = set(), set()
        for used in info.used_registers():
            reg = register(used.register, self.bitness)
            if used.access in _READ:
                reads.add(reg.parent)
            if used.access in _WRITE:
                writes.add(reg.parent)
                # Preserve parent bits on partial writes, and old values on conditional writes.
                parent = ix.RegisterExt.full_register32(used.register) if self.bitness == 32 else ix.RegisterExt.full_register(used.register)
                if reg.width < ix.RegisterExt.size(parent) * 8 or used.access in (ix.OpAccess.COND_WRITE, ix.OpAccess.READ_COND_WRITE):
                    reads.add(reg.parent)
        # iced reports full r64 writes for zero-extending r32 destinations.
        if ins.rflags_read:
            reads.add(self.flags)
        if ins.rflags_modified:
            writes.add(self.flags)
            # Some instructions only change a subset of flags (e.g. INC keeps CF).
            reads.add(self.flags)
        memory = set()
        for used in info.used_memory():
            if used.access in _READ:
                memory.add("read")
            if used.access in _WRITE:
                memory.add("write")
        flow = _FLOWS.get(ins.flow_control, "stop")
        if flow in ("call", "indirect_call"):
            reads.update(self.call_state)
            writes.update(self.call_state)
            memory.update(("read", "write", "unknown"))
        if flow == "return":
            # No prototype is proven, so all machine state is externally observable.
            reads.update(self.call_state)
        target = ins.near_branch_target if ins.op_count and ins.op_kind(0) in _BRANCHES else None
        return Instruction(address, ins.len, data[:ins.len].hex(), self.formatter.format(ins),
                           _MNEMONICS[ins.mnemonic], tuple(operands), flow, target,
                           tuple(sorted(reads)), tuple(sorted(writes)), tuple(sorted(memory)),
                           ins.has_lock_prefix or ins.has_rep_prefix or ins.has_repne_prefix
                           or ins.is_call_far or ins.is_call_far_indirect or ins.is_jmp_far or ins.is_jmp_far_indirect)

    def lift(self, ins: Instruction) -> AirOp:
        ops, mnemonic = ins.operands, ins.mnemonic
        opcode = "opaque"
        scalar = all(o.kind in ("register", "constant", "memory", "address") and o.width in (8, 16, 32, 64)
                     and (o.kind != "register" or o.parent in self.gprs) for o in ops)
        if not ins.opaque_prefix:
            if mnemonic == "nop":
                opcode = "nop"
            elif ins.flow == "branch" and mnemonic in CONDITIONS:
                opcode = "branch"
            elif ins.flow == "jump" and ops and ops[0].kind == 'address':
                opcode = "jump"
            elif ins.flow in ("call", "indirect_call") and mnemonic == 'call' and ops and ops[0].kind != 'unknown':
                opcode = "call"
            elif ins.flow == "return" and mnemonic == "ret":
                opcode = "return"
            elif mnemonic in ("push", "pop") and scalar and len(ops) == 1 and ops[0].kind in ("register", "constant"):
                opcode = mnemonic
            elif mnemonic == "lea" and len(ops) == 2 and ops[0].kind == "register" and ops[0].parent in self.gprs and ops[1].kind == "memory":
                opcode = "address"
            elif scalar and len(ops) == 2:
                dest, source = ops
                if mnemonic == "mov":
                    if dest.kind == "register":
                        opcode = "load" if source.kind == "memory" else "copy"
                    elif dest.kind == "memory" and source.kind in ("register", "constant"):
                        opcode = "store"
                elif mnemonic == "lea" and dest.kind == "register" and source.kind == "memory":
                    opcode = "address"
                elif mnemonic in ("add", "sub", "and", "or", "xor") and dest.kind == "register" and source.kind in ("register", "constant", "memory"):
                    opcode = mnemonic
                elif mnemonic in ("cmp", "test"):
                    opcode = "compare" if mnemonic == "cmp" else "test"
        return AirOp(f"L_{ins.address:x}", ins.address, opcode, ops, ins.reads, ins.writes,
                     ins.memory, opcode != "opaque", Evidence(Status.INFERRED if opcode != "opaque" else Status.UNKNOWN,
                     "x86-lifter-v1" if self.bitness == 32 else "x64-lifter-v1", 1.0 if opcode != "opaque" else 0.0,
                     (ins.address,), "Decoded machine effects; no source-level types inferred" if opcode != "opaque"
                     else "Semantic lifting unsupported; decoder effects retained"),
                     ins.text if opcode == "opaque" else mnemonic)


class X86Architecture(X64Architecture):
    """32-bit protected-mode PE code; scalar AIR remains deliberately bounded."""
    name = 'x86'
    bitness = 32
    gprs = tuple('eax ecx edx ebx esp ebp esi edi'.split())
    flags = 'eflags'
    call_state = tuple(sorted((*gprs, flags, *(f'zmm{i}' for i in range(8)))))
