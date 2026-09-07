"""Small independent AIR-L test interpreter for compiled scalar fixtures.

This evaluates bounded bitvectors and dictionary memory in Python. It never loads
or executes native code, accesses host addresses, or calls an external function.
It is a validation oracle for a subset, not an ACHERON dynamic-analysis feature.
"""
from acheron.x64 import GPRS


def evaluate(function, rcx: int, rdx: int = 0) -> int:
    from acheron.x64 import X86Architecture
    bits = function.bitness
    sp, result_register = ('esp', 'eax') if bits == 32 else ('rsp', 'rax')
    registers = dict.fromkeys(X86Architecture.gprs if bits == 32 else GPRS, 0)
    registers[sp] = 0x10000
    if bits == 64:
        registers.update(rcx=rcx & ((1 << 64) - 1), rdx=rdx & ((1 << 64) - 1))
    memory = {}
    flags = {"z": False, "s": False, "o": False, "c": False}

    def mask(width):
        return (1 << width) - 1

    def getreg(name):
        if name in registers:
            return registers[name]
        if name.startswith("e"):
            return registers["r" + name[1:]] & mask(32)
        raise AssertionError(name)

    def location(op):
        assert op.segment not in ("fs", "gs")
        return ((getreg(op.base) if op.base else 0) + (getreg(op.index) * op.scale if op.index else 0) + op.displacement) & mask(op.address_width)

    def load(address, width):
        return sum(memory.get(address + i, 0) << (8 * i) for i in range(width // 8))

    def store(address, width, value):
        for i in range(width // 8):
            memory[address + i] = (value >> (8 * i)) & 255

    if bits == 32:
        # cdecl parameters live above the 4-byte return address on the stack.
        store(registers[sp] + 4, 32, rcx)
        store(registers[sp] + 8, 32, rdx)

    def read(op):
        if op.kind == "register":
            return (registers[op.parent] >> op.offset) & mask(op.width)
        if op.kind == "constant":
            return op.value
        if op.kind == "memory":
            return load(location(op), op.width)
        raise AssertionError(op)

    def write(op, value):
        value &= mask(op.width)
        if op.kind == "memory":
            store(location(op), op.width, value)
        elif op.width in (32, 64):
            registers[op.parent] = value
        else:
            field_mask = mask(op.width) << op.offset
            registers[op.parent] = (registers[op.parent] & ~field_mask) | (value << op.offset)

    blocks = {b.address: b for b in function.blocks}
    current = function.address
    for _ in range(10000):
        block = blocks[current]
        for op in block.air:
            assert op.supported, op
            args = op.operands
            if op.opcode in ("copy", "load", "store"):
                write(args[0], read(args[1]))
            elif op.opcode == "address":
                write(args[0], location(args[1]))
            elif op.opcode == "push":
                value, width = read(args[0]), args[0].width
                registers[sp] -= width // 8
                store(registers[sp], width, value)
            elif op.opcode == "pop":
                value = load(registers[sp], args[0].width)
                registers[sp] += args[0].width // 8
                write(args[0], value)
            elif op.opcode in ("add", "sub", "compare", "and", "or", "xor", "test"):
                a, b, width = read(args[0]), read(args[1]), args[0].width
                subtract = op.opcode in ("sub", "compare")
                if op.opcode == "add":
                    result = a + b
                elif subtract:
                    result = a - b
                elif op.opcode in ("and", "test"):
                    result = a & b
                elif op.opcode == "or":
                    result = a | b
                else:
                    result = a ^ b
                sign = 1 << (width - 1)
                result_masked = result & mask(width)
                flags["z"], flags["s"] = result_masked == 0, bool(result_masked & sign)
                flags["c"] = a < b if subtract else result > mask(width) if op.opcode == "add" else False
                flags["o"] = bool(((a ^ b) if subtract else ~(a ^ b)) & (a ^ result_masked) & sign) if subtract or op.opcode == "add" else False
                if op.opcode not in ("compare", "test"):
                    write(args[0], result_masked)
            elif op.opcode == "return":
                return registers[result_register] & mask(32)
            elif op.opcode not in ("branch", "jump", "nop"):
                raise AssertionError(op.opcode)
        if len(block.edges) == 2:
            m = block.instructions[-1].mnemonic
            truth = {"je": flags["z"], "jne": not flags["z"], "jl": flags["s"] != flags["o"],
                     "jle": flags["z"] or flags["s"] != flags["o"], "jg": not flags["z"] and flags["s"] == flags["o"],
                     "jge": flags["s"] == flags["o"], "jb": flags["c"], "jae": not flags["c"]}[m]
            current = block.edges[0 if truth else 1].target
        else:
            assert len(block.edges) == 1 and block.edges[0].internal
            current = block.edges[0].target
    raise AssertionError("Oracle step budget exhausted")
