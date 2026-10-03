"""Wire format of the Sonicake Pocket Master SysEx protocol (USB MIDI / BLE MIDI).

Every message is ``F0 <body> F7``. The body is a *logical* frame in which every byte is sent
nibble-expanded (``0xAB`` -> ``0x0A 0x0B``), so all transmitted bytes stay below 0x80:

    logical frame = [crc, total, index, length, payload[length]]

* ``crc``    CRC-8/SMBus (poly 0x07, init 0) over ``total .. payload`` (logical bytes)
* ``total``  number of packets of a multi-packet response (1 for normal messages)
* ``index``  0-based packet number
* ``length`` number of payload bytes in this packet

Payloads start with a 2-byte header. The high nibble of the first byte looks like a version
(always 1), the low nibble is the direction: 1 = set (host -> device), 2 = get / state report,
4 = acknowledge. The second byte is the command. Multi-byte integers are little-endian,
parameter values are IEEE-754 float32.

Everything here was cross-checked against the ~7400 captured commands in PocketEdit's
command library (tests/test_protocol.py rebuilds all of them byte for byte).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

# --- payload header -------------------------------------------------------
SET = 0x11
GET = 0x12
ACK = 0x14

CMD_GLOBAL = 0x11         # global setting (group, sub-id, int32 value)
CMD_PRESET_VOLUME = 0x42  # volume of the current preset
CMD_SELECT = 0x43         # load preset by index (0-49 user, 50-99 factory)
CMD_CHAIN = 0x44          # signal chain order
CMD_EFFECT = 0x47         # select effect model in a module
CMD_PARAM = 0x48          # set a parameter (float32)
CMD_STATE = 0x49          # module on/off; module 9 = amp mode (0 normal amp, 1 clone)
CMD_SAVE = 0x4A           # save the edit buffer to a user slot with a name
CMD_ACK = 0x08

# query kinds (payload [GET, kind])
Q_GLOBALS = 0x10
Q_IR_NAMES = 0x20
Q_CLONE_NAMES = 0x24
Q_PRESET_NAMES = 0x40
Q_CURRENT_DUMP = 0x41
Q_CURRENT_INDEX = 0x43
Q_MODIFIED = 0x45

# --- modules ---------------------------------------------------------------
MODULES = ["NR", "FX1", "DRV", "AMP", "IR", "EQ", "FX2", "DLY", "RVB"]
CLONE_MODULE = 9          # captured-amp ("clone") profiles; shares the AMP slot
AMP_MODE_MODULE = 9       # CMD_STATE on module 9 switches normal amp <-> clone
FIXED_BLOCK = [2, 3, 4, 5]  # DRV-AMP-IR-EQ always stay together in this order

USER_PRESETS = 50
FACTORY_PRESETS = 50
PRESET_COUNT = USER_PRESETS + FACTORY_PRESETS
NAME_LEN = 10

# --- edit-buffer dump (reply to Q_CURRENT_DUMP) ---------------------------------
# Payload: 12 41, uint16 0x00ff, uint16 header length, header records, then groups.
# A record is uint16 tag, uint16 length, data; groups contain records. Known tags:
T_STATES = 0x3001         # uint32 bit mask: bit m = module m on, bit 9 = captured-amp mode
T_CHAIN = 0x3002          # 9 module ids in chain order + 0x09
T_EFFECTS = 0x3003        # 10 x uint32 effect code (modules 0..9)
T_PARAMS = 0x3004         # 10 modules x 8 x float32
T_VOLUME = 0x2001         # uint32 preset volume
T_TEMPO = 0x2002          # uint32, 120 in a default preset - probably tempo (BPM), unconfirmed
PARAM_STRIDE = 32
# absolute offsets of the same data in a standard dump (fallback)
DUMP_EFFECT_BASE = 100
DUMP_PARAM_BASE = 144
DUMP_PARAM_STRIDE = PARAM_STRIDE


def crc8(data: bytes | list[int]) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def expand(data: bytes | list[int]) -> list[int]:
    out: list[int] = []
    for b in data:
        out += [(b >> 4) & 0x0F, b & 0x0F]
    return out


def collapse(data: bytes | list[int]) -> bytes:
    if len(data) % 2:
        raise ValueError("nibble-expanded data must have an even length")
    if any(b > 0x0F for b in data):
        raise ValueError("not nibble-expanded data")
    return bytes((data[i] << 4) | data[i + 1] for i in range(0, len(data), 2))


def u32(v: int) -> list[int]:
    return list(struct.pack("<I", v & 0xFFFFFFFF))


def i32(v: int) -> list[int]:
    return list(struct.pack("<i", int(v)))


def f32(v: float) -> list[int]:
    return list(struct.pack("<f", float(v)))


def build(payload: list[int], total: int = 1, index: int = 0) -> list[int]:
    """SysEx data bytes (without F0/F7) for a payload."""
    if len(payload) > 255:
        raise ValueError("payload too long for one packet")
    body = [total, index, len(payload)] + list(payload)
    return expand([crc8(body)] + body)


@dataclass
class Frame:
    total: int
    index: int
    payload: bytes
    crc_ok: bool

    @property
    def kind(self) -> tuple[int, int] | None:
        return (self.payload[0], self.payload[1]) if len(self.payload) >= 2 else None

    @property
    def command(self) -> int | None:
        return self.payload[1] if len(self.payload) >= 2 else None


def parse_frame(data: bytes | list[int]) -> Frame:
    """Parse SysEx data (without F0/F7)."""
    b = collapse(list(data))
    if len(b) < 4:
        raise ValueError("frame too short")
    total, index, length = b[1], b[2], b[3]
    payload = b[4:]
    ok = crc8(b[1:]) == b[0] and length == len(payload)
    return Frame(total, index, bytes(payload), ok)


def hex_to_sysex_data(h: str) -> list[int]:
    """'8080F0....F7' (PocketEdit/BLE notation) -> SysEx data without F0/F7."""
    raw = bytes.fromhex(h.replace(" ", ""))
    if raw[:2] == b"\x80\x80":   # BLE-MIDI timestamp header
        raw = raw[2:]
    if raw[:1] == b"\xf0":
        raw = raw[1:]
    if raw[-1:] == b"\xf7":
        raw = raw[:-1]
    return list(raw)


# --- command builders --------------------------------------------------------
def query(kind: int) -> list[int]:
    return build([GET, kind])


def select_preset(index: int) -> list[int]:
    if not 0 <= index < PRESET_COUNT:
        raise ValueError(f"preset index must be 0..{PRESET_COUNT - 1}")
    return build([SET, CMD_SELECT] + u32(index))


def module_state(module: int, on: bool) -> list[int]:
    return build([SET, CMD_STATE] + u32(module) + u32(1 if on else 0))


def amp_mode(clone: bool) -> list[int]:
    return module_state(AMP_MODE_MODULE, clone)


def select_effect(module: int, code: int) -> list[int]:
    return build([SET, CMD_EFFECT] + u32(module) + u32(module) + u32(code))


def set_param(module: int, alg: int, value: float) -> list[int]:
    return build([SET, CMD_PARAM] + u32(module) + u32(alg) + f32(value))


def set_chain(order: list[int]) -> list[int]:
    validate_chain(order)
    return build([SET, CMD_CHAIN] + list(order) + [AMP_MODE_MODULE])


def preset_volume(value: int) -> list[int]:
    if not 0 <= int(value) <= 100:
        raise ValueError("preset volume must be 0..100")
    return build([SET, CMD_PRESET_VOLUME, 0x01, 0x20, 0x01, 0x00, int(value)])


GLOBALS = {  # name: (group, sub-id, min, max)
    "global_volume": (2, 2, 0, 100),
    "input_level": (1, 3, -20, 20),
    "fx_rec_level": (1, 4, -20, 20),
    "monitor_level": (2, 4, -20, 20),
    "bt_rec_level": (5, 4, -20, 20),
}


def set_global(name: str, value: int) -> list[int]:
    if name not in GLOBALS:
        raise ValueError(f"unknown global setting '{name}'. Known: {', '.join(GLOBALS)}")
    group, sub, lo, hi = GLOBALS[name]
    if not lo <= int(value) <= hi:
        raise ValueError(f"{name} must be {lo}..{hi}")
    return build([SET, CMD_GLOBAL, group, sub, 0, 0] + i32(int(value)))


def encode_name(name: str) -> list[int]:
    if not name or len(name) > NAME_LEN:
        raise ValueError(f"preset names are 1..{NAME_LEN} characters")
    if any(not 0x20 <= ord(c) <= 0x7E for c in name):
        raise ValueError("preset names must be plain ASCII (letters, digits, punctuation)")
    return [ord(c) for c in name] + [0] * (NAME_LEN - len(name))


def save_preset(index: int, name: str) -> list[int]:
    if not 0 <= index < USER_PRESETS:
        raise ValueError(f"only user presets P01..P{USER_PRESETS:02d} can be written")
    return build([SET, CMD_SAVE] + u32(index) + encode_name(name) + [0, 0, 0])


def validate_chain(order: list[int]) -> None:
    if sorted(order) != list(range(9)):
        raise ValueError("chain must contain each of the 9 modules exactly once")
    i = order.index(FIXED_BLOCK[0])
    if order[i:i + 4] != FIXED_BLOCK:
        raise ValueError("DRV, AMP, IR and EQ form a fixed block and must stay together in this order")


# --- preset labels -------------------------------------------------------------
def preset_label(index: int) -> str:
    return f"P{index + 1:02d}" if index < USER_PRESETS else f"F{index - USER_PRESETS + 1:02d}"


def preset_index(label: int | str) -> int:
    """'P07' / 'F03' / 'p7' / 6 (0-based index) -> index 0..99."""
    s = str(label).strip().upper()
    if s[:1] in ("P", "U") and s[1:].isdigit():
        n = int(s[1:])
        if 1 <= n <= USER_PRESETS:
            return n - 1
    elif s[:1] == "F" and s[1:].isdigit():
        n = int(s[1:])
        if 1 <= n <= FACTORY_PRESETS:
            return USER_PRESETS + n - 1
    elif s.isdigit() and 0 <= int(s) < PRESET_COUNT:
        return int(s)
    raise ValueError(f"bad preset '{label}': use P01..P50 (user), F01..F50 (factory) or index 0..99")


# --- decoding --------------------------------------------------------------------
def decode_name(b: bytes) -> str:
    out = []
    for c in b[:NAME_LEN]:
        if c == 0:
            break
        out.append(chr(c) if 0x20 <= c <= 0x7E else "?")
    return "".join(out).rstrip()


def _is_name_block(b: bytes) -> bool:
    if len(b) != NAME_LEN or b[0] == 0:
        return False
    pad = False
    for c in b:
        if pad:
            if c != 0:
                return False
        elif c == 0:
            pad = True
        elif not 0x20 <= c <= 0x7E:
            return False
    return True


def scan_names(payload: bytes) -> list[tuple[int, str]]:
    """Find 10-byte ASCII name blocks (zero padded) in a payload: [(offset, name)]."""
    out, i = [], 0
    while i + NAME_LEN <= len(payload):
        block = payload[i:i + NAME_LEN]
        if _is_name_block(block):
            out.append((i, decode_name(block)))
            i += NAME_LEN
        else:
            i += 1
    return out


NAME_RECORD = 20          # preset-name dump: [GET, 0x40], then records of uint32 slot + 16-byte name


def preset_name_records(payload: bytes) -> dict[int, str]:
    """Decode the reply to Q_PRESET_NAMES: {slot index: name}. Incomplete records are skipped."""
    out: dict[int, str] = {}
    start = 2 if payload[:2] == bytes([GET, Q_PRESET_NAMES]) else 0
    for o in range(start, len(payload) - NAME_RECORD + 1, NAME_RECORD):
        idx = struct.unpack_from("<I", payload, o)[0]
        if idx >= PRESET_COUNT:
            break
        out[idx] = decode_name(payload[o + 4:o + NAME_RECORD])
    return out


def slot_names(payload: bytes, count: int = 5) -> list[str]:
    """Names of user IR / clone slots: 10-byte names in 16-byte records after a 7-byte header."""
    return [decode_name(payload[7 + 16 * i: 17 + 16 * i]) for i in range(count)
            if len(payload) >= 17 + 16 * i]


def parse_records(buf: bytes, start: int, end: int) -> list[tuple[int, int, bytes]]:
    """[(offset, tag, data)] for consecutive uint16 tag / uint16 length records."""
    out, o = [], start
    while o + 4 <= end:
        tag, ln = struct.unpack_from("<HH", buf, o)
        if o + 4 + ln > end:
            break
        out.append((o, tag, bytes(buf[o + 4:o + 4 + ln])))
        o += 4 + ln
    return out


def parse_dump(payload: bytes) -> dict[int, bytes]:
    """Flatten the dump into {tag: data}. Header records get tags 0xF000 | tag."""
    if payload[:2] != bytes([GET, Q_CURRENT_DUMP]) or len(payload) < 6:
        raise ValueError("not an edit-buffer dump")
    hdr_len = struct.unpack_from("<H", payload, 4)[0]
    tags = {0xF000 | t: d for _, t, d in parse_records(payload, 6, 6 + hdr_len)}
    for _, _, group in parse_records(payload, 6 + hdr_len, len(payload)):
        for _, t, d in parse_records(group, 0, len(group)):
            tags[t] = d
    return tags


def dump_fields(payload: bytes) -> dict[str, object]:
    """Decode the known parts of a dump: codes, params(module, alg) -> float, mask, chain, volume."""
    t = parse_dump(payload)
    out: dict[str, object] = {"tags": t}
    if T_EFFECTS in t:
        out["codes"] = list(struct.unpack_from(f"<{len(t[T_EFFECTS]) // 4}I", t[T_EFFECTS]))
    if T_PARAMS in t:
        out["params"] = t[T_PARAMS]
    if T_STATES in t:
        out["mask"] = struct.unpack_from("<I", t[T_STATES])[0]
    if T_CHAIN in t and sorted(t[T_CHAIN][:9]) == list(range(9)):
        out["chain"] = list(t[T_CHAIN][:9])
    if T_VOLUME in t:
        out["volume"] = struct.unpack_from("<I", t[T_VOLUME])[0]
    if T_TEMPO in t:
        out["tempo"] = struct.unpack_from("<I", t[T_TEMPO])[0]
    return out


def param_from_block(block: bytes, module: int, alg: int) -> float | None:
    o = PARAM_STRIDE * module + 4 * alg
    return struct.unpack_from("<f", block, o)[0] if len(block) >= o + 4 else None
