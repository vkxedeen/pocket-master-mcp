# pocket-master-mcp

<!-- mcp-name: io.github.voronkovd/pocket-master-mcp -->

[![PyPI](https://img.shields.io/pypi/v/pocket-master-mcp?label=PyPI&cacheSeconds=3600)](https://pypi.org/project/pocket-master-mcp/) [![CI](https://github.com/voronkovd/pocket-master-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/voronkovd/pocket-master-mcp/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant (Claude Desktop or any other MCP client) control a **Sonicake Pocket Master** guitar processor over USB MIDI. It also includes offline tools that translate the device's UI into other languages, with Russian built in.

Describe the sound you want in plain words ("tight modern metal rhythm", "clean with a wide chorus, less reverb"). The assistant picks models, sets parameters, reorders the chain, and saves and names presets on the unit.

> **Unofficial project.** It is not affiliated with or endorsed by Sonicake. The protocol is based on the reverse-engineering work in [PocketEdit](https://github.com/suckyble/PocketEdit). Reading (current preset, preset names, the full edit buffer) is verified on a real unit with firmware V1.3.3. Writing presets has seen little hardware testing so far, so **run `backup_presets` first**. Patched firmware is unofficial too: you use it at your own risk.

## What it can do

- **Live editing:** select a model in any block (22 amps + 5 captured-amp profiles, 20 cabs/IRs, 8 drives, FX1/FX2 with 15–17 effects each, 9 delays, 10 reverbs, 3 EQs, noise gate), switch blocks on and off, and set parameters by name with range checking (`Gain`, `Time` in ms, `Rate` in Hz, `Mode` = `Bass`, `+3dB` = `on`, …).
- **Signal chain:** reorder NR / FX1 / FX2 / DLY / RVB around the fixed DRV-AMP-IR-EQ block.
- **Read state:** decode the edit buffer (models, on/off, parameter values, chain, preset volume) and list the 100 preset names.
- **Presets:** select presets, save the edit buffer to a user slot P01–P50 with a name, rename presets, back up and restore presets.
- **Tone files:** apply a whole tone from a JSON file. Examples are in [`examples/presets`](examples/presets).
- **Globals:** global volume, input / FX rec / monitor / BT rec levels.
- **UI language:** build a firmware file with a translated UI (Russian built in, see [UI language](#ui-language-firmware)).

## Requirements

- A Sonicake Pocket Master connected over USB. It shows up as a class-compliant MIDI port.
- Python 3.10+.
- An MCP client, for example [Claude Desktop](https://claude.ai/download).

The server has to run on the computer the Pocket Master is plugged into, because it needs direct access to the USB MIDI port.

## Installation

The easiest way is [uv](https://docs.astral.sh/uv/): `uvx` downloads and runs the server.

### Claude Desktop

Open **Settings → Developer → Edit Config** and add:

```json
{
  "mcpServers": {
    "pocket-master": {
      "command": "uvx",
      "args": ["pocket-master-mcp"]
    }
  }
}
```

Restart Claude Desktop completely. If Claude cannot find `uvx`, use its absolute path (`which uvx`, typically `~/.local/bin/uvx`). For firmware previews (PNG), use `"args": ["--from", "pocket-master-mcp[preview]", "pocket-master-mcp"]`.

Alternatively, run `pipx install pocket-master-mcp` or `pip install "pocket-master-mcp[preview]"` and use `"command": "pocket-master-mcp"`.

### From source

```bash
git clone https://github.com/voronkovd/pocket-master-mcp.git
cd pocket-master-mcp
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Then use `"command": "/absolute/path/to/pocket-master-mcp/.venv/bin/pocket-master-mcp"`.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PM_PORT` | auto | substring of the MIDI port name. Without it, the server looks for "Pocket", "Sonicake", "QME" and otherwise probes every port. |
| `PM_DATA_DIR` | `~/.pocket-master-mcp` | where backups, tone files, language packs and logs are stored |
| `PM_DEVICE_MAP` | bundled | path to a custom `device_map.json` |
| `PM_DEBUG_TOOLS` | off | `1` exposes `debug_send`, `debug_monitor` and `debug_raw_dump` |

## Checking the connection

1. From a source checkout, run `python scripts/midi_check.py`. It is read-only: it prints the ports, the current preset and the preset names.
2. In Claude: *"connect to the Pocket Master and show the device state"*. Compare the models and values with the screen of the unit.
3. If something is decoded wrongly, set `PM_DEBUG_TOOLS=1` and ask for `debug_raw_dump`. It writes the raw dump with offsets to `~/.pocket-master-mcp/logs/`. Please attach it to an issue.

## Tools

| Tool | What it does |
|---|---|
| `connect`, `list_midi_ports` | find and open the Pocket Master |
| `device_state` | edit buffer: preset, chain, amp mode, models, on/off, parameter values |
| `list_models(block)` | models of a block with their parameters and ranges |
| `set_model(block, model, on)` | select a model by name |
| `set_block(block, on)` | switch a block on or off |
| `set_param(block, param, value)` | set a parameter of the current model |
| `set_chain(order)` | signal chain order |
| `set_preset_volume`, `set_global` | preset volume, global settings |
| `apply_preset(spec)` | apply a whole tone in one call |
| `list_presets`, `select_preset` | preset names, load a preset |
| `save_preset(preset, name)` | save the edit buffer to P01–P50, verified by reading the names back |
| `rename_preset` | rename a user preset |
| `backup_presets`, `list_backups`, `restore_preset` | backups as JSON |
| `save_preset_file`, `list_preset_files`, `load_preset_file` | tone files |
| `list_user_slots` | names of the user IRs and captured-amp profiles |
| `firmware_info`, `firmware_strings` | inspect a firmware `.bin`: version, sections, CRCs, UI strings |
| `list_language_packs`, `get_language_pack`, `save_language_pack` | UI translations (English string → translation) |
| `build_language_firmware` | build a firmware with the second UI language replaced by a language pack, plus a PNG preview |
| `preview_firmware_strings` | render a firmware's UI strings with its own font |

Blocks are `nr` (gate), `fx1`, `drv`, `amp`, `ir`, `eq`, `fx2`, `dly`, `rvb`. Aliases such as `gate`, `drive`, `cab`, `delay` and `reverb` also work. Captured-amp profiles (`User Profile 1..5`) are selected in the `amp` block, and the server switches the amp mode automatically.

## UI language (firmware)

The firmware has two UI languages, English and Chinese. `build_language_firmware` replaces the Chinese one with a language pack: Russian (`ru`) is built in, and your own packs can be saved with `save_language_pack`. It works offline on a copy of the **official** firmware file, never on the device. Flash the result with the official **Sonicake Manager**, then choose the language in the device's settings. To go back, flash the official file.

- A pack maps English UI strings to translations. Strings that are not listed stay English. Effect and parameter names exist only in English in the firmware and are not translated.
- The device font is a tiny pixel font, so glyphs are hand-drawn in `data/glyphs.json`. Cyrillic is included. For other scripts, add glyphs there first; the build stops and lists any character without a glyph.
- The build checks the result: CRCs, every string, a glyph for every character, and that only the UI section changed. It refuses already-patched input, and it never overwrites the source.
- This is **unofficial**, so use it at your own risk. It was tested on V1.3.3 and builds for V1.1.0. Details are in [`docs/FIRMWARE.md`](docs/FIRMWARE.md).

Example: *"Build a Russian firmware from ~/Downloads/Pocket Master Firmware V1.3.3.bin, but use 'Сохр.' for Save."*

The same is available without an MCP client:

```bash
pocket-master-fw info  "Pocket Master Firmware V1.3.3.bin"
pocket-master-fw build "Pocket Master Firmware V1.3.3.bin" -l ru --set "Save=Сохр."
```

Firmware files are not part of this project. Download them from Sonicake.

## Tone format

```json
{
  "chain": ["nr", "fx1", "drv", "amp", "ir", "eq", "fx2", "dly", "rvb"],
  "blocks": {
    "drv": {"model": "Scream", "params": {"Gain": 5, "Tone": 60, "Vol": 85}},
    "amp": {"model": "Sol 100 LD", "params": {"Gain": 62, "Middle": 58}},
    "ir":  {"model": "BritGN 4x12"},
    "dly": {"on": false},
    "rvb": {"model": "Room", "params": {"Mix": 10}}
  },
  "preset_volume": 70
}
```

Selecting a model resets its parameters to the model defaults, so parameters are applied after the model (`apply_preset` does this in the right order).

## Limitations

- Only the edit buffer can be dumped. Backups therefore load every preset one by one, and unsaved edits are lost.
- Backups store decoded settings, not raw preset bytes, so anything the decoder does not know (if anything) is not restored.
- Global settings can be written but not read yet.
- User IR / captured-amp *contents* cannot be uploaded, only selected.

## How it works

- [`docs/PROTOCOL.md`](docs/PROTOCOL.md): MIDI SysEx framing (nibble expansion, CRC-8), commands, the edit-buffer dump and the preset names.
- [`docs/FIRMWARE.md`](docs/FIRMWARE.md): the `HTFW` firmware container, the update protocol of Sonicake Manager, and the LVGL UI fonts and string tables.
- `tools/build_device_map.py` regenerates the model and parameter table from a PocketEdit checkout.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

The tests rebuild a sample of the device commands captured by PocketEdit and real replies from a unit, and they run the device logic against a fake Pocket Master, so no hardware is needed. Firmware build tests run when an official firmware file is in `local/` or `PM_TEST_FIRMWARE` points to one.

## Credits and license

- **PocketEdit** by [suckyble](https://github.com/suckyble/PocketEdit) and contributors (hnikolov and others) is the source of the protocol knowledge. The model and parameter table (`data/device_map.json`, regenerated by `tools/build_device_map.py`) and the command samples in `tests/fixtures/pocketedit_commands.json` are derived from its libraries. PocketEdit does not state a license. If you are its author and want these files changed or removed, please open an issue.
- The firmware language tools contain no Sonicake code or data. They patch a firmware file the user supplies.

This code is MIT licensed, see [LICENSE](LICENSE). Sonicake and Pocket Master are trademarks of their owners. Model names refer to the products they emulate and are used only to identify the models.
