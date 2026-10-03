"""MCP server exposing a Sonicake Pocket Master over USB MIDI.

Run with `pocket-master-mcp` (stdio transport). Environment variables:
  PM_PORT         substring of the MIDI port name (default: auto-detect)
  PM_DATA_DIR     where backups, preset files and logs are stored (default ~/.pocket-master-mcp)
  PM_DEVICE_MAP   path to a custom device_map.json
  PM_DEBUG_TOOLS  "1" to expose low-level tools (raw SysEx, MIDI monitor, raw dumps)
"""
from __future__ import annotations

import functools
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # mcp 2.x renamed FastMCP
    from mcp.server.mcpserver import MCPServer as FastMCP  # type: ignore

from . import firmware as FW
from . import protocol as P
from .device import PocketMaster, data_dir

# stdout carries the MCP protocol, so logs go to stderr only.
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("pocket_master_mcp")

dev = PocketMaster()
mcp = FastMCP("pocket-master")
DEBUG = os.environ.get("PM_DEBUG_TOOLS") == "1"


def tool(debug: bool = False):
    """Register an MCP tool that returns errors as text instead of raising."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*a, **kw):
            try:
                return f(*a, **kw)
            except Exception as e:  # noqa: BLE001
                log.exception("tool %s failed", f.__name__)
                return f"ERROR: {e}"
        if debug and not DEBUG:
            return wrapper
        return mcp.tool()(wrapper)
    return deco


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


def _safe_filename(s: str) -> str:
    return re.sub(r"[^\w\-]+", "_", s).strip("_") or "unnamed"


def _subdir(name: str) -> Path:
    d = data_dir() / name
    d.mkdir(exist_ok=True)
    return d


def _user_slot(preset: int | str) -> int:
    idx = P.preset_index(preset)
    if idx >= P.USER_PRESETS:
        raise ValueError("factory presets (F01..F50) are read-only; save to a user slot P01..P50")
    return idx


# ---------------------------------------------------------------- connection
@tool()
def list_midi_ports() -> str:
    """List MIDI ports on this computer (to find the Pocket Master)."""
    return _dump(dev.list_ports())


@tool()
def connect(port_hint: str = "") -> str:
    """Connect to the Pocket Master. port_hint: part of the MIDI port name (empty = auto-detect)."""
    name = dev.connect(port_hint or None)
    cur = P.preset_label(dev.current) if dev.current is not None else "unknown"
    return f"connected to {name}, current preset {cur}"


@tool()
def device_state() -> str:
    """Read the edit buffer from the device: current preset, chain order, amp mode, and for every
    block its model, on/off state and parameter values (includes unsaved edits)."""
    st = dev.refresh()
    if dev.modified is not None:
        st["unsaved_changes"] = dev.modified
    return _dump(st)


@tool()
def list_models(block: str = "") -> str:
    """List models (and their parameters with ranges) for a block, or the model names of all blocks.
    Blocks: nr (gate), fx1, drv (drive), amp, ir (cab), eq, fx2, dly (delay), rvb (reverb).
    Captured-amp profiles ('User Profile 1..5') are listed under amp."""
    if not block:
        return _dump({k: [m["name"] for m in v] for k, v in dev.map["models"].items()})
    b = dev.block(block)
    pools = [b["key"]] + (["clone"] if b["key"] == "amp" else [])
    rows = {}
    for pool in pools:
        for m in dev.models(pool):
            rows[m["name"]] = {p["name"]: (p["options"] if p.get("type") == "select" else
                                           "on/off" if p.get("type") == "switch" else
                                           f"{p['min']}..{p['max']}{' ' + p['unit'] if p.get('unit') else ''}")
                               for p in m["params"]}
    return _dump(rows)


# ------------------------------------------------------------- live editing
@tool()
def set_model(block: str, model: str, on: bool = True) -> str:
    """Select a model in a block by name (e.g. amp "Brit 800", drv "Scream", ir "BritGN 4x12",
    dly "Analog", rvb "Plate 1"; amp also accepts captured profiles "User Profile 1..5").
    Selecting a model resets its parameters to the model defaults, so set parameters afterwards."""
    return dev.set_model(block, model, on)


@tool()
def set_block(block: str, on: bool) -> str:
    """Turn a block on or off, keeping its model."""
    return dev.set_block(block, on)


@tool()
def set_param(block: str, param: str, value: float | int | str | bool) -> str:
    """Set a parameter of the block's current model, e.g. ("amp", "Gain", 65), ("dly", "Time", 420),
    ("fx1", "Mode", "Bass"), ("fx1", "+3dB", "on"). Use list_models to see parameter names/ranges."""
    return dev.set_param(block, param, value)


@tool()
def set_chain(order: list[str]) -> str:
    """Set the signal chain order. All 9 modules, with DRV-AMP-IR-EQ kept together in this order,
    e.g. ["nr", "fx1", "drv", "amp", "ir", "eq", "fx2", "dly", "rvb"]."""
    return dev.set_chain(order)


@tool()
def set_preset_volume(value: int) -> str:
    """Volume of the current preset, 0..100."""
    return dev.set_preset_volume(value)


@tool()
def set_global(setting: str, value: int) -> str:
    """Global (not per-preset) setting: global_volume 0..100, input_level / fx_rec_level /
    monitor_level / bt_rec_level -20..20 dB."""
    dev.send(P.set_global(setting, value))
    return f"{setting} = {value}"


@tool()
def apply_preset(spec: dict[str, Any]) -> str:
    """Apply a whole tone to the edit buffer in one call (nothing is saved). Format:
    {"chain": ["nr","fx1","drv","amp","ir","eq","fx2","dly","rvb"],          (optional)
     "blocks": {
        "nr":  {"on": true, "params": {"THRE": 40}},
        "drv": {"model": "Scream", "params": {"Gain": 20, "Tone": 55, "Vol": 70}},
        "amp": {"model": "Brit 800", "params": {"Gain": 70, "Middle": 60}},
        "ir":  {"model": "BritGN 4x12"},
        "fx1": {"on": false},
        "dly": {"model": "Analog", "params": {"Mix": 18, "Time": 380}},
        "rvb": {"model": "Plate 1", "params": {"Mix": 20}}},
     "preset_volume": 70}                                                  (optional)
    Per block: model first (resets params to defaults), then on/off, then params."""
    return "\n".join(dev.apply_spec(spec)) or "empty spec, nothing sent"


# ---------------------------------------------------------------- presets
@tool()
def list_presets() -> str:
    """List preset names: P01..P50 (user) and F01..F50 (factory)."""
    names = dev.read_names()
    if dev.current is None:
        dev.read_current_index()
    rows = [f"{P.preset_label(i)}  {names.get(i, '')}{'   <- current' if i == dev.current else ''}"
            for i in range(P.PRESET_COUNT)]
    note = "" if len(names) >= P.PRESET_COUNT else f"\n(note: only {len(names)} names decoded)"
    return "\n".join(rows) + note


@tool()
def select_preset(preset: str) -> str:
    """Load a preset ('P07', 'F12' or index 0..99) and return its decoded contents.
    Unsaved edits of the current preset are discarded."""
    st = dev.select(P.preset_index(preset))
    return _dump(st)


@tool()
def save_preset(preset: str, name: str) -> str:
    """Save the CURRENT edit buffer (incl. unsaved edits) into a user slot P01..P50 with a name
    (1..10 ASCII characters). OVERWRITES the slot - confirm with the user before replacing an existing preset."""
    return _dump(dev.save(_user_slot(preset), name))


@tool()
def rename_preset(preset: str, name: str) -> str:
    """Rename a user preset without changing its sound. Loads that preset first, so unsaved
    edits of the current preset are lost."""
    idx = _user_slot(preset)
    dev.select(idx)
    return _dump(dev.save(idx, name))


@tool()
def list_user_slots() -> str:
    """Names of the 5 user IR slots and 5 captured-amp (clone) profiles stored on the device."""
    return _dump({"user_irs": dev.read_slot_names(P.Q_IR_NAMES),
                  "clone_profiles": dev.read_slot_names(P.Q_CLONE_NAMES)})


def _spec_from_state(st: dict[str, Any]) -> dict[str, Any]:
    spec: dict[str, Any] = {"blocks": {}}
    if st.get("chain"):
        spec["chain"] = [c.lower() for c in st["chain"]]
    for key, b in st.get("blocks", {}).items():
        if str(b.get("model", "")).startswith("unknown"):
            continue
        e: dict[str, Any] = {"on": b.get("on", True), "params": b.get("params", {})}
        if key != "nr":
            e["model"] = b["model"]
        spec["blocks"][key] = e
    if st.get("preset_volume") is not None:
        spec["preset_volume"] = st["preset_volume"]
    return spec


@tool()
def backup_presets(label: str = "", include_factory: bool = False) -> str:
    """Back up user presets (and optionally factory ones) to a JSON file in the data directory.
    The device can only dump the edit buffer, so every preset is loaded one after another;
    the originally selected preset is reloaded at the end (unsaved edits are lost)."""
    dev.ensure()
    start = dev.read_current_index()
    names = dev.read_names()
    count = P.PRESET_COUNT if include_factory else P.USER_PRESETS
    out: dict[str, Any] = {}
    for i in range(count):
        st = dev.select(i)
        out[P.preset_label(i)] = {"name": names.get(i, ""), "spec": _spec_from_state(st), "decoded": st}
    if start is not None:
        dev.select(start)
    path = _subdir("backups") / f"presets_{_safe_filename(label) if label else time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return f"backed up {len(out)} presets to {path}"


@tool()
def list_backups() -> str:
    """List backup files in the data directory."""
    files = sorted(_subdir("backups").glob("*.json"))
    return "\n".join(f.name for f in files) or "no backups yet"


@tool()
def restore_preset(backup_file: str, source: str, target: str = "") -> str:
    """Rebuild one preset from a backup file in the edit buffer and save it.
    source: slot in the backup ('P07'); target: user slot to write (default: same as source).
    OVERWRITES the target slot."""
    path = Path(backup_file).expanduser()
    if not path.is_absolute():
        path = _subdir("backups") / backup_file
    data = json.loads(path.read_text(encoding="utf-8"))
    key = P.preset_label(P.preset_index(source))
    if key not in data:
        return f"ERROR: {key} not found in {path.name}"
    idx = _user_slot(target or source)
    log_lines = dev.apply_spec(data[key]["spec"])
    res = dev.save(idx, data[key]["name"] or key)
    return "\n".join(log_lines) + "\n" + _dump(res)


# ------------------------------------------------------------ preset files
@tool()
def save_preset_file(name: str, spec: dict[str, Any] | None = None) -> str:
    """Store a tone (apply_preset format) as a JSON file. Without spec, the current edit buffer is stored."""
    spec = spec or _spec_from_state(dev.refresh())
    path = _subdir("presets") / f"{_safe_filename(name)}.json"
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"saved {path}"


@tool()
def list_preset_files() -> str:
    """List stored tone files."""
    return "\n".join(sorted(p.stem for p in _subdir("presets").glob("*.json"))) or "no preset files yet"


@tool()
def load_preset_file(name: str, apply: bool = True) -> str:
    """Load a tone file (name from list_preset_files or a path to .json) and, by default, apply it."""
    path = Path(name).expanduser()
    if not (path.suffix == ".json" and path.exists()):
        path = _subdir("presets") / f"{_safe_filename(name)}.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    return apply_preset(spec) if apply else _dump(spec)


# --------------------------------------------------------------- firmware
# Offline tools: they read and write firmware files only, never the device. Flash the
# result with the official Sonicake Manager (Settings -> firmware update).

def _user_packs_dir() -> Path:
    return _subdir("languages")


def _pack(language: str) -> dict[str, Any]:
    p = _user_packs_dir() / f"{_safe_filename(language)}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return FW.load_pack(language)


@tool()
def firmware_info(path: str) -> str:
    """Inspect a Pocket Master firmware file (.bin): version, sections and CRCs, and what the
    second UI language currently is (official Chinese or a patched language)."""
    fw = FW.Firmware.load(path)
    return _dump({**fw.info(), "second_language": FW.second_language(fw)})


@tool()
def firmware_strings(path: str) -> str:
    """List the UI strings of a firmware file: index, English text and the second language's text.
    The English texts are the keys used by language packs."""
    return _dump(FW.ui_strings(FW.Firmware.load(path)))


@tool()
def list_language_packs() -> str:
    """Language packs available for build_language_firmware (built-in and user packs)."""
    out = {k: {"name": v.get("name"), "strings": len(v.get("strings", {})), "source": "built-in"}
           for k, v in FW.builtin_packs().items()}
    for p in sorted(_user_packs_dir().glob("*.json")):
        v = json.loads(p.read_text(encoding="utf-8"))
        out[p.stem] = {"name": v.get("name"), "strings": len(v.get("strings", {})), "source": str(p)}
    return _dump(out)


@tool()
def get_language_pack(language: str = "ru") -> str:
    """Show a language pack (name and English -> translation map), e.g. to edit it."""
    return _dump(_pack(language))


@tool()
def save_language_pack(code: str, name: str, strings: dict[str, str]) -> str:
    """Save a user language pack. code: short id (e.g. 'ru-short'); name: language name shown in
    the device's language menu; strings: English UI string -> translation (see firmware_strings).
    Strings that are not listed stay English."""
    path = _user_packs_dir() / f"{_safe_filename(code)}.json"
    path.write_text(json.dumps({"name": name, "code": code, "strings": strings}, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    return f"saved {path} ({len(strings)} strings)"


@tool()
def build_language_firmware(source: str, language: str = "ru", output: str = "",
                            overrides: dict[str, str] | None = None, preview: bool = True,
                            overwrite: bool = False) -> str:
    """Build a firmware file whose second UI language (Chinese in the official firmware) is
    replaced by a language pack. source: path to the OFFICIAL .bin (never modified);
    language: pack code (list_language_packs) or path to a pack .json; overrides: extra
    English -> translation pairs for this build; output: target path (default: next to the
    source, '<name> <CODE>.bin'). Writes a PNG preview of all strings next to it.
    Flashing is done by the user with Sonicake Manager; then pick the language in the
    device's settings. Tell the user that patched firmware is unofficial."""
    src = Path(source).expanduser()
    pack = _pack(language)
    out = Path(output).expanduser() if output else src.with_name(f"{src.stem} {pack.get('code', language).upper()}.bin")
    if out.resolve() == src.resolve():
        return "ERROR: output must not be the source file"
    if out.exists() and not overwrite:
        return f"ERROR: {out} exists (pass overwrite=true to replace it)"
    raw, report = FW.build_language(src.read_bytes(), pack, overrides)
    if not report["verified"]:
        return "ERROR: verification of the built file failed, nothing written\n" + _dump(report)
    out.write_bytes(raw)
    report["output"] = str(out)
    if preview:
        try:
            report["preview"] = str(FW.render_strings(raw, out.with_suffix(".png")))
        except ImportError:
            report["preview"] = "install pillow and numpy for previews (pip install 'pocket-master-mcp[preview]')"
    return _dump(report)


