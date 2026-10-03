# Contributing

Issues and pull requests are welcome, especially for:

- **Other firmware versions.** If something is decoded wrongly, run the server with `PM_DEBUG_TOOLS=1`
  and attach the output of `debug_raw_dump` or `debug_monitor` (in `~/.pocket-master-mcp/logs/`).
  Remove anything personal first: dumps include preset names.
- **Writing presets.** Saving and restoring presets has not been tested much on hardware.
  Reports, good or bad, are very useful.
- **Language packs.** Add `src/pocket_master_mcp/data/languages/<code>.json`. Keys are the English UI
  strings (`pocket-master-fw strings FIRMWARE.bin`). Missing letters go into `data/glyphs.json`:
  5x8 pixel art in the style of the font's Latin letters, with `oy` = rows below the baseline.
  Check with `pocket-master-fw build ...` and look at the PNG preview.
- **Tone examples.** Add files to `examples/presets`. Describe them as "in the style of", not as official
  artist presets.

Please **never commit firmware files** (`.bin`) or the Sonicake Manager installer. They belong to Sonicake.
Keep them in `local/`, which git ignores.

Before opening a PR, run `pytest`. Device tests use a fake unit, so no hardware is needed. Firmware build
tests run only when an official firmware file is available: put it in `local/` or set `PM_TEST_FIRMWARE`.
