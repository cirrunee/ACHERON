"""Defensive, read-only PE metadata parsing. No OS loader calls are used."""
from __future__ import annotations

from dataclasses import dataclass, field
import struct

from .model import AnalysisError, Limits


@dataclass(frozen=True)
class Section:
    name: str
    rva: int
    virtual_size: int
    raw_offset: int
    raw_size: int
    characteristics: int

    @property
    def span(self) -> int:
        return max(self.virtual_size, self.raw_size)

    @property
    def executable(self) -> bool:
        return bool(self.characteristics & 0x20000000)


@dataclass
class PEImage:
    data: bytes = field(repr=False)
    architecture: str
    bitness: int
    image_base: int
    entry: int
    image_size: int
    headers_size: int
    sections: list[Section]
    directories: list[tuple[int, int]]
    imports: list[dict] = field(default_factory=list)
    exports: list[dict] = field(default_factory=list)
    runtime_functions: list[tuple[int, int, int]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def section_at(self, address: int) -> Section | None:
        rva = address - self.image_base
        return next((s for s in self.sections if s.rva <= rva < s.rva + s.span), None)

    def executable(self, address: int) -> bool:
        s = self.section_at(address)
        return bool(s and s.executable and address - self.image_base - s.rva < s.raw_size)

    def rva_offset(self, rva: int, size: int = 1) -> int:
        if rva < 0 or size < 0 or rva + size > self.image_size:
            raise AnalysisError(f"RVA range outside image: {rva:#x}+{size:#x}")
        if rva < self.headers_size and rva + size <= self.headers_size:
            if rva + size <= len(self.data):
                return rva
        for s in self.sections:
            delta = rva - s.rva
            if 0 <= delta < s.span and delta + size <= s.raw_size:
                return s.raw_offset + delta
        raise AnalysisError(f"RVA has no contiguous file backing: {rva:#x}+{size:#x}")

    def read_rva(self, rva: int, size: int) -> bytes:
        offset = self.rva_offset(rva, size)
        return self.data[offset:offset + size]

    def read_va(self, address: int, size: int) -> bytes:
        return self.read_rva(address - self.image_base, size)

    def code_bytes(self, address: int, maximum: int = 15) -> bytes:
        s = self.section_at(address)
        if not s or not self.executable(address):
            raise AnalysisError(f"Address is not file-backed executable code: {address:#x}")
        size = min(maximum, s.raw_size - (address - self.image_base - s.rva))
        return self.read_va(address, size)

    def cstring(self, rva: int, maximum: int = 4096) -> str:
        # Bound by the contiguous mapping before searching, never walk into a gap.
        offset = self.rva_offset(rva)
        s = self.section_at(self.image_base + rva)
        available = (s.raw_size - (rva - s.rva)) if s else self.headers_size - rva
        raw = self.data[offset:offset + min(maximum, available)]
        end = raw.find(b"\0")
        if end < 0:
            raise AnalysisError(f"Unterminated metadata string at RVA {rva:#x}")
        return raw[:end].decode("ascii", errors="backslashreplace")


def _unpack(data: bytes, fmt: str, offset: int) -> tuple:
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise AnalysisError(f"Truncated PE field at file offset {offset:#x}")
    return struct.unpack_from(fmt, data, offset)


class PELoader:
    def load(self, data: bytes, limits: Limits = Limits()) -> PEImage:
        if len(data) > limits.max_file_bytes:
            raise AnalysisError("Input exceeds file byte budget")
        if data[:2] != b"MZ":
            raise AnalysisError("Unsupported format: expected DOS MZ signature")
        (pe,) = _unpack(data, "<I", 0x3C)
        if pe < 64 or data[pe:pe + 4] != b"PE\0\0":
            raise AnalysisError("Invalid PE signature or DOS header overlap")
        machine, count, _, _, _, optional_size, _ = _unpack(data, "<HHIIIHH", pe + 4)
        if not 0 < count <= limits.max_sections:
            raise AnalysisError("Invalid section count or section budget exceeded")
        opt = pe + 24
        (magic,) = _unpack(data, "<H", opt)
        if magic not in (0x10B, 0x20B):
            raise AnalysisError(f"Unsupported optional header magic: {magic:#x}")
        bits = 64 if magic == 0x20B else 32
        minimum = 112 if bits == 64 else 96
        if optional_size < minimum or opt + optional_size > len(data):
            raise AnalysisError("Truncated optional header")
        (entry_rva,) = _unpack(data, "<I", opt + 16)
        (base,) = _unpack(data, "<Q" if bits == 64 else "<I", opt + (24 if bits == 64 else 28))
        image_size, headers_size = _unpack(data, "<II", opt + 56)
        if not headers_size <= len(data) or not 0 < headers_size <= image_size:
            raise AnalysisError("Invalid image/header sizes")
        if base + image_size > 1 << bits:
            raise AnalysisError("Image address range overflows architecture width")
        if entry_rva >= image_size:
            raise AnalysisError("Entry point RVA exceeds image range")
        (directory_count,) = _unpack(data, "<I", opt + minimum - 4)
        if directory_count > 16 or minimum + directory_count * 8 > optional_size:
            raise AnalysisError("Invalid or truncated data directory array")
        dirs = [_unpack(data, "<II", opt + minimum + i * 8) for i in range(directory_count)]
        dirs += [(0, 0)] * (16 - len(dirs))
        table = opt + optional_size
        if table + count * 40 > headers_size:
            raise AnalysisError("Section table exceeds SizeOfHeaders")
        sections = []
        for i in range(count):
            name, vs, rva, raw_size, raw, _, _, _, _, flags = _unpack(data, "<8sIIIIIIHHI", table + i * 40)
            s = Section(name.rstrip(b"\0").decode("ascii", "backslashreplace"), rva, vs, raw, raw_size, flags)
            if s.span and (rva < headers_size or rva + s.span > image_size):
                raise AnalysisError("Section virtual range outside image or overlaps headers")
            if raw_size and (raw < headers_size or raw + raw_size > len(data)):
                raise AnalysisError("Section file range outside input or overlaps headers")
            sections.append(s)
        for i, a in enumerate(sections):
            for b in sections[i + 1:]:
                if a.span and b.span and max(a.rva, b.rva) < min(a.rva + a.span, b.rva + b.span):
                    raise AnalysisError("Overlapping virtual sections are unsupported")
                if a.raw_size and b.raw_size and max(a.raw_offset, b.raw_offset) < min(a.raw_offset + a.raw_size, b.raw_offset + b.raw_size):
                    raise AnalysisError("Overlapping raw sections are unsupported")
        arch = {0x8664: "x86_64", 0x14C: "x86", 0xAA64: "arm64"}.get(machine, f"machine_{machine:04x}")
        if (arch == "x86_64" and bits != 64) or (arch == "x86" and bits != 32):
            raise AnalysisError("Machine type disagrees with optional header")
        image = PEImage(data, arch, bits, base, base + entry_rva if entry_rva else 0, image_size, headers_size, sections, dirs)
        for index, (rva, size) in enumerate(dirs):
            if index == 8 and rva and not size:  # GlobalPtr has a specified zero Size.
                image.rva_offset(rva)
                continue
            if bool(rva) != bool(size):
                raise AnalysisError(f"Inconsistent directory {index} address/size")
            if size:
                if index == 4:  # Certificate directory contains a file offset, not an RVA.
                    if rva + size > len(data):
                        raise AnalysisError("Certificate directory exceeds input")
                else:
                    image.rva_offset(rva, size)
        self._exports(image, limits)
        self._imports(image, limits)
        self._runtime_functions(image, limits)
        for index, label in ((2, "resources"), (5, "relocations"), (6, "debug/PDB"), (9, "TLS callbacks"), (10, "load configuration"), (13, "delay imports"), (14, ".NET metadata")):
            if dirs[index][1]:
                image.diagnostics.append(f"{label}: directory mapped; semantic parsing unsupported in v0.1")
        return image

    @staticmethod
    def _exports(image: PEImage, limits: Limits) -> None:
        rva, size = image.directories[0]
        if not size:
            return
        if size < 40:
            raise AnalysisError("Truncated export directory")
        fields = struct.unpack("<IIHHIIIIIII", image.read_rva(rva, 40))
        base, count, names, eat, name_table, ord_table = fields[5:]
        if max(count, names) > limits.max_directory_entries or names > count:
            raise AnalysisError("Export table count exceeds budget or function count")
        addresses = image.read_rva(eat, count * 4) if count else b""
        names_data = image.read_rva(name_table, names * 4) if names else b""
        ord_data = image.read_rva(ord_table, names * 2) if names else b""
        aliases: dict[int, list[str]] = {}
        for i in range(names):
            (ordinal,) = struct.unpack_from("<H", ord_data, i * 2)
            if ordinal >= count:
                raise AnalysisError("Export name ordinal outside address table")
            (name_rva,) = struct.unpack_from("<I", names_data, i * 4)
            aliases.setdefault(ordinal, []).append(image.cstring(name_rva))
        for i in range(count):
            (target,) = struct.unpack_from("<I", addresses, i * 4)
            if not target:
                continue
            forwarded = rva <= target < rva + size
            image.exports.append({"address": None if forwarded else image.image_base + target,
                                  "ordinal": base + i, "names": aliases.get(i, []),
                                  "forwarder": image.cstring(target, min(4096, rva + size - target)) if forwarded else None})

    @staticmethod
    def _imports(image: PEImage, limits: Limits) -> None:
        rva, size = image.directories[1]
        if not size:
            return
        width = image.bitness // 8
        fmt = "<Q" if width == 8 else "<I"
        entries = 0
        for offset in range(0, size - 19, 20):
            if offset // 20 >= limits.max_directory_entries:
                raise AnalysisError("Import descriptor budget exceeded")
            desc = struct.unpack("<IIIII", image.read_rva(rva + offset, 20))
            if not any(desc):
                return
            original, _, _, name_rva, iat = desc
            if not name_rva or not iat:
                raise AnalysisError("Invalid import descriptor")
            dll = image.cstring(name_rva)
            lookup = original or iat
            for i in range(limits.max_directory_entries + 1):
                (value,) = struct.unpack(fmt, image.read_rva(lookup + i * width, width))
                image.rva_offset(iat + i * width, width)
                if not value:
                    break
                entries += 1
                if entries > limits.max_directory_entries:
                    raise AnalysisError("Import entry budget exceeded")
                ordinal = value & 0xFFFF if value & (1 << (image.bitness - 1)) else None
                if ordinal is None:
                    image.read_rva(value, 2)  # hint
                name = None if ordinal is not None else image.cstring(value + 2)
                image.imports.append({"dll": dll, "name": name, "ordinal": ordinal,
                                      "iat_address": image.image_base + iat + i * width})
        raise AnalysisError("Unterminated import descriptor table")

    @staticmethod
    def _runtime_functions(image: PEImage, limits: Limits) -> None:
        rva, size = image.directories[3]
        if not size:
            return
        if image.architecture != "x86_64":
            image.diagnostics.append("Exception metadata parsing unsupported for this architecture")
            return
        if size % 12 or size // 12 > limits.max_directory_entries:
            raise AnalysisError("Invalid or oversized x64 runtime-function table")
        for offset in range(0, size, 12):
            start, end, unwind = struct.unpack("<III", image.read_rva(rva + offset, 12))
            if not 0 < start < end <= image.image_size:
                raise AnalysisError("Invalid runtime-function range")
            image.read_rva(unwind, 4)
            image.runtime_functions.append((image.image_base + start, image.image_base + end, image.image_base + unwind))
        image.diagnostics.append("Runtime-function ranges parsed; unwind opcodes and exception CFG edges unsupported")
