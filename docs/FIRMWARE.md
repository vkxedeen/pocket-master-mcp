# Pocket Master firmware notes (V1.1.0, V1.3.3)

Unofficial, from static analysis of the update files and Sonicake Manager 1.3.0 for Mac.

## File (`HTFW`)

| offset | content |
|---|---|
| 0x00 | `HTFW` |
| 0x04 | uint16 unknown check value, uint16 1 — **not checked or sent by the updater** |
| 0x08 | uint32 file size (checked by the updater) |
| 0x0C | char[16] product name (checked: must match the device) |
| 0x1C | `V` major minor patch |
| 0x38 | 5 × {uint16 CRC, uint8 0, char type, uint32 flash address, uint32 offset from 0x88, uint32 size} |

Section CRC = CRC-16/MODBUS of the section, stored byte-swapped. Types: `c` bootloader/ARM,
`g` ARM code, `f` cab IRs, `b` main application (Andes NDS32, UI), `e` factory presets.

## Update protocol (Sonicake Manager)

Same SysEx framing as the editor protocol. `11 60` start, per section `11 61 <type> 00 .. <packets> <size>`,
data packets, `11 6E <type> 00`, finally `11 6E 6E 00`. Section data is sent as `[0x11, type] + data`.
No file-level or section CRC is transmitted; patched files are accepted (verified on hardware).

## UI (section `b`, pointers = section offset + 0x10000)

- Language blocks: 4 `lv_font_t*` + 80 `char*` (UTF-8). Chinese at 0x15B0B8, English at 0x15B1E0.
- Chinese font 0 (LVGL, 8 bpp, line height 11): cmap 0 = ASCII, cmap 1 = SPARSE_TINY from U+00A9 with
  © and the 91 CJK characters of the UI. Missing glyphs are drawn as boxes.
- `pocket_master_mcp/firmware.py` (MCP tool `build_language_firmware`, CLI `pocket-master-fw build`) replaces the CJK glyphs by Cyrillic pixel glyphs and the Chinese strings by
  Russian ones, so the second language becomes Russian. Section sizes stay the same.
