"""The encoder must reproduce commands captured from the real device (PocketEdit's library)."""
import json
import struct
from pathlib import Path

import pytest

from pocket_master_mcp import protocol as P

LIB = json.loads((Path(__file__).parent / "fixtures" / "pocketedit_commands.json").read_text())
MOD = {n: i for i, n in enumerate(P.MODULES)}


def data(h):
    return P.hex_to_sysex_data(h)


def test_framing_roundtrip():
    payload = [0x11, 0x48, 3, 0, 0, 0, 1, 0, 0, 0] + P.f32(42.5)
    f = P.parse_frame(P.build(payload))
    assert f.crc_ok and f.total == 1 and f.index == 0 and list(f.payload) == payload
    assert all(b < 0x10 for b in P.build(payload))


def test_known_messages():
    assert P.module_state(9, False) == data("8080f0080100010000000a0101040900090000000000000000000000000000f7")
    assert P.query(P.Q_PRESET_NAMES) == data("8080F0000E00010000000201020400F7")
    assert P.query(P.Q_CURRENT_DUMP) == data("8080F0000900010000000201020401F7")
    assert P.query(P.Q_CURRENT_INDEX) == data("8080F0000700010000000201020403F7")
    assert P.query(P.Q_IR_NAMES) == data("8080F0020900010000000201020200F7")
    assert P.query(P.Q_CLONE_NAMES) == data("8080F0030500010000000201020204F7")
    ack = P.parse_frame(data("8080F00B02000100000003010400080000F7"))
    assert ack.crc_ok and ack.kind == (P.ACK, P.CMD_ACK) and ack.payload[2] == 0


def test_module_states():
    for mod, d in LIB["moduleStates"].items():
        assert P.module_state(int(mod), True) == data(d["on"])
        assert P.module_state(int(mod), False) == data(d["off"])
    assert P.amp_mode(True) == data(LIB["ampModes"]["clone"])


def test_effect_types_match_device_map():
    from pocket_master_mcp.device import load_device_map
    dm = load_device_map()
    by_id = {(k, m["id"]): m for k, ms in dm["models"].items() for m in ms}
    keys = {b["module"]: b["key"] for b in dm["blocks"]}
    n = 0
    for mod, fx in LIB["effectTypes"].items():
        for fid, h in fx.items():
            fid = int(fid)
            if fid >= 901:
                assert P.select_effect(9, by_id[("clone", fid)]["code"]) == data(h)
            elif fid == 201:  # stored in the short (10-byte) form; the long form is checked by code
                f = P.parse_frame(data(h))
                assert struct.unpack("<I", f.payload[-4:])[0] == by_id[("drv", 201)]["code"]
                continue
            else:
                assert P.select_effect(int(mod), by_id[(keys[int(mod)], fid)]["code"]) == data(h), (mod, fid)
            n += 1
    assert n > 100


def test_parameters_are_float32():
    n = 0
    for mod, algs in LIB["parameters"].items():
        for alg, vals in algs.items():
            for v, h in vals.items():
                if (mod, alg) == ("8", "5"):   # one mislabelled capture in the library
                    continue
                assert P.set_param(int(mod), int(alg), float(v)) == data(h), (mod, alg, v)
                n += 1
    assert n > 200


def test_chain_orders():
    for key, h in LIB["chainOrderCommands"].items():
        assert P.set_chain([MOD[m] for m in key.split("-")]) == data(h)
    with pytest.raises(ValueError):
        P.set_chain([0, 1, 2, 6, 3, 4, 5, 7, 8])   # fixed block split up


def test_globals_and_volume():
    names = {"globalVolume": "global_volume", "inputLevel": "input_level", "fxRecLevel": "fx_rec_level",
             "btRecLevel": "bt_rec_level", "monitorLevel": "monitor_level"}
    for k, vals in LIB["globalCommands"].items():
        for v, h in vals.items():
            if k == "presetVolume":
                assert P.preset_volume(int(v)) == data(h)
            else:
                assert P.set_global(names[k], int(v)) == data(h), (k, v)


def test_preset_select_and_labels():
    for bank in ("user", "factory"):
        for label, h in LIB["presetCommands"][bank].items():
            assert P.select_preset(P.preset_index(label)) == data(h)
    assert P.preset_index("p7") == 6 and P.preset_index("F01") == 50 and P.preset_label(99) == "F50"
    with pytest.raises(ValueError):
        P.preset_index("P51")


def test_save_preset_template():
    # PocketEdit's save template: 0001000001030101040a{IDX}000000000000{NAME}000000000000
    name = "".join(f"0{c >> 4:x}0{c & 15:x}" for c in b"Lead") + "0000" * 6
    body = "0001000001030101040a" + "0001" + "000000000000" + name + "000000000000"
    raw = bytes.fromhex(body)
    logical = bytes((raw[i] << 4) | raw[i + 1] for i in range(0, len(raw), 2))
    expected = P.expand([P.crc8(logical)]) + list(raw)
    assert P.save_preset(1, "Lead") == expected
    with pytest.raises(ValueError):
        P.save_preset(50, "x")          # factory slot
    with pytest.raises(ValueError):
        P.save_preset(0, "Way too long name")


def test_preset_names_from_real_device():
    fx = json.loads((Path(__file__).parent / "fixtures" / "names_real_partial.json").read_text())
    payload = b"".join(bytes.fromhex(p) for p in fx["packets"])
    names = P.preset_name_records(payload)
    assert names == {0: "PoketMastr", 1: "Sweet OD", 2: "Chill CLN", 3: "Neo Soul", 4: "UK Metal",
                     5: "TwigiBlues", 6: "Rockstage", 7: "UKInvasion", 8: "G Force", 9: "Kyoto Solo",
                     10: "Cool Jazz"}


def test_current_preset_reply_from_real_device():
    f = P.parse_frame(P.build([0x12, 0x43, 0x21, 0x00]))
    assert f.command == P.CMD_SELECT and P.preset_label(f.payload[2]) == "P34"
