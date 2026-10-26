# print3d-voron

Fork of mfranzon/print3d (MIT), ported from Bambu Studio + X2D to PrusaSlicer + Klipper
Vorons. Plan and audit: docs/PORT.md. Brief: https://claude.ai/artifact/S1rQCJ5ea1g2gNtwgiEM3z

## Standing rules
- Keep the printer-agnostic parts (photo measurement, likeness, fits, printability, viewer,
  handoff) working. The peg and bracket benchmark tests must stay green.
- All printer knowledge lives behind one profile layer: `src/print3d/profiles/<printer>/`
  holding `printer.toml` plus one exported PrusaSlicer `.ini` per material, chosen by a
  `--printer` argument (default `voron300-sc`). Keep changes outside that layer small so it
  can go upstream as a pull request. The Bambu backend (x2d-0.4) stays working behind the
  same slicer interface; do not delete studio.py, flatten.py or repair_3mf.py.
- Fits are keyed by printer, nozzle and material.
- One material family per plate unless Jeff approves a pair (e.g. PETG interface under PLA).
- Never start a print. Moonraker uploads always send `print=false`. Never commit API keys or
  other secrets; the key comes from `MOONRAKER_API_KEY`.
- Work in phases (docs/PORT.md) and stop at each gate for Jeff's review.

## Local setup (Jeff's Mac Studio)
- PrusaSlicer 2.9.6: `/Applications/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer`
  (override with `PRUSASLICER_BIN`). Pin this version; per-part tool metadata lives in its
  internal 3MF format.
- Blender 5.2.2 at `/Applications/Blender.app` (upstream asks for 4.2+).
- Live PrusaSlicer presets: `~/Library/Application Support/PrusaSlicer/{printer,print,filament}/`.
  Copy, never edit them in place.
- Remotes: `upstream` = mfranzon/print3d; `origin` = 3d-dank/print3d-voron (once forked).
