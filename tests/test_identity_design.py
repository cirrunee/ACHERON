from pathlib import Path
import tomllib

from acheron.identity import ATTRIBUTION, DESCRIPTION, CREATOR


def test_canonical_first_party_attribution_and_third_party_separation():
    root = Path(__file__).resolve().parents[1]
    package = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert CREATOR == "cirrune"
    assert package["project"]["authors"] == [{"name": "cirrune"}]
    assert ATTRIBUTION in (root / "README.md").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 cirrune" in (root / "LICENSE").read_text()
    assert "CompanyName" not in (root / "tools/windows-version.txt").read_text(encoding="utf-8")
    notices = (root / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert "iced-x86" in notices and "LGPLv3" in notices
    assert "retain their respective owners" in notices
    assert (root / "docs/provenance/README.md").exists()


def test_shared_text_and_evidence_tokens_have_readable_contrast():
    import pytest
    pytest.importorskip("PySide6")
    from acheron.desktop.theme import COLORS

    def luminance(color):
        values = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
        values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
        return sum(v * factor for v, factor in zip(values, (.2126, .7152, .0722)))

    for role in ("text", "muted", "known", "inferred", "hypothesized", "unknown"):
        for surface in ("background", "surface", "code"):
            light, dark = sorted((luminance(COLORS[role]), luminance(COLORS[surface])), reverse=True)
            assert (light + .05) / (dark + .05) >= 4.5, (role, surface)
