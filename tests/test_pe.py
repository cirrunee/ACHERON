import random
import struct

import pytest

from acheron.model import AnalysisError, Limits
from acheron.pe import PELoader
from .helpers import directory, pe


@pytest.mark.parametrize("bits", [32, 64])
def test_headers_and_address_mapping(bits):
    image = PELoader().load(pe(bits=bits))
    assert image.bitness == bits
    assert image.read_va(image.entry, 1) == b"\xc3"
    assert image.executable(image.entry)
    assert not image.executable(image.image_base + 0x2000)
    assert image.rva_offset(0x1000) == 0x200
    with pytest.raises(AnalysisError):
        image.read_rva(0x11FF, 2)
    with pytest.raises(AnalysisError):
        image.read_rva(-1, 1)


def test_virtual_tail_has_no_file_backing():
    data = bytearray(pe())
    struct.pack_into("<I", data, 0x188 + 8, 0x500)
    image = PELoader().load(bytes(data))
    assert not image.executable(image.image_base + 0x1300)
    with pytest.raises(AnalysisError, match="backing"):
        image.read_rva(0x1300, 1)


@pytest.mark.parametrize("offset,value", [(0x3C, 0xFFFFFFF0), (0x98 + 60, 0xFFFFFFFF), (0x188 + 20, 0x700), (0x188 + 40 + 12, 0x1100)])
def test_bad_offsets_and_overlap(offset, value):
    data = bytearray(pe())
    struct.pack_into("<I", data, offset, value)
    with pytest.raises(AnalysisError):
        PELoader().load(bytes(data))


def test_truncation_at_every_byte():
    data = pe()
    for length in range(len(data)):
        with pytest.raises(AnalysisError):
            PELoader().load(data[:length])


def test_import_name_and_ordinal():
    data = bytearray(pe())
    directory(data, 1, 0x2000, 40)
    struct.pack_into("<IIIII", data, 0x400, 0x2050, 0, 0, 0x2040, 0x2080)
    data[0x440:0x44D] = b"KERNEL32.dll\0"
    struct.pack_into("<QQQ", data, 0x450, 0x20C0, 0x8000000000000007, 0)
    struct.pack_into("<QQQ", data, 0x480, 0x20C0, 0x8000000000000007, 0)
    data[0x4C0:0x4CE] = b"\0\0ExitProcess\0"
    image = PELoader().load(bytes(data))
    assert image.imports[0]["name"] == "ExitProcess"
    assert image.imports[1]["ordinal"] == 7
    assert image.imports[0]["iat_address"] == image.image_base + 0x2080


def test_exports_and_forwarder():
    data = bytearray(pe())
    directory(data, 0, 0x2000, 0x100)
    struct.pack_into("<IIHHIIIIIII", data, 0x400, 0, 0, 0, 0, 0, 1, 2, 1, 0x2040, 0x2050, 0x2060)
    struct.pack_into("<II", data, 0x440, 0x1000, 0x2080)
    struct.pack_into("<I", data, 0x450, 0x2070)
    struct.pack_into("<H", data, 0x460, 0)
    data[0x470:0x478] = b"example\0"
    data[0x480:0x493] = b"KERNEL32.Sleep\0\0\0\0\0"
    image = PELoader().load(bytes(data))
    assert image.exports[0]["names"] == ["example"]
    assert image.exports[1]["forwarder"] == "KERNEL32.Sleep"
    assert image.exports[1]["address"] is None


def test_runtime_ranges_and_malformed_directories():
    data = bytearray(pe())
    directory(data, 3, 0x2000, 12)
    struct.pack_into("<III", data, 0x400, 0x1000, 0x1001, 0x2020)
    data[0x420] = 1
    image = PELoader().load(bytes(data))
    assert image.runtime_functions == [(image.entry, image.entry + 1, image.image_base + 0x2020)]
    directory(data, 3, 0x2000, 13)
    with pytest.raises(AnalysisError):
        PELoader().load(bytes(data))
    directory(data, 3, 0x2FFF, 12)
    with pytest.raises(AnalysisError):
        PELoader().load(bytes(data))


def test_certificate_is_file_offset_and_limits():
    data = bytearray(pe())
    directory(data, 4, 0x700, 0x10)
    PELoader().load(bytes(data))
    with pytest.raises(AnalysisError, match="budget"):
        PELoader().load(bytes(data), Limits(max_file_bytes=100))
    with pytest.raises(AnalysisError):
        PELoader().load(bytes(data), Limits(max_sections=1))


def test_seeded_mutation_smoke_is_bounded_and_only_reports_analysis_errors():
    rng = random.Random(0xAC4E)
    original = pe()
    for _ in range(500):
        data = bytearray(original)
        for _ in range(rng.randint(1, 8)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        try:
            image = PELoader().load(bytes(data), Limits(max_directory_entries=128))
            assert len(image.sections) <= 96
        except AnalysisError:
            pass
