"""Command line for the offline firmware tools (no MCP client needed).

    pocket-master-fw info     FIRMWARE.bin
    pocket-master-fw strings  FIRMWARE.bin
    pocket-master-fw packs
    pocket-master-fw build    FIRMWARE.bin [-l ru] [-o OUT.bin] [--set "Save=Сохр."] [--force]
    pocket-master-fw preview  FIRMWARE.bin [-o OUT.png]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import firmware as F


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pocket-master-fw", description="Sonicake Pocket Master firmware tools (offline).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="version, sections, CRCs, second UI language")
    p.add_argument("firmware")
    p = sub.add_parser("strings", help="UI strings (English and second language)")
    p.add_argument("firmware")
    sub.add_parser("packs", help="built-in language packs")
    p = sub.add_parser("build", help="replace the second UI language by a language pack")
    p.add_argument("firmware", help="official firmware .bin (not modified)")
    p.add_argument("-l", "--language", default="ru", help="pack code or path to a pack .json (default: ru)")
    p.add_argument("-o", "--output", help="output .bin (default: next to the input, '<name> <CODE>.bin')")
    p.add_argument("--set", action="append", default=[], metavar="ENGLISH=TRANSLATION",
                   help="override one string, may be repeated (use \\n for a line break)")
    p.add_argument("--force", action="store_true", help="overwrite the output file")
    p.add_argument("--no-preview", action="store_true", help="do not write the PNG preview")
    p = sub.add_parser("preview", help="PNG of the second language's strings")
    p.add_argument("firmware")
    p.add_argument("-o", "--output")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "info":
            fw = F.Firmware.load(a.firmware)
            _print({**fw.info(), "second_language": F.second_language(fw)})
        elif a.cmd == "strings":
            _print(F.ui_strings(F.Firmware.load(a.firmware)))
        elif a.cmd == "packs":
            _print({k: {"name": v.get("name"), "strings": len(v.get("strings", {}))} for k, v in F.builtin_packs().items()})
        elif a.cmd == "build":
            src = Path(a.firmware).expanduser()
            pack = F.load_pack(a.language)
            out = Path(a.output).expanduser() if a.output else src.with_name(
                f"{src.stem} {str(pack.get('code', 'custom')).upper()}.bin")
            if out.resolve() == src.resolve():
                sys.exit("output must not be the input file")
            if out.exists() and not a.force:
                sys.exit(f"{out} exists (use --force)")
            overrides = {}
            for s in a.set:
                k, sep, v = s.partition("=")
                if not sep:
                    sys.exit(f"--set needs ENGLISH=TRANSLATION, got {s!r}")
                overrides[k.replace("\\n", "\n")] = v.replace("\\n", "\n")
            raw, report = F.build_language(src.read_bytes(), pack, overrides)
            if not report["verified"]:
                _print(report)
                sys.exit("verification failed, nothing written")
            out.write_bytes(raw)
            report["output"] = str(out)
            if not a.no_preview:
                try:
                    report["preview"] = str(F.render_strings(raw, out.with_suffix(".png")))
                except ImportError:
                    report["preview"] = "pip install 'pocket-master-mcp[preview]' for previews"
            _print(report)
        elif a.cmd == "preview":
            raw = Path(a.firmware).expanduser().read_bytes()
            out = a.output or str(Path(a.firmware).expanduser().with_suffix(".png"))
            print(F.render_strings(raw, out))
    except (ValueError, OSError) as e:
        sys.exit(f"error: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
