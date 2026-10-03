"""Pocket Master firmware files ("HTFW"): inspection and UI language packs.

Nothing here talks to the device. Patched files are flashed with the official Sonicake Manager,
which only checks the 'HTFW' magic, the product name and the file size (see docs/FIRMWARE.md).

Language packs replace the device's second UI language (Chinese in the official firmware):
the CJK glyphs of its 8 bpp LVGL font are replaced by glyphs for the pack's characters
(data/glyphs.json, pixel art in the style of the font's Latin letters), and the second
language's string pointers are redirected to the translated strings, stored in the space the
CJK bitmaps freed. Section sizes never change; the section CRC is recomputed.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

HDR = 0x88
PTR_BASE = 0x10000          # pointers in section 'b' = section offset + 0x10000
SECTION_TYPES = {"c": "bootloader / ARM code", "g": "ARM code", "f": "cab IRs",
                 "b": "main application + UI", "e": "factory presets"}


# ------------------------------------------------------------------ container
def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def section_crc(data: bytes) -> int:
    """Value stored in the section table (byte-swapped CRC-16/MODBUS)."""
    c = crc16_modbus(data)
    return ((c & 0xFF) << 8) | (c >> 8)


@dataclass
class Section:
    index: int
    type: str
    address: int
    start: int          # file offset
    size: int
    crc: int
    entry: int          # file offset of the table entry


@dataclass
class Firmware:
    data: bytearray
    product: str
    version: str
    sections: list[Section] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "Firmware":
        return cls.parse(Path(path).expanduser().read_bytes())

    @classmethod
    def parse(cls, raw: bytes) -> "Firmware":
        if raw[:4] != b"HTFW" or len(raw) < HDR:
            raise ValueError("not a Pocket Master firmware file (no 'HTFW' header)")
        size = struct.unpack_from("<I", raw, 8)[0]
        if size != len(raw):
            raise ValueError(f"file size {len(raw)} does not match the header ({size})")
        v = raw[0x1C:0x20]
        fw = cls(bytearray(raw), raw[0x0C:0x1C].rstrip(b"\0").decode("ascii", "replace"),
                 f"{chr(v[0])}{v[1]}.{v[2]}.{v[3]}")
        for i in range(5):
            e = 0x38 + 16 * i
            ck, addr, off, sz = struct.unpack_from("<IIII", raw, e)
            if HDR + off + sz > len(raw):
                raise ValueError(f"section {i} lies outside the file")
            fw.sections.append(Section(i, chr(ck >> 24), addr, HDR + off, sz, ck & 0xFFFF, e))
        return fw

    def section(self, type_: str) -> Section:
        return next(s for s in self.sections if s.type == type_)

    def section_bytes(self, s: Section) -> bytes:
        return bytes(self.data[s.start:s.start + s.size])

    def info(self) -> dict[str, Any]:
        return {"product": self.product, "version": self.version, "size": len(self.data),
                "sections": [{"type": s.type, "content": SECTION_TYPES.get(s.type, "?"),
                              "flash_address": f"{s.address:#010x}", "size": s.size,
                              "crc_ok": section_crc(self.section_bytes(s)) == s.crc} for s in self.sections]}

    def fix_crc(self, s: Section) -> None:
        s.crc = section_crc(self.section_bytes(s))
        struct.pack_into("<H", self.data, s.entry, s.crc)


# ------------------------------------------------------------------ UI layout
def _cstr(d: bytes | bytearray, ptr: int) -> str | None:
    o = ptr - PTR_BASE
    if not 0 <= o < len(d):
        return None
    e = d.find(b"\0", o)
    try:
        return bytes(d[o:e]).decode("utf-8")
    except UnicodeDecodeError:
        return None


@dataclass
class UiLayout:
    """Two language blocks, each 4 lv_font_t pointers followed by n string pointers."""
    en: int
    second: int
    n: int

    @classmethod
    def find(cls, d: bytes | bytearray) -> "UiLayout":
        i = bytes(d).find(b"\0English\0")
        if i < 0:
            raise ValueError("UI string table not found ('English' missing)")
        en_str = bytes(d).find(struct.pack("<I", i + 1 + PTR_BASE))
        if en_str < 0:
            raise ValueError("language table not found")
        en = en_str - 16
        for n in range(20, 400):
            sec = en - (16 + 4 * n)
            if sec < 0:
                break
            if d[sec + 20:sec + 28] == d[en + 20:en + 28]:      # 'NR', 'FX1' pointers are shared
                return cls(en, sec, n)
        raise ValueError("second language block not found")

    def strings(self, d: bytes | bytearray, block: int) -> list[str | None]:
        return [_cstr(d, struct.unpack_from("<I", d, block + 16 + 4 * k)[0]) for k in range(self.n)]

    def font(self, d: bytes | bytearray, block: int, k: int = 0) -> int:
        return struct.unpack_from("<I", d, block + 4 * k)[0] - PTR_BASE


@dataclass
class LvFont:
    dsc: int
    bitmap: int
    glyph_dsc: int
    cmaps: int
    bpp: int
    cmap_num: int

    @classmethod
    def at(cls, d: bytes | bytearray, font: int) -> "LvFont":
        dsc = struct.unpack_from("<I", d, font + 16)[0] - PTR_BASE
        gb, gd, cm = (x - PTR_BASE for x in struct.unpack_from("<III", d, dsc))
        bits = struct.unpack_from("<H", d, dsc + 18)[0]
        return cls(dsc, gb, gd, cm, (bits >> 9) & 0xF, bits & 0x1FF)

    def cmap(self, d, k):
        rs, rl, gs, ul, go, ll, ty = struct.unpack_from("<IHHIIHB", d, self.cmaps + 20 * k)
        lst = list(struct.unpack_from(f"<{ll}H", d, ul - PTR_BASE)) if ul else None
        return {"at": self.cmaps + 20 * k, "start": rs, "length": rl, "glyph_start": gs,
                "list_at": ul - PTR_BASE if ul else None, "list": lst, "type": ty}

    def glyph(self, d, gid):
        raw = struct.unpack_from("<I", d, self.glyph_dsc + 8 * gid)[0]
        w, h, ox, oy = struct.unpack_from("<BBbb", d, self.glyph_dsc + 8 * gid + 4)
        return {"index": raw & 0xFFFFF, "adv": raw >> 20, "w": w, "h": h, "ox": ox, "oy": oy}

    def glyph_id(self, d, cp: int) -> int | None:
        for k in range(self.cmap_num):
            c = self.cmap(d, k)
            if c["start"] <= cp < c["start"] + c["length"]:
                off = cp - c["start"]
                if c["list"] is None:
                    return c["glyph_start"] + off
                if off in c["list"]:
                    return c["glyph_start"] + c["list"].index(off)
        return None

    def chars(self, d) -> str:
        out = []
        for k in range(self.cmap_num):
            c = self.cmap(d, k)
            if c["list"] is None:
                out += [chr(c["start"] + i) for i in range(c["length"])]
            else:
                out += [chr(c["start"] + i) for i in c["list"]]
        return "".join(out)


# ------------------------------------------------------------------ packs
def _data(name: str) -> Any:
    return json.loads(resources.files(__package__).joinpath("data", name).read_text(encoding="utf-8"))


def builtin_packs() -> dict[str, dict[str, Any]]:
    d = resources.files(__package__).joinpath("data", "languages")
    return {p.name[:-5]: json.loads(p.read_text(encoding="utf-8")) for p in d.iterdir() if p.name.endswith(".json")}


def load_pack(pack: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(pack, dict):
        return pack
    packs = builtin_packs()
    if pack in packs:
        return packs[pack]
    p = Path(pack).expanduser()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    raise ValueError(f"unknown language pack '{pack}'. Built-in: {', '.join(packs)} (or a path to a .json file)")


def glyph_library() -> dict[str, Any]:
    return _data("glyphs.json")["glyphs"]


# ------------------------------------------------------------------ inspect / build
def ui_strings(fw: Firmware) -> list[dict[str, Any]]:
    s = fw.section("b")
    d = fw.data[s.start:s.start + s.size]
    lay = UiLayout.find(d)
    en, sec = lay.strings(d, lay.en), lay.strings(d, lay.second)
    return [{"index": k, "english": en[k], "second": sec[k]} for k in range(lay.n)]


def second_language(fw: Firmware) -> dict[str, Any]:
    s = fw.section("b")
    d = fw.data[s.start:s.start + s.size]
    lay = UiLayout.find(d)
    font = LvFont.at(d, lay.font(d, lay.second))
    chars = font.chars(d)
    extra = "".join(c for c in chars if ord(c) > 0x7E)
    cjk = sum(1 for c in extra if 0x4E00 <= ord(c) <= 0x9FFF)
    return {"name": lay.strings(d, lay.second)[0], "string_count": lay.n,
            "font_extra_characters": extra, "official": cjk > 0 and not any(0x400 <= ord(c) < 0x500 for c in extra)}


def build_language(src: bytes, pack: str | dict[str, Any],
                   overrides: dict[str, str] | None = None) -> tuple[bytes, dict[str, Any]]:
    """Return (patched firmware, report). `src` must be an official (unpatched) firmware."""
    pack = load_pack(pack)
    tr: dict[str, str] = dict(pack.get("strings", {}))
    tr.update(overrides or {})
    fw = Firmware.parse(src)
    sec = fw.section("b")
    d = bytearray(fw.section_bytes(sec))
    lay = UiLayout.find(d)
    font_at = lay.font(d, lay.second)
    f = LvFont.at(d, font_at)
    if f.bpp != 8 or f.cmap_num != 2:
        raise ValueError(f"unexpected second-language font (bpp {f.bpp}, {f.cmap_num} cmaps)")
    c1 = f.cmap(d, 1)
    if c1["type"] != 3 or not c1["list"]:
        raise ValueError("unexpected font cmap")
    old = [chr(c1["start"] + x) for x in c1["list"]]
    if not any(0x4E00 <= ord(c) <= 0x9FFF for c in old):
        raise ValueError("this firmware is already patched; build from the official file")
    gs, ll = c1["glyph_start"], len(c1["list"])

    en = lay.strings(d, lay.en)
    unknown = sorted(k for k in tr if k not in en)
    target = [tr.get(e, e) if e is not None else None for e in en]

    # characters needed outside the font's ASCII range
    need = sorted({c for t in target if t for c in t if ord(c) > 0x7E and c != "\n"})
    lib = glyph_library()
    missing = [c for c in need if c not in old and c not in lib]
    if missing:
        raise ValueError(f"no glyphs for: {''.join(missing)} — add them to data/glyphs.json")
    new_chars = sorted(set(need) | {c for c in old if c == "©"})
    if len(new_chars) > ll:
        raise ValueError(f"{len(new_chars)} glyphs needed, the font has room for {ll}")

    # bitmap region of the old non-ASCII glyphs
    gls = [f.glyph(d, g) for g in range(gs, gs + ll)]
    lo = min(g["index"] for g in gls)
    hi = max(g["index"] + g["w"] * g["h"] for g in gls)

    def latin(ch):
        g = f.glyph(d, ord(ch) - 0x20 + 1)
        return bytes(d[f.bitmap + g["index"]:f.bitmap + g["index"] + g["w"] * g["h"]]), g

    entries = []
    for ch in new_chars:
        if ch in old and ch not in lib:
            g = f.glyph(d, gs + old.index(ch))
            bm = bytes(d[f.bitmap + g["index"]:f.bitmap + g["index"] + g["w"] * g["h"]])
            entries.append((ch, bm, g["adv"], g["w"], g["h"], g["ox"], g["oy"]))
            continue
        spec = lib[ch]
        if isinstance(spec, str):
            bm, g = latin(spec[1])
            entries.append((ch, bm, g["adv"], g["w"], g["h"], g["ox"], g["oy"]))
        else:
            rows = spec["rows"]
            w = len(rows[0])
            if any(len(r) != w for r in rows):
                raise ValueError(f"glyph {ch!r}: rows of different width")
            bm = bytes(255 if c == "#" else 0 for r in rows for c in r)
            entries.append((ch, bm, int(spec.get("adv", 6) * 16), w, len(rows), spec.get("ox", 0), spec.get("oy", 0)))

    d[f.bitmap + lo:f.bitmap + hi] = bytes(hi - lo)
    pos = lo
    for k, (ch, bm, adv, w, h, ox, oy) in enumerate(entries):
        d[f.bitmap + pos:f.bitmap + pos + len(bm)] = bm
        struct.pack_into("<IBBbb", d, f.glyph_dsc + 8 * (gs + k), (pos & 0xFFFFF) | (adv << 20), w, h, ox, oy)
        pos += len(bm)
    for k in range(len(entries), ll):
        struct.pack_into("<IBBbb", d, f.glyph_dsc + 8 * (gs + k), 0, 0, 0, 0, 0)
    start = min(ord(e[0]) for e in entries)
    offs = [ord(e[0]) - start for e in entries]
    struct.pack_into(f"<{ll}H", d, c1["list_at"], *(offs + [0] * (ll - len(offs))))
    struct.pack_into("<IHHIIHB", d, c1["at"], start, offs[-1] + 1, gs, c1["list_at"] + PTR_BASE, 0, len(offs), 3)
    glyph_bytes = pos - lo

    # strings
    pos = (pos + 3) & ~3
    placed: dict[str, int] = {}
    for k, t in enumerate(target):
        if t is None:
            continue
        if t == en[k]:                    # untranslated: share the English string
            struct.pack_into("<I", d, lay.second + 16 + 4 * k, struct.unpack_from("<I", d, lay.en + 16 + 4 * k)[0])
            continue
        if t not in placed:
            raw = t.encode("utf-8") + b"\0"
            if pos + len(raw) > hi:
                raise ValueError("translations too long: not enough free space in the font area")
            d[f.bitmap + pos:f.bitmap + pos + len(raw)] = raw
            placed[t] = f.bitmap + pos
            pos = (pos + len(raw) + 3) & ~3
        struct.pack_into("<I", d, lay.second + 16 + 4 * k, placed[t] + PTR_BASE)

    fw.data[sec.start:sec.start + sec.size] = d
    fw.fix_crc(sec)
    out = bytes(fw.data)
    check = verify_language(out, target)
    longer = [{"english": e, "translation": t} for e, t in zip(en, target)
              if e and t and max(map(len, t.split("\n"))) > max(map(len, e.split("\n"))) + 2]
    report = {"source_version": fw.version, "language": target[0], "strings": lay.n,
              "translated": sum(1 for e in en if e in tr), "untranslated_kept_english":
              sorted({e for e in en if e and e not in tr and any(c.isalpha() for c in e)} - {"NR", "FX1", "FX2", "DRV",
                     "AMP", "IR", "EQ", "DLY", "RVB", "VOL", "BT", "USB", "dB", "P01", "MOVE", "Preset VOL"}),
              "unknown_keys": unknown, "glyphs": "".join(e[0] for e in entries),
              "font_area": {"glyph_bytes": glyph_bytes, "string_bytes": pos - glyph_bytes - lo, "free": hi - pos},
              "longer_than_english": longer, "verified": check}
    return out, report


def verify_language(raw: bytes, expected: list[str | None] | None = None) -> bool:
    """Re-read a patched file: CRCs, strings, and a glyph for every character of the second language."""
    fw = Firmware.parse(raw)
    if not all(section_crc(fw.section_bytes(s)) == s.crc for s in fw.sections):
        return False
    s = fw.section("b")
    d = fw.data[s.start:s.start + s.size]
    lay = UiLayout.find(d)
    got = lay.strings(d, lay.second)
    if expected is not None and got != expected:
        return False
    f = LvFont.at(d, lay.font(d, lay.second))
    return all(f.glyph_id(d, ord(c)) is not None for t in got if t for c in t if c != "\n")


def render_strings(raw: bytes, path: str | Path, scale: int = 3) -> Path:
    """PNG preview of the second language's strings, drawn from the file's own font."""
    import numpy as np
    from PIL import Image
    fw = Firmware.parse(raw)
    s = fw.section("b")
    d = bytes(fw.data[s.start:s.start + s.size])
    lay = UiLayout.find(d)
    fa = lay.font(d, lay.second)
    f = LvFont.at(d, fa)
    lh, bl = struct.unpack_from("<hh", d, fa + 8)
    seen, items = set(), []
    for t in lay.strings(d, lay.second):
        if t and t not in seen:
            seen.add(t)
            items.append(t)
    rows = []
    for t in items:
        lines = t.split("\n")
        img = np.zeros((lh * len(lines) + 3, max(len(x) for x in lines) * 7 + 6), np.uint8)
        for li, line in enumerate(lines):
            x = 2
            for ch in line:
                gid = f.glyph_id(d, ord(ch))
                if gid is None:
                    img[1 + li * lh:1 + li * lh + 8, x:x + 5] = 90
                    x += 6
                    continue
                g = f.glyph(d, gid)
                if g["w"] and g["h"]:
                    bm = np.frombuffer(d[f.bitmap + g["index"]:f.bitmap + g["index"] + g["w"] * g["h"]],
                                       np.uint8).reshape(g["h"], g["w"])
                    top = 1 + li * lh + lh - bl - g["oy"] - g["h"]
                    if top >= 0:
                        img[top:top + g["h"], x + g["ox"]:x + g["ox"] + g["w"]] |= bm
                x += round(g["adv"] / 16)
        rows.append(img)
    width = max(r.shape[1] for r in rows)
    sheet = np.vstack([np.pad(r, ((0, 1), (0, width - r.shape[1]))) for r in rows])
    out = Path(path).expanduser()
    Image.fromarray(sheet).resize((sheet.shape[1] * scale, sheet.shape[0] * scale), Image.NEAREST).save(out)
    return out
