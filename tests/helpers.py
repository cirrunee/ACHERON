"""Synthetic PE construction for malformed-input tests, not compiler fixtures."""
import struct


def pe(code: bytes = b"\xc3", *, bits: int = 64, entry: int = 0x1000) -> bytes:
    data = bytearray(0x800)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    optional = 240 if bits == 64 else 224
    struct.pack_into("<HHIIIHH", data, 0x84, 0x8664 if bits == 64 else 0x14C, 2, 0, 0, 0, optional, 0x22)
    opt = 0x98
    struct.pack_into("<H", data, opt, 0x20B if bits == 64 else 0x10B)
    struct.pack_into("<I", data, opt + 16, entry)
    struct.pack_into("<Q" if bits == 64 else "<I", data, opt + (24 if bits == 64 else 28), 0x140000000 if bits == 64 else 0x400000)
    struct.pack_into("<II", data, opt + 32, 0x1000, 0x200)
    struct.pack_into("<II", data, opt + 56, 0x3000, 0x200)
    struct.pack_into("<I", data, opt + (108 if bits == 64 else 92), 16)
    section = opt + optional
    struct.pack_into("<8sIIIIIIHHI", data, section, b".text", len(code), 0x1000, 0x200, 0x200, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<8sIIIIIIHHI", data, section + 40, b".rdata", 0x400, 0x2000, 0x400, 0x400, 0, 0, 0, 0, 0x40000040)
    if len(code) > 0x200:
        raise ValueError("Synthetic code exceeds fixture section")
    data[0x200:0x400] = b"\xcc" * 0x200
    data[0x200:0x200 + len(code)] = code
    return bytes(data)


def directory(data: bytearray, index: int, rva: int, size: int) -> None:
    struct.pack_into("<II", data, 0x98 + 112 + index * 8, rva, size)
