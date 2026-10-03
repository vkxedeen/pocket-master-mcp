"""Regenerate src/pocket_master_mcp/data/device_map.json from a PocketEdit checkout.

    git clone https://github.com/suckyble/PocketEdit
    node tools/extract_pocketedit.js PocketEdit/index.html > /tmp/pocketedit.json
    python tools/build_device_map.py /tmp/pocketedit.json

The effect codes are taken from PocketEdit's command library (the 4-byte value at the end
of every "select effect" command), names/parameters from its module library.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pocket_master_mcp import protocol as P  # noqa: E402

BLOCKS = [  # key, module id, display name
    ("nr", 0, "NR"), ("fx1", 1, "FX1"), ("drv", 2, "DRV"), ("amp", 3, "AMP"), ("ir", 4, "IR"),
    ("eq", 5, "EQ"), ("fx2", 6, "FX2"), ("dly", 7, "DLY"), ("rvb", 8, "RVB"),
]


def main(src: str) -> None:
    lib = json.loads(Path(src).read_text())
    mods, cmds = lib["modules"], lib["commands"]
    eff = mods["effectLibrary"]

    def param(a):
        p = {"name": a["name"], "alg": a["algId"]}
        wt = a.get("widgetType", 0)
        if wt == 1:
            p["type"] = "switch"
        elif wt == 2:
            p["type"] = "select"
            p["options"] = a["options"]
        else:
            p.update({"min": a.get("min", 0), "max": a.get("max", 100), "step": a.get("step", 1)})
            if a.get("unit"):
                p["unit"] = a["unit"]
        p["default"] = a.get("defaultValue", 0)
        return p

    models: dict[str, list] = {}
    for key, mid, _ in BLOCKS:
        fx_ids = next(m["effects"] for m in mods["modules"] if m["moduleId"] == mid)
        rows = []
        for fid in fx_ids:
            e = eff[str(fid)]
            if mid == 0:
                code = 0x1B  # Gate; seen in a real dump
            else:
                frame = P.parse_frame(P.hex_to_sysex_data(cmds["effectTypes"][str(mid)][str(fid)]))
                code = struct.unpack("<I", frame.payload[-4:])[0]
            rows.append({"id": fid, "name": e["name"], "code": code,
                         "params": [param(a) for a in e.get("alg", [])]})
        models[key] = rows
    # clone (captured amp) profiles live in module 9 but are selected in the AMP slot
    clone = []
    for fid in range(901, 906):
        e = eff[str(fid)]
        frame = P.parse_frame(P.hex_to_sysex_data(cmds["effectTypes"]["3"][str(fid)]))
        clone.append({"id": fid, "name": e["name"], "code": struct.unpack("<I", frame.payload[-4:])[0],
                      "params": [param(a) for a in e.get("alg", [])]})
    models["clone"] = clone

    out = {
        "_source": "Derived from PocketEdit (github.com/suckyble/PocketEdit) module and command libraries.",
        "blocks": [{"key": k, "module": m, "label": n} for k, m, n in BLOCKS],
        "models": models,
    }
    dst = ROOT / "src" / "pocket_master_mcp" / "data" / "device_map.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {dst} ({sum(len(v) for v in models.values())} models)")


if __name__ == "__main__":
    main(sys.argv[1])
