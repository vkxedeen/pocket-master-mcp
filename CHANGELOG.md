# Changelog

## 0.1.0 — first public release

- MCP server for the Sonicake Pocket Master over USB MIDI: models, on/off, parameters, chain order,
  preset volume, global settings, whole-tone specs, preset select / save / rename, backups, tone files.
- Protocol decoding verified on a real unit (V1.3.3): current preset, preset names, full edit-buffer dump.
- Offline firmware tools (MCP tools and the `pocket-master-fw` command): inspect `.bin` files and
  build a firmware whose second UI language is replaced by a language pack. Russian is built in and
  was verified on hardware (V1.3.3, flashed with Sonicake Manager).