@tool()
def preview_firmware_strings(path: str, output: str = "") -> str:
    """Render the second language's strings of a firmware file with the file's own font (PNG),
    to check glyphs and lengths before flashing."""
    raw = Path(path).expanduser().read_bytes()
    out = Path(output).expanduser() if output else Path(path).expanduser().with_suffix(".png")
    return str(FW.render_strings(raw, out))


# ------------------------------------------------------ debug / research
def _write_log(prefix: str, lines: list[str]) -> Path:
    path = _subdir("logs") / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _frame_line(t: float, data: list[int]) -> str:
    try:
        f = P.parse_frame(data)
        return f"{t:8.3f} pkt {f.index + 1}/{f.total} crc={'ok' if f.crc_ok else 'BAD'} payload={f.payload.hex()}"
    except ValueError:
        return f"{t:8.3f} raw {bytes(data).hex()}"


@tool(debug=True)
def debug_send(payload_hex: str, wait: float = 1.0) -> str:
    """Send a raw payload (logical bytes as hex, e.g. '1243' = query current preset; framing, CRC and
    nibble expansion are added) and log every reply for `wait` seconds."""
    dev.ensure()
    payload = list(bytes.fromhex(payload_hex.replace(" ", "")))
    t0 = time.time()
    dev.sysex(P.build(payload))
    time.sleep(max(0.1, min(10.0, float(wait))))
    lines = [_frame_line(t - t0, d) for t, d in dev.raw if t >= t0]
    path = _write_log("query", [f"# sent {payload_hex}"] + lines)
    return f"{len(lines)} replies, log: {path}\n" + "\n".join(lines[:40])


