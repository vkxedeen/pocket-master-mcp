#!/usr/bin/env python3
"""Read-only connectivity check without an AI client (changes nothing on the device).

Lists MIDI ports, finds the Pocket Master, asks for the current preset number, the preset
names and the edit-buffer dump, prints what was decoded and saves the raw dump to
local/dump_<time>.txt. Usage: python scripts/midi_check.py [port-substring]
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mido  # noqa: E402

from pocket_master_mcp import protocol as P  # noqa: E402

HINTS = [sys.argv[1]] if len(sys.argv) > 1 else ["pocket", "sonicake", "sonic master", "qme"]
outs, ins = mido.get_output_names(), mido.get_input_names()
print("MIDI outputs:", outs or "none")
print("MIDI inputs: ", ins or "none")
out_name = next((n for h in HINTS for n in outs if h.lower() in n.lower()), None)
in_name = next((n for h in HINTS for n in ins if h.lower() in n.lower()), None)
if not out_name or not in_name:
    sys.exit("Pocket Master not found by name. Pass part of the port name as an argument.")
print(f"using output '{out_name}', input '{in_name}'")


def ask(out, inp, kind, label, wait=2.0):
    for _ in inp.iter_pending():
        pass
    out.send(mido.Message("sysex", data=P.query(kind)))
    t0, got = time.time(), []
    while time.time() - t0 < wait:
        for m in inp.iter_pending():
            if m.type == "sysex":
                got.append(m)
        time.sleep(0.01)
    print(f"\n{label}: {len(got)} SysEx message(s)")
    for m in got[:12]:
        try:
            f = P.parse_frame(list(m.data))
            print(f"  packet {f.index + 1}/{f.total} crc={'ok' if f.crc_ok else 'BAD'} "
                  f"payload[{len(f.payload)}]={f.payload[:24].hex(' ')}{' ...' if len(f.payload) > 24 else ''}")
        except ValueError:
            print("  raw", bytes(m.data[:32]).hex(" "))
    return got


with mido.open_output(out_name) as out, mido.open_input(in_name) as inp:
    got = ask(out, inp, P.Q_CURRENT_INDEX, "current preset")
    for m in got:
        f = P.parse_frame(list(m.data))
        if len(f.payload) >= 3 and f.payload[1] == P.CMD_SELECT:
            print("  -> current preset:", P.preset_label(f.payload[2]))
    got = ask(out, inp, P.Q_PRESET_NAMES, "preset names", wait=3.0)
    payload = b"".join(P.parse_frame(list(m.data)).payload for m in got)
    names = P.preset_name_records(payload)
    print(f"  -> {len(names)} names, first ones: {[names[i] for i in sorted(names)[:8]]}")

    got = ask(out, inp, P.Q_CURRENT_DUMP, "edit-buffer dump", wait=3.0)
    frames = [P.parse_frame(list(m.data)) for m in got]
    dump = b"".join(f.payload for f in sorted(frames, key=lambda f: f.index))
    print(f"  -> {len(dump)} bytes in {len(frames)} packet(s), all crc ok: {all(f.crc_ok for f in frames)}")
    if dump:
        from pocket_master_mcp.device import PocketMaster
        decoded = PocketMaster().decode_dump(dump)
        print(json.dumps(decoded, ensure_ascii=False, indent=1))
        lines = [f"{i:5d}: {dump[i:i + 16].hex(' ')}" for i in range(0, len(dump), 16)]
        path = Path(__file__).resolve().parents[1] / "local" / f"dump_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(lines) + "\n\n" + json.dumps(decoded, ensure_ascii=False, indent=1) + "\n")
        print("\nraw dump:")
        print("\n".join(lines))
        print(f"\nsaved to {path}")
print("\ndone")
