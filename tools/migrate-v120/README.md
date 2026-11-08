# M: 8.2 contents on upstream 0.8.9 / GR IV 1.20

SPDX-License-Identifier: GPL-2.0-only

Start: upstream/release-0.8.9 at `fe9ca39`. The local `v0.8.9` tag was found to
point to a fork 0.8.6 commit; it was not used or moved. AF/AFML source was first
saved separately on codex/dev (`9060426`); no AF code is part of this port.

Source modules remain separate (`awbml`, `shadowml`, `awbfit`, `brightauto`).
`BuildOptions.awbLearn`, `shadowLearn`, `awbFit`, `brightAuto` independently enable
them for both 1.11 and 1.20. An absent/false switch preserves upstream behaviour.
The default migration recipe explicitly selects all four, with `brightAuto: balanced`.
Recipes record their switches in feature-byte-2 bit 2 plus a learned-flags byte;
without them, record bytes are exactly upstream's.

PR #21 is `color/hue-additive.ts`, selected by `ConvertOptions.additiveHue`.
PR #22 is `color/white-anchor.ts`, selected by `ConvertOptions.keepWhite`.
They are also accepted by `Engine.convertPreset` for GR IV; both default false,
so ordinary imports stay compatible with upstream. They affect conversion of a
new LUT, not a previously quantised slot. Single and combined switch results
were compared with the original branches (4923842 and f253810).
The migration copies all 20 actual 8.2 slots verbatim; it does not fit them again.
The 15 supplied replacement LUTs already match the existing 8.2 data when imported
with the original `hue: true` conditions (matrix, curves, post and hue block).

## Private inputs and builds

Activate the existing Codex environment with `source ../out/codex/activate.sh`.
Keep all firmware, decoded images, full extracted recipes and test data outside Git.
The first inventory used the verified 8.2 container and the original codex/dev
engine, and rebuilt exactly the same 40401304-byte file. Its private files are
`$GRMOD_OUT/v120-01/inventory82{,-full}.json` and `rebuild82.json`.

```
npx vite-node tools/migrate-v120/build.ts   "$GRMOD_OUT/v120-01/inventory82-full.json"   "$GRMOD_PACK/official/official.bin"   "$GRMOD_PACK/official/official_1.20/fwdc248b.bin"   "$GRMOD_OUT/v120-01"
python3 tools/migrate-v120/audit.py "$GRMOD_OUT/v120-01"
```

The builder produces off / fit / AWB / full variants for both versions. Every
container must pass all build checks and full `inspect` reconstruction. The off
variants must match the pre-migration upstream builds byte-for-byte.
`fwdc248b.bin` is the 1.20 full variant. Raw historical-behaviour controls are only
emulator inputs: their module context has live exposure disabled or unscaled
output, and they are not updater containers or independently validated old releases.
They exercise the same legacy-behaviour assertions as the original suite.

## Port and checks

`tools/port/gr4-120-learned-overrides.json` records every mapped address and its
evidence. The upstream mapping run accepted 145/160 (including existing upstream
overrides); 15 needed additional manual inspection, including the changed still builder and the singleton object.
`gr4-120-learned.json` generates only these modules and their test helpers, followed
by native generation, so unrelated upstream embedded code is preserved.

```
GRMOD_ZIG=1 python3 tools/port/generate.py tools/port/gr4-120-learned.json
```

Generation has been rerun and all generated module sources compared exactly.
The broader upstream GR IV map/hand-edit patch also includes the new source modules.
Use the independent learned-module config when rebuilding just this addition.

For 1.20, set `GRIV_RTOS=$GRMOD_OUT/v120-01/official120.rtos` and run the copies
under `tools/gr4v120/{re,awbml,shadowml}`. Run the original 1.11 tools with the
original environment. The AWB full-suite controls are documented in the private
run log and final handoff. No numeric or ABI assertions were removed.
For migrated 1.11 builds the original shadow suite also accepts the explicit
`GRMOD_SHADOW_DIFF_MANIFEST` audit; without it the historical checks run unchanged.
The 1.20 shadow suite's old equal-padded-image assumption was replaced by a strict
actual-build manifest: hook, gain word, whole appended code/model/context,
exact recipe-bit change, zero padding and unchanged old prefix. Hashes bind that
manifest to both actual RTOS images. `audit.py` produces it independently.

`check_quant.py` executes the actual 1.20 still S builder through its three new
quantisers; the native C exhaustive check is `tools/gr4v120/awbml/test_fl8.c`.
1.20 rounds to nearest eighth-stop with ties upward instead of 1.11's float32
truncation. The module implements the new behaviour with integer operations.
Its trained model, tables and gain-scaling algorithm are otherwise unchanged.

`boot.py` invokes upstream's 1.20 boot checker on the full candidate. The two
intentional AWB/shadow hooks are classified as function-level entries only after
their full function suites pass, following the checker's HDR/ADJ convention.

**Full-recipe boot validation has not passed.** The initial 1318-hook run reported
failures in the early Halation/parameter hooks and was stopped for diagnosis.
A first-20-hook native-focused diagnostic (40 states per hook) reproduced the same
16 failures on both the unmodified upstream recipe and this candidate. Excluding
new look/RAW identities did not resolve them; that experimental fixture is kept
only in private research output. No existing hook was exempted to force a pass.
Examples include invalid Toning 160 being clamped to 0, and complex wrappers whose
first original-code call is not a valid final synchronization point. The remaining
UI/controller cases need valid typed objects and whole-function replay.

`looks120.log` records a separate successful upstream menu/layout/settings check
on the actual full 20-slot candidate against the same recipe without the layout.
A separate ratios-plus-four-modules raw diagnostic passed the original boot checker
(55 transparent hooks, 40 states each; directories, settings, RAW targets and entry wrappers).
It runs the original boot checker
without the slot/Halation UI. Its result does not replace full-recipe validation.
The final handoff and `boot120.json` record these scopes and the unresolved stop.

Learned modules share the existing heap-gap words with HDR/diagnostic options.
Conflicting HDR, Halation diagnostics and Direct Flash diagnostics are rejected
at build time. Regular Halation on the 20 slots remains enabled.

The inventory describes firmware content and build-time switches. The updater file
does not reveal the camera's currently selected menu values or stored user modes.

No camera, card or flash operation is performed by these tools. Delivery is a
candidate for Claude review. The official 1.20 update is irreversible.
