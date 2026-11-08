# GR IV 1.20 migration M

This file records the port from the upstream `fe9ca39` (0.8.9) base. Historical
notes in this directory retain their 1.11 addresses and evidence labels. Use
[the migration tools](../../tools/migrate-v120/README.md) and
[the address overrides](../../tools/port/gr4-120-learned-overrides.json) for 1.20.

## Scope and evidence

- [E] The actual 8.2 container was inspected before source migration, then rebuilt
  byte-for-byte using its 20 slots, icons, ratios, hidden-look list and four module
  settings. It contains no AF/CPU-LUT experiment or additional end-screen image.
- [E] The 1.20 recipe retains the 20 slot payloads exactly. Added styles move from
  34..53 to 38..57; the hidden factory styles remain the same. Two additional
  1.20 factory styles (31/32, monochrome) are retained in the order schema.
- [E] The 15 supplied LUTs already reproduce the actual 8.2 slots under the
  original hue-enabled import settings. Re-fitting with PR21/22 enabled uses
  different fitting constraints; those flags are available independently for
  future imports and are not used to alter the migration's existing colours.
- [C] ComPropIf guard/slot/vtable move to 5537b298/5537b2a0/53fc54d8. Constructor
  and getter/commit owners preserve E+518, D+4d8/4dc/4e0 and the 1090-byte buffer
  stride. Private `property-layout-audit.json` records the paired instructions.
- [C/E] Still S construction moves to 5395bde8 and delegates exposure rounding to
  538fb018/538fb068/538fb0b8. The integer live reader was adapted and checked
  against the actual builder, in addition to host and ARM tests. See
  `stock120-quant.json`, `awb120-host.log`, `awb120-arm.log` and `awb120-fw.log`.
- [C] AWB/shadow modules use white-balance/shooting modes and statistics fields,
  without look-number dispatch; style 38..57 is handled by the upstream 1.20 slot
  and settings modules.
- [C] AWB slot 5583901c, shadow scratch 55839014 and throttle 5583903c stay within
  the upstream reserved 44-byte gap and its extended zero-fill end 55839040.
  These are shared with optional upstream HDR/diagnostic uses; the builder refuses
  those combinations. No RAM ownership assumption is silently applied to AF.
- [E/?] The full candidate's menu/hidden-look/settings checks pass. Generic
  full-recipe boot transparency checks report failures also present on the upstream
  recipe; first-20-hook diagnostics match exactly (16 failures). Full-recipe
  validation remains open; matching the baseline does not close this requirement.
- [?] Installability, real boot, real camera performance, white balance/shadow
  quality and recovery are not established by emulation. Await Claude review.

Private output lives under `out/codex/v120-01`. The final handoff records exact
commands, all results (including historical core-suite failures), firmware hashes,
model/effort/usage and the review stop. This task does not authorise flashing.
