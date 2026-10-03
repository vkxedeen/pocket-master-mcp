"""Firmware tools. The official firmware is not part of the repository: tests that need it run
when PM_TEST_FIRMWARE points to "Pocket Master Firmware V1.3.3.bin" (or the file is in local/)."""
import os
from pathlib import Path

import pytest

from pocket_master_mcp import firmware as F

ROOT = Path(__file__).resolve().parents[1]


def _official():
    cands = [os.environ.get("PM_TEST_FIRMWARE", "")] + [str(p) for p in sorted((ROOT / "local").glob("Pocket Master Firmware V*.bin"))]
    for c in cands:
        if c and Path(c).exists():
            fw = F.Firmware.load(c)
            if F.second_language(fw)["official"]:
                return Path(c)
    return None


FIRMWARE = _official()
needs_fw = pytest.mark.skipif(FIRMWARE is None, reason="official firmware file not available")


def test_crc16_modbus():
    assert F.crc16_modbus(b"123456789") == 0x4B37
    assert F.section_crc(b"123456789") == 0x374B


def test_glyph_library_is_consistent():
    lib = F.glyph_library()
    for ch, spec in lib.items():
        if isinstance(spec, str):
            assert spec.startswith("=") and 0x20 < ord(spec[1]) < 0x7F, ch
        else:
            rows = spec["rows"]
            assert len({len(r) for r in rows}) == 1 and set("".join(rows)) <= {"#", "."}, ch
            assert len(rows) - max(0, -spec.get("oy", 0)) <= 9, f"{ch} too tall for line height 11"


def test_builtin_russian_pack_has_glyphs():
    pack = F.load_pack("ru")
    lib = F.glyph_library()
    chars = {c for t in pack["strings"].values() for c in t if ord(c) > 0x7E}
    assert chars - set(lib) <= {"©"}


def test_rejects_non_firmware():
    with pytest.raises(ValueError):
        F.Firmware.parse(b"not a firmware" * 20)


@needs_fw
def test_build_russian(tmp_path):
    raw = FIRMWARE.read_bytes()
    out, rep = F.build_language(raw, "ru")
    assert rep["verified"] and rep["language"] == "Русский"
    if rep["source_version"] == "V1.3.3":
        assert not rep["unknown_keys"]          # older versions lack some newer strings
    assert len(out) == len(raw)
    fw = F.Firmware.parse(out)
    assert all(s["crc_ok"] for s in fw.info()["sections"])
    strings = {s["english"]: s["second"] for s in F.ui_strings(fw)}
    assert strings["Settings"] == "Настройки" and strings["NR"] == "NR"
    # only section 'b' changes
    a, b = F.Firmware.parse(raw), fw
    for sa, sb in zip(a.sections, b.sections):
        if sa.type != "b":
            assert a.section_bytes(sa) == b.section_bytes(sb)
    with pytest.raises(ValueError):
        F.build_language(out, "ru")          # already patched
    assert F.render_strings(out, tmp_path / "p.png").stat().st_size > 1000


@needs_fw
def test_overrides_and_missing_glyph():
    raw = FIRMWARE.read_bytes()
    out, rep = F.build_language(raw, "ru", {"Save": "Сохр."})
    assert {s["english"]: s["second"] for s in F.ui_strings(F.Firmware.parse(out))}["Save"] == "Сохр."
    with pytest.raises(ValueError, match="no glyphs"):
        F.build_language(raw, {"name": "Ελληνικά", "strings": {"English": "Ελληνικά"}})
