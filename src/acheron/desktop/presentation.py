"""Presentation-only projections. Analysis artifacts and exports are unchanged."""
from dataclasses import dataclass
import re

from ..pseudocode import render_with_map

TRAILING_ADDRESS = re.compile(r"\s*/\* 0x[0-9a-f]+ \*/$")


def readable_pseudocode(function):
    text, source_map = render_with_map(function)
    # Remove only the fixed renderer preamble and duplicate source-address suffix.
    # The full exported reconstruction and its provenance remain intact.
    lines = text.splitlines()
    prefix = 3 if lines[:1] == ["/* ACHERON: reconstructed machine-state pseudocode; NOT original source."] else 0
    output = "\n".join(TRAILING_ADDRESS.sub("", line) for line in lines[prefix:])
    mapping = {address: [n - prefix for n in numbers if n > prefix] for address, numbers in source_map.items()}
    return output, mapping


def confidence_text(function):
    return f"INFERRED · entry evidence {round(function.confidence * 100)}/100"


def confidence_explanation(function):
    return ("This score describes the evidence for the candidate function entry.\n"
            "It is a heuristic ranking, not a probability or a correctness score for the pseudocode.\n"
            "Signature, types and source-level semantics may remain unknown.\n\n" +
            "\n".join(f"{e.source}: {e.confidence:.0%}" for e in function.evidence))


def human_progress(message):
    if message.startswith("Reading binary"):
        return "Reading file and checking the binary format"
    if message.startswith("Decoding "):
        return "Finding functions and decoding instructions"
    if message.startswith("Analyzing data flow"):
        return message.replace("Analyzing data flow", "Analyzing functions")
    if message == "Preparing analysis views":
        return "Preparing results for inspection"
    return message


@dataclass(frozen=True)
class Location:
    function: int
    address: int
    view: int
