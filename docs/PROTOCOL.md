# Pocket Master SysEx protocol

Based on [PocketEdit](https://github.com/suckyble/PocketEdit) (`tools/SYSEX_PAYLOAD_FORMAT.md` and `index.html`). The logical-byte view below is a reinterpretation of that work: PocketEdit works with hex strings and fixed character offsets. Every command builder in `protocol.py` is checked against the captures in PocketEdit's command library.

## Framing

Over USB, a message is a normal SysEx `F0 … F7`. Over BLE-MIDI, it is preceded by the 2-byte timestamp `80 80`. Between `F0` and `F7`, every **logical byte** `0xAB` is sent as the two bytes `0A 0B` (nibble expansion), so the data stays 7-bit clean.

```
logical frame:  crc  total  index  length  payload[length]
```

| field | meaning |
|---|---|
| `crc` | CRC-8/SMBus (poly `0x07`, init `0`) over `total … payload` |
| `total` | packets in this response (1 for normal messages) |
| `index` | packet number, 0-based |
| `length` | payload bytes in this packet |

Multi-packet responses (preset dump, name list) are joined by concatenating the payloads of packets `0 … total-1`.

## Payload

`[type, command, …]`. Integers are little-endian, parameter values are float32.

| type | direction |
|---|---|
| `0x11` | set (host → device) |
| `0x12` | get request (host → device) / state report (device → host) |
| `0x14` | acknowledge (device → host) |

### Set commands (`0x11`)

| cmd | layout after `11 cmd` | meaning |
|---|---|---|
| `0x11` | `group sub 00 00 int32` | global setting (see table) |
| `0x42` | `01 20 01 00 value` | preset volume 0..100 |
| `0x43` | `uint32 index` | load preset (0–49 user P01–P50, 50–99 factory F01–F50) |
| `0x44` | `m0 … m8 09` | chain order (module ids), DRV-AMP-IR-EQ stay together |
| `0x47` | `uint32 module, uint32 module, uint32 code` | select effect model |
| `0x48` | `uint32 module, uint32 param, float32 value` | set parameter |
| `0x49` | `uint32 module, uint32 on` | module on/off. Module 9 = amp mode (0 normal amp, 1 captured profile) |
| `0x4A` | `uint32 slot, char[10] name, 00 00 00` | save edit buffer to user slot 0..49 |

Modules: 0 NR, 1 FX1, 2 DRV, 3 AMP, 4 IR, 5 EQ, 6 FX2, 7 DLY, 8 RVB, 9 captured amp ("clone").

Effect codes are `category << 24 | id`, for example DRV `0x03……`, AMP `0x07……`, IR `0x0A……`, DLY `0x0B……`, RVB `0x0C……`. The full table is in `data/device_map.json`. Captured profiles use module 9 and category `0x0F` (profile 1 is captured as `0x07000000`), so the server compares only the low 24 bits.

Globals (`group`, `sub`): volume (2,2) 0..100; input level (1,3), FX rec (1,4), monitor (2,4), BT rec (5,4), all −20..20 dB as int32.

### Requests (`12 kind`)

| kind | reply |
|---|---|
| `0x10` | global settings |
| `0x20` | user IR names: 5 × 16-byte records after a 7-byte header, name = first 10 bytes |
| `0x24` | captured-amp profile names, same layout |
| `0x40` | all 100 preset names (multi-packet), 10-byte zero-padded ASCII names in fixed records |
| `0x41` | edit-buffer dump (multi-packet), see below |
| `0x43` | current preset: `12 43 index …` |
| `0x45` | modified flag: `12 45 0/1` |

The device also sends `12 43 …`, `12 47 …` (short form: module, code), `12 48 …` and `12 49 …` when the preset or a knob is changed on the unit itself.

ACK: `14 08 00` = ok, `14 08 01` = failed (sent after save).

## Edit-buffer dump (reply to `12 41`)

Confirmed on a real unit (476 bytes in 26 packets, see `tests/fixtures/dump_real_p34.json`).

```
12 41  uint16 0x00ff  uint16 header_len  header records  groups...
record = uint16 tag, uint16 length, data[length]      group = record whose data are records
```

| group | tag | content |
|---|---|---|
| header | `0x0001`, `0x0002` | unknown (`02000000`, `0a454d51`) |
| 0 | `0x1001..0x1003` | unknown uint32 (10, 8, 2) |
| 1 | `0x2001` | uint32 preset volume |
| 1 | `0x2002` | uint32, 120 in the sample: probably tempo (BPM), unconfirmed |
| 2 | `0x3001` | uint32 mask: bit m = module m on, bit 9 = captured-amp mode |
| 2 | `0x3002` | 9 module ids in chain order + `09` |
| 2 | `0x3003` | 10 × uint32 effect code (modules 0..9; the NR gate is `0x1B`) |
| 2 | `0x3004` | 10 modules × 8 × float32 parameters (module m, param p at `32·m + 4·p`) |
| 3 | — | 8 zero bytes |

## Preset names (reply to `12 40`)

`12 40`, then 100 records of `uint32 slot, char[16] name` (zero padded), sent in 106 packets.