@tool(debug=True)
def debug_monitor(seconds: float = 10.0) -> str:
    """Record incoming SysEx for up to 55 s (turn knobs / switch presets on the device meanwhile)."""
    dev.ensure()
    seconds = max(0.5, min(55.0, float(seconds)))
    t0 = time.time()
    time.sleep(seconds)
    lines = [_frame_line(t - t0, d) for t, d in dev.raw if t >= t0]
    if not lines:
        return f"nothing received in {seconds:.0f} s"
    return f"{len(lines)} messages, log: {_write_log('capture', lines)}\n" + "\n".join(lines[:80])


@tool(debug=True)
def debug_raw_dump() -> str:
    """Save the raw edit-buffer dump and preset-name dump (logical payload bytes) to the logs folder,
    with offsets, to verify or extend the decoder."""
    dump = dev.read_dump()
    names = dev.request(P.Q_PRESET_NAMES, lambda f: len(f.payload) > 100, timeout=5.0)
    lines = [f"# edit buffer dump, {len(dump)} bytes"]
    lines += [f"{i:5d}: {dump[i:i + 16].hex(' ')}" for i in range(0, len(dump), 16)]
    if names:
        lines += [f"# preset names dump, {len(names.payload)} bytes"]
        lines += [f"{i:5d}: {names.payload[i:i + 16].hex(' ')}" for i in range(0, len(names.payload), 16)]
    path = _write_log("dump", lines)
    return f"log: {path}\ndecoded: {_dump(dev.decode_dump(dump))}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
