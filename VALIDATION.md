# Apex early-season compiler validation - 8 November 2026

Experimental development checkpoint for native S0-S3 output. Offline structure,
render and authored-animation checks pass. R5R v2.6.52 completed six spawns,
eleven sequence checks and 55 server playback/movement samples with the original
walking IK chain retained. All six client screenshots show the expected shapes;
the float-position prop also shows its bent pose. This fixes the preceding
checkpoint's IK-linkage crash and invalid float-material visual control.
This is not a stable release or proof of full Apex model equivalence.
Retail and later self-hostable seasons remain future targets.

Windows x64 MSVC Release: build/r5studiomdl.exe
SHA-256: `00f58e02143edc2e5bdd8a4d823bb52550c9b81a1ad8dda2114cafa20a9eb9b2` (15 November 2026).
Independent reader SHA-256: `59b293911d28bf9cd674981fcfaffccf73fbab854d2efbc8c88639439c22d4a4`.

## Automated checks

- All 75 native compiler/packaging/runtime-harness regressions pass on ordinary Python 3.10 and locked uv/Python 3.14.
- Both CTest groups pass: convex-hull math and native compiler regressions. The
  inherited hull tests are not Apex physics emission evidence.
- Complex-skinning tests exercise mixed 1/2/3/4/8/16-influence vertices across all
  four profiles, preservation through SMD and DMX, all sixteen bone usage flags,
  VVD/VVW checksums/offsets, multiple meshes/LODs with VVC, malformed weight spans,
  excess-influence rejection, small positive weights and quantization-budget failure.
  A mesh with 4,803 sixteen-influence vertices checks shared VG extra-weight data
  beyond the capacity of a naive uint16-indexed per-vertex table.
- The earlier geometry, body-group, LOD, attachment, hitbox, event, blend and delta
  checks remain. Full-frame animation checks cover a 95-frame authored sequence,
  section boundaries and position/rotation/scale with unchanged tolerances.
- The clean ZIP contains six authored examples, including native frame movement and two-block
  piecewise root motion with an IK chain. All six compile, export, recompile and pass render comparisons
  on all four targets: 24 package round trips. These also compare supported
  animation metadata and every decoded frame in every blend, including the animated
  example's new blend/event. This is not full model or runtime equivalence.

## External assets and S3 packaging

External assets preserve the shared skeleton, attachments, hitboxes, IK chains,
pose parameters and standalone sequence metadata/tracks. Authored checks compare
embedded vs standalone assets for all four targets, including native frame
movement, fractional-cycle events and a six-blend rectangular grid with pose keys.
Every animation frame is decoded for comparison. Material GUID binding is still
required for each render slot. The manifest bounds the sequence set; tests cover
stale extra sequence files, target mismatches, unbound material rejection and a
RePak process that exits zero without producing new artifacts.

The installed RePak built six runtime example bindings into 29 assets: six models,
six rigs and seventeen sequences (eleven authored clips plus six empty references).
The mandatory streaming file contains six VG assets. No IK chain is removed.
RePak SHA-256: `afaf61c9f462444adbe49d87a494a63bdc813be8945d8857c9d692847f1a5ca2`.
RPak SHA-256: `900468758a27cfe5402c7f773645f9c73c652f05df9be738b16b53c3f946333b`.
Streaming SHA-256: `2faf9fb82eda83b8f5f744608b94858352b02181527b54fdf4e21522e9b880bc`.
Build map, source hashes and an empty runtime-exclusions list are recorded in
`test-output/r5r-authored/pak/r5c_authored.report.json`.

The isolated runtime is `F:\Games\Apex Detours\r5c-test-runtime`, sourced from
R5R v2.6.52 LIVE. Its executable SHA-256 is
`bfe9066cf13db3b72fb1017a385260ac2337442f82c4acc96fca40cb7ff306ef`.
Current retail was not modified or launched. The completed report, netconsole log,
client/server script log and reviewed PNGs are under
`test-output/r5r-runtime-evidence`. The final run exited cleanly with code zero.
All six runtime meshes also compare against fresh original-QC external-asset
compilations with no render or supported-animation metadata differences, using
the unchanged limits. Results: `test-output/runtime-source-validation/results.json`.
`test-output/runtime-fixes-validation-manifest.json` records the final executable,
tools, package and evidence hashes.
The runtime QC adds material bindings and white vertex colors to the float prop;
it does not round or replace its original positions.

The IK crash at `r5apex.exe+0x7C6E4D` was caused by the absent virtual-rig mapping.
Studio field 0x158 must be -1 for external asset linkage. A single-field research
control with the original chain completed both sequence probes; production output
and the final six-model run reproduce the result. External output now writes the
sentinel and the package checks matching rig/model bones and chains. Regressions
reject stale chains and older embedded-chain models lacking the sentinel.
This proves chain linkage and crash-free playback, not IK target solving or rules.

The float prop uses the installed S3 SKNC debug material
`opaque_normalz_front_sknc` (GUID `1421bd566ca23287`) and `$usevertexcolor`.
Its shader requires COLOR in addition to float positions and packed weights.
The preceding error-SKNC binding produced an oversized error surface; rigid float,
unpacked-input and alternative-material controls narrowed this to input compatibility.
No packed-position tolerance was relaxed. The final client photograph samples
`bend` at cycle 0.5, paused using the same API as R5R's model viewer, and visibly
shows the bent mesh. Exact textured appearance or per-vertex runtime parity is not
asserted by that screenshot.

Pose review exposed another defect: animation descriptor bit 0x20000 means usable
bone tracks, independently of the sequence's scale bit. Without it, cycles advanced
but the prop's attachment stayed fixed. The encoder now sets it for its explicit
bone channels and writes zero animation bases. All 25,405 surveyed S0-S3 animation
descriptor bases are zero; 24,556 have the bone-track bit. The final server `bend`
attachment samples move by many inches. The harness records attachment samples
and explicitly rejects advancing cycles with a static probe for this fixture.

Both native and legacy root-motion examples change origin during playback. Server
timing can lag a cycle by one tick; exact trajectory parity is not asserted. The
mixed `lean` blend remains at its default static pose; its animated endpoint is
not a live-runtime claim. Event dispatch and independent external-rig-only playback
remain unverified: render models retain embedded clips. IK rules/locks are not emitted.

All 581 installed S3 VG auxiliary counts match the studio mesh count. An isolated
concrete control did not draw with the auxiliary buffer omitted; zero-filled
48-byte records restored drawing. The writer allocates these records, native
shader descriptor bits, skinned bone palettes and optional packed positions.
The auxiliary fields remain unknown. Packed positions retain the existing
0.0001-inch render budget.

## Piecewise root motion and IK-chain evidence

The compiler now emits the native 44-byte piecewise movement records from explicit
`$legacymovement` extraction or `movementrecord` imports. Export preserves the
records and in-place local poses without applying extraction again. Native
frame-movement streams use the separate path described below; an `rm` request
combined with `$legacymovement` is rejected.
Tests cover 95-frame linear extraction, two imported movement blocks, changed-record
detection, malformed counts/spans/end frames, duplicate ends and nonfinite values.
The packaged example also exercises extracted translation/yaw over two blocks.

Raw native rig surveys found 106/122/121/138 rigs in S0/S1/S2/S3 (487 total),
with 71/83/80/92 IK chains (326 total), zero decoding errors. Every chain has three
links, type 0 and the exact scalar 0.8660253882408142 at offset 0x10. The compiler's
inherited 0.707 default was corrected to this cos(30 degrees) value.
Explicit source overrides remain available.

All 271 rigs containing chains were rebuilt as skeleton-only models; all 326 chain
descriptions compare exactly, matching link indices through bone names. No model
render data or external rig dependency graph is claimed equivalent by that test.
Authored regressions additionally exercise a skipped twist bone, a nonzero knee
direction, explicit/default scalar values and malformed link indices. Generated
sources use noautoik: IK-rule emission and runtime solving are not implemented.

A separate owned S0 survey decoded 3,301 raw sequence files / 5,701 animation
descriptors: 2,902 frame-movement pointers and zero piecewise movement records.
Piecewise motion therefore has layout-reference and authored round-trip evidence,
not retail piecewise root-motion parity or runtime movement proof. Reports are motion-ik-native-survey.json and ik-native-rebuilds.json
under test-output; they record source/compiler/reader hashes. The research-only
extractor copies and game-derived inputs/outputs are not distributed.

Movement-record and chain floats use the existing metadata tolerance 0.000001.
The native rig rebuild comparison was exact. No comparison limit was widened.
motion-ik-validation-manifest.json retains the preceding build's source/tool/report/
package hashes and automated check counts.

## Native frame-movement evidence

The native encoder writes mode-0 scalar packets in 30-frame sections. Extracted
motion uses the same grid to remove movement from the roots. Tests cover all four
profiles, 65-frame extraction, section boundary/guard samples, yaw, raw delta clips,
single-frame/zero channels, fixed text tracks, all 20 packet modes at multiple t
values, native sidecar import/export, changed-sample detection, conflicting options,
quantization failure and malformed flags/scales/counts/offsets/packet spans.
Frame-motion limits are 0.001 inches and 0.005 degrees. No existing limits changed.

All 13,025 streams in extracted owned S0-S3 common sequence assets decode without
errors (1,292,880 frames). Per-season stream/frame counts:

| Profile | Streams | Frames | Streams with multiple sections |
| --- | ---: | ---: | ---: |
| S0 | 2,902 | 288,411 | 955 |
| S1 | 3,022 | 305,147 | 1,003 |
| S2 | 2,929 | 281,611 | 950 |
| S3 | 4,172 | 417,711 | 1,252 |

The survey exercises modes 0..19 and finds no mode-1 signed16 overflows. Every
stream was imported through the compiler into a zero-pose stub animation. The
rebuilt movement payload and every decoded movement sample compare exactly.
This measures compressed-stream preservation, not independently regenerated
polynomial compression, source bone-animation equivalence, external rig loading,
RPak baking or in-game root motion. The authored tests separately exercise the new
mode-0 encoder and extraction.

Local reports `frame-native-survey.json`, `frame-native-imports.json` and
`frame-render-rebuilds.json` record source/compiler/tool hashes. The same 48 cached
render sources also pass again with zero render error and no new differences.
`frame-validation-manifest.json` records final tool, report and package hashes.
Game-derived reports, sidecars, stub output and extractor copies stay ignored.

## Animation metadata export

Native export now preserves rectangular blend grids, pose parameters/keys, per-blend
FPS and flags, sequence bone weights, bounds, fades, activity names/modifiers, and
numeric/named events. A new eventcycle source option retains fractional normalized
timing without rounding it to an integer frame. Exported sequence playback flags
remain separate from the named animations' flags.

Regressions cover a 3x2 grid with nonuniform pose keys, 35-frame sectioned tracks,
independent blend FPS/frame counts/loop flags, custom bone weights, long event
options, fractional cycles, single-frame NaN events and delta tracks. Negative
checks detect changed timing/poses/events, malformed grids, invalid cycles,
unterminated options and unsupported event types. Layers now fail explicitly:
the inherited TF2 layer layout is not valid native asset-GUID data.

The metadata comparator uses absolute 0.000001 for float metadata and checks
every blend frame at the existing authored-animation limits: 0.001 inches for
position, 0.0002 radians for Euler rotation (modulo a full turn), and 0.0016 for
scale. noforceloop is excluded from animation flag comparison because it controls
compilation. No previous threshold was increased.

The installed-asset descriptor survey decoded 390/454/469/649 sequences in S0/S1/S2/S3
with zero errors (animation-metadata-survey.json under test-output). All have zero
embedded blends, a 1x1 grid and no events or pose parameters. Reference descriptors
may omit the single-frame flag. They are not animation clips and export rejects
them rather than generating invented playback. Consequently authored data supplies
the blend/event round-trip evidence; this survey does not prove retail animation,
external-rig, event-dispatch or runtime equivalence.

## Installed-asset survey

All 1,789 studio structures and render geometry decode: 49,593,673 triangles
across all LODs, including the 559 models previously excluded for complex skinning.
These are the installed S0-S3 common RPaks and patch chains, not every map/skin pak.

| Target | Models decoded | Render triangles (all LODs) | Errors |
| --- | ---: | ---: | ---: |
| s0 | 360/360 | 9,477,600 | 0 |
| s1 | 420/420 | 10,386,145 | 0 |
| s2 | 428/428 | 11,918,028 | 0 |
| s3 | 581/581 | 17,811,900 | 0 |

The geometry survey above is retained evidence from the preceding complex-skinning
build (`a76eeac4...`), reader `1b1a802b...`; it was not rerun for this metadata change.
Reports are complex-native-survey-s0.json / s1.json and complex-survey-s2.json /
s3.json under test-output. They identify the actual reader hash. All vertex weight
spans, counts, bone indices and normalized sums are checked while decoding. A
successful decode does not establish animation-rig or runtime equivalence.

The original research extractor copied VVD bytes into VVC files for some S0/S1
assets. Strict VVC checks exposed 114/118 bad exports. The local-only research
copy was corrected to read the native vvcOffset, then both corpora were extracted
again into separate complex-native-s0/s1 folders. The final surveys above use those
corrected components. No comparison was relaxed, no game installation was modified,
and the extractor modification is not distributed.

## Weight encoding evidence

All 5,651,844 VVD vertices in S0/S1 complex-layout files have influence counts from
1 through 16 and satisfy sum(stored values) + count = 32768. Native packed weights
therefore decode as (stored + 1) / 32768. An independent byte-level comparison of
the original S0 VVD/VVW and S3 VG bird data reconstructs the same bone/weight values
for all 10,989 vertices, using the original VTX mapping. The VG final influence is
the remainder after decoded explicit weights, not after the raw stored integers.
Evidence: weight-facts.txt and complex-cross-format.json under test-output.

## Retail render rebuilds

Each profile rebuilds the earlier eight-model sample plus pilot_heavy_gibraltar,
pilot_light_support, pilot_light_wraith and pilot_heavy_caustic. These exercise
10/13/14/16 influences, larger skeletons, multiple materials and LODs. All 48 pass.
The previous four unsupported bird cases now pass; no earlier passing model newly
differs. Maximum measured errors across these runs:

- position: 0
- normal: 0
- uv: 0
- weight: 0

The fixed limits remain position 0.0001 inches, normal component 0.006, UV 0.00001
and weight 2/32767. None was increased. The native writer preserves normalized
integer sums and rejects unrepresentable weight ratios or index overflows.

These are explicitly render-only runs: physics/BVH, rigs and sequence metadata are
not preserved or compared. Full render reports live in complex-render-s0 through
complex-render-s3. complex-validation-manifest.json records the compiler, reader,
source/tool hashes, report hashes and all selected input companion hashes. Game
data, research tools and rebuilt assets stay ignored and are not distributed.

The animation-metadata build recompiled the same 48 sources: 12/12 pass per profile,
with zero measured position/normal/UV/weight error and no newly differing models.
These remain render-only checks. Reports are animation-render-s0 through s3;
animation-validation-manifest.json identifies compiler/tool/report hashes and
links the preceding input-companion manifest. The final validator also rechecks
those rebuilt files after its blend-count comparison was added; results are in
animation-render-revalidation.json. No corpus tool changed during a run.

The motion/IK build also recompiles the same 48 cached render exports, checking
original source hashes and cached input hashes. Results are in motion-render-rebuilds.json
with the actual executable/tool hashes; all 48 pass with zero measured render error
and no new differences. This remains render-only evidence.

The external-asset build recompiled the same 48 cached render exports: 12/12 pass
per profile, zero measured render error and no newly differing models. Inputs and
compiler/tool hashes are recorded in `asset-render-rebuilds.json`. These remain
render-only comparisons; no corpus tools were changed during the run.

## Native PHY (12 November 2026)

The early-Apex `.phy` was decoded from all 938 installed S0-S3 files (202/229/225/282;
every byte accounted for, `tools/phy54.py`) and is now written by the compiler for
`$collisionmodel` and `$collisionjoints`. Layout and rules are in the format notes.

Corpus: every installed model with a PHY was exported with `decompile54.py --render-only
--with-physics`, rebuilt and compared by `roundtrip54.py --render-only --with-physics`
(render validation plus `compare_phy54.py`). S0/S1 use the corrected complex-native
extractions. Compiler SHA-256
`f25c53c02a16241fd10495a134334d29507824f04310e8050850a142a064e2bd`; tools roundtrip54
`aeb52222...`, compare_phy54 `3cfbb654...`, decompile54 `4dca0626...`, phy54
`90dd10e5...`. Limits: vertices and bounds 0.0001 in; centroids, radii and centres
0.0001 of the hull/solid size; inertia 0.0001 of its largest component; numeric
keyvalues 0.00001 relative. None was widened.

| Season | Pass | Differences |
| --- | --- | --- |
| S0 | 201 / 202 | tablet_mini |
| S1 | 228 / 229 | tablet_mini |
| S2 | 224 / 225 | tablet_mini |
| S3 | 280 / 282 | wood_gib01d; w_bloodhound_axe (not exported) |

All render comparisons in the run passed. Explained differences:

- tablet_mini (S0-S2): retail's stored hull point lies outside its own hull (its
  stored radius is -25.6). The rebuild stores the centroid, as S3 retail does.
- w_bloodhound_axe (S3): a retail hull is not a closed polyhedron (V - E + F = 5);
  the decompiler refuses it rather than exporting a different shape.
- wood_gib01d (S3): inscribed radius 0.83919 vs retail 0.835564. Its faces are not
  planar, and the retail plane rule is not established for 6 of 1,245 S3 hulls; the
  compiler's rule (Newell normal, plane through the outermost face vertex) matches the
  other 1,239.

Fixes found by the corpus: polygon volume, centroid and inertia are measured from the
stored faces fanned from their first vertex (bent faces differ from the convex hull);
loops keep their source starting vertex; FLT_MIN-initialised bounds maxima; retail
`concave` editparams and `jointmerge` pairs are exported. A first comparison rounded
positions to 0.001 for face matching, which falsely failed marvin; faces are now
matched by nearest vertex and compared as ordered loops (winding included).

## BVH collision (12 November 2026)

The BVH block (studiohdr 0x214) is decoded: header, entries, packed and float
vertices, BVH4 nodes, triangle leaves (types 4/5), parallelogram quad leaves (6/7,
whose fourth corner is computed as b + c - a and often not stored) and leaf lists (3);
only the meaning of a small per-leaf table is open (format notes). All 3,865 S0-S3
entries decode to valid trees; every hull and solid entry encloses its retail PHY
solid's volume except wood_gib01c's, and every trace triangle and quad is a render
triangle or pair. The compiler writes leaves as retail does: quads for exact
parallelograms, triangles otherwise, and lists where a leaf has both. The compiler
writes the trace mesh (static props), the physics hull (`$collisionmodel`) or one entry
per solid in bone order (`$collisionjoints`), and the 0x1F0 box and 0x218 roles.

Corpus: every installed model with a BVH (S0 229, S1 272, S2 273, S3 354) was exported
(`decompile54.py --render-only --with-physics`), rebuilt and compared by
`roundtrip54.py`, which now runs `compare_bvh54.py` on every model with a BVH. Compiler
SHA-256 `394d5e4ce84c88c825863f76767dca7069bcf1077e799b96776c1524d117feb1` (writes quad
and list leaves); tools roundtrip54 `2d5811c8...`, compare_bvh54 `50184367...`, bvh54 `819009db...`,
compare_phy54 `3cfbb654...`, decompile54 `ff535740...`, phy54 `90dd10e5...`.

The comparison checks, for every model: entry roles and count, the 0x1F0 box (0.0001
in), a valid rebuilt tree (every child box contains its geometry, each node reached
once), and that the rebuilt trace mesh is its own LOD 0 render triangles with matching
winding (1.5 packing steps). Against retail, per entry: trace meshes triangle by
triangle with winding (1.5 steps plus the model's measured retail offset, at most 0.001
in), a retail quad matching when its two triangles under either diagonal do; hulls
and solids by vertex set (1.5 steps) and enclosed volume (0.1%). Every one of the
3,865 retail entries was compared; an entry the reader cannot decode is a difference,
never skipped. (Earlier runs, with a triangle-only compiler and before quads and lists
were decoded, gave the same result.)

| Season | Pass | Differences |
| --- | --- | --- |
| S0 | 227 / 229 | tablet_mini (PHY), wood_gib01c |
| S1 | 270 / 272 | tablet_mini (PHY), wood_gib01c |
| S2 | 271 / 273 | tablet_mini (PHY), wood_gib01c |
| S3 | 351 / 354 | wood_gib01c; wood_gib01d (PHY); w_bloodhound_axe (not exported) |

- tablet_mini, wood_gib01d, w_bloodhound_axe: the PHY differences explained above; their
  BVHs compare equal (w_bloodhound_axe cannot be exported).
- wood_gib01c: hull volume -53.5881 vs retail -53.4481 (0.26%); the vertex sets match.
  A hull face is bent, and retail splits it along the other diagonal. Fanning faces
  from their first vertex matches the other 93 S0/S3 hull entries stored as plain
  triangles; no fan start, index rule or convexity rule matches all of them.

Found by the corpus: retail drops trace triangles whose corners share a stored position
(wood_gib01c has two in its render mesh); retail orders jointed entries by bone index
(bird); the hull box at 0x6C must be kept exactly on export (`$bbox`), since collision can
widen a computed box. Two comparison defects were fixed before the final run: node boxes
are checked only on the rebuilt tree (retail shares child nodes between slots), and
retail trace vertices sit up to 0.001 in above the stored render vertices.

### In game (R5R v2.6.52)

`tools/build_r5r_collision_test.py` builds an S3 package (RPak SHA-256
`35033d6a038b7204e0c7e1e6b48b8d116343f512ebf62368d2b0d0db693cb2c1`, compiler
`261be5b46cd43351f28c83577dce5c943448181ef381822bd64bcdc18872cc09`): static and physics boxes, a
physics box without `$keyvalues`, an
L-shaped step with and without a PHY, a box without collision, a physics box built with
`--no-bvh`, boxes of 16/32/64 in at 5/20/500 mass, a decompiled and rebuilt physics box,
a decompiled and rebuilt retail rocket (`bangalore_rockets_projectile`) and the retail
jointed bird (six solids) exported in full by `decompile54.py` and rebuilt unchanged,
with retail controls (`error`,
`coin`, `concrete_chunk02a`, the rocket and the bird). `ingame54.py --collision` spawns
trace targets as `SOLID_VPHYSICS` prop_dynamics 240 in above the ground (as R5R's map
editor does) and traces each point straight down three ways: an ordinary shot trace, a
solid-mask trace and a high-detail trace. It drops each physics model as a prop_physics
from 160 in onto one level spot found by a ground search, samples it for 8 s, traces it
and removes it; and turns each jointed model into a ragdoll. Expected heights come from
the compiled BVH entries. Final run: passed, exit code 0; 204 traces of each kind (99
ordinary and 149 high-detail ones checked against expectations), 8 drops and 2
ragdolls as declared. Report, netconsole and script logs:
`test-output/r5r-collision/evidence`.

- Ordinary traces follow the physics-hull entry: 98 grid traces over the physics box
  and the step-with-PHY hit at the hull's height (64 in, and on the step hull's slope);
  worst difference 0.057 in, one packing step. Models without a PHY are missed, retail
  `error` and `coin` too.
- High-detail traces follow the trace-mesh entry: 147 grid traces over the static box,
  the step and the step-with-PHY hit the trace mesh, worst difference 0.033 in, and the
  retail `error` and `coin` controls hit theirs 0.032 in above their decoded tops, like
  the rebuilds. On the step with a PHY the two differ as the entries do: half an inch
  onto the low side an ordinary trace stops at 63.31 on the hull's slope, a high-detail
  one at 16.03 on the exact L.
- The box without `$keyvalues` gets the compiler's default `prop_data` (retail's form)
  and lands like the others; before that default a prop_physics without prop_data was
  deleted on spawn.
- Every physics drop settles on the ground within 0.13 in at under 0.07 in/s and is then
  hit by a trace. The rebuilt rocket rests at 6.719 in, exactly where retail's does.
  Without the BVH the box still lands but no trace hits it, so traces use the BVH.
- Jointed: the bird exported and rebuilt by these tools and the retail bird both switch
  to ragdolls (the server entity is replaced within 0.3 s). The export keeps retail's
  clip-less `ragdoll` descriptor (ACT_DIERAGDOLL); built that way for R5R, BecomeRagdoll
  crashed (integer divide by zero, r5apex.exe+0x1CAEFA), and with the bind-pose clip that
  `--external-assets` now embeds it switches like retail's. Ragdoll motion was not
  measured: R5R has no server `prop_ragdoll`, the client copy of the prop disappears at
  the switch, the ragdoll is not found by `GetClientEntArrayBySignifier` under ten
  candidate classes, and screenshots did not capture the birds. Jointed
  BVH entries are not traced on a standing prop_dynamic, retail's or rebuilt: shot
  traces hit only retail's hitboxes, solid-mask traces neither.
- Surfaces: traces report the model's `$surfaceprop` (our concrete and metal boxes 15
  and 22; retail `concrete_chunk02a` 51 rock, its model surface, not its BVH table's 15).
- Defects found in game: the leaf header's high 16 bits are a 1024-vertex page, not a
  vertex number (every leaf after the first traced at the wrong place on the step; now
  fixed, and `crypto_drone_holo`'s 2,812 triangles decode only this way); prop_physics
  needs a `prop_data` keyvalue, without which the game deletes it; the packager now
  stages the PHY, which RePak requires; a jointed model needs an `ACT_DIERAGDOLL`
  sequence to become a ragdoll (the render-only export drops it, so the test adds one).

## Full native export (12 November 2026)

`decompile54.py` now exports model keyvalues, hitbox sets and clip-less (reference-pose)
sequence descriptors, and accepts the external-rig include count of -1, so the full
(non-render-only) export covers most retail models; `roundtrip54.py` compares keyvalues
byte for byte, hitbox sets (bones, groups, names, crit overrides, hit data groups,
boxes within 0.0001 in) and, in full mode too, the PHY and BVH. The compiler writes
retail's compact keyvalue form with a default `prop_data`.

Corpus: every installed model, full mode (S0 360, S1 420, S2 428, S3 581), and every
model with a BVH in `--render-only --with-physics` mode, as before. Compiler SHA-256
`8abcc24daaadfcc634b63d6711630aa12028f4d3cec1cd2b4a02ff5e7b1f222e` (the final
`261be5b4...` differs only in `--external-assets` output, which these runs do not use);
tools roundtrip54 `6e5e2410...`, decompile54 `9abe2055...`, compare_bvh54 `b5fbf041...`,
bvh54 `819009db...`, compare_phy54 `3cfbb654...`, phy54 `90dd10e5...`, validate54
`75a1a51a...`, mdl54 `294ecb9e...`. Limits unchanged.

| Season | Full mode: pass / refused / differ | Render + physics: pass / 1,128 |
| --- | --- | --- |
| S0 | 260 / 97 / 3 | 227 / 229 |
| S1 | 315 / 102 / 3 | 270 / 272 |
| S2 | 324 / 102 / 2 | 271 / 273 |
| S3 | 419 / 160 / 2 | 351 / 354 |

- Refused (460, plus w_bloodhound_axe): RUI panels (346), procedural bones (81) or
  both (33), which the native export does not support yet; the decompiler says so.
- Differences: the PHY and BVH cases explained above (wood_gib01c, tablet_mini,
  wood_gib01d), and `pov_pilot_medium_bloodhound_legendary_02` in S0 and S1, whose
  normals differ by up to 0.103 (limit 0.006). This first-person model had not been
  rebuilt before (the export refused its include count of -1); the cause is not known.
- Found by this run: retail clip-less descriptors exist with and without the
  single-frame bit, so the export keeps it as stored and the compiler adds it only to
  sequences with clips.
- Known limit: a rigid physics model with an embedded first animation round-trips its
  PHY only within the animation's rotation quantization. The compiler poses the rigid
  hull by animation 0 frame 0 (studiomdl's rule), using the exact source angle; the
  native format stores rotations in steps of 0.00019175 rad, in which the root's 90
  degrees (8,191.75 steps) cannot be stored exactly, so a full rebuild sees it 4.8e-5 rad
  off (the physics example: 0.0022 in at 45 in radius). No retail model is affected
  (none embeds a first animation in a rigid physics model); the package check
  round-trips the physics example in render + PHY mode.

## RUI panels, jiggle bones and linear bones (15 November 2026)

The compiler and decompiler now handle RUI panels and jiggle bones (layouts in the
format notes), and every multi-bone model gets retail's linear bone table. The
round trip compares RUI panels exactly, jiggle records byte for byte with the per-bone
slot table up to the bone-controller offset, and the linear table (present when
retail's is, and a copy of the bone records).

Corpus: every installed model in full mode and every BVH model in render + PHY mode, as
above, with compiler `00f58e02...`; tools roundtrip54 `e33b0aaa...`, decompile54
`01f63495...`, validate54 `84f06491...`, mdl54 `59b29391...`, PHY/BVH tools unchanged.
Limits unchanged.

| Season | Full mode: pass / refused / differ | Render + physics: pass / 1,128 |
| --- | --- | --- |
| S0 | 358 / 0 / 2 | 227 / 229 |
| S1 | 418 / 0 / 2 | 270 / 272 |
| S2 | 426 / 0 / 2 | 271 / 273 |
| S3 | 578 / 1 / 2 | 351 / 354 |

- All 379 RUI models and all 114 jiggle-bone models (33 have both) pass; nothing is
  refused for RUI or procedural bones any more.
- The remaining differences are the retail PHY/BVH anomalies explained above
  (tablet_mini, wood_gib01c, wood_gib01d) and the refused w_bloodhound_axe hull. No
  model newly differs.
- The normal difference of `pov_pilot_medium_bloodhound_legendary_02` (and the
  `ptpov_lstar` and `ptpov_at_rifle_legendary_01` differences seen once their RUI and
  jiggle bones could be exported) was the validator's: it ordered triangles by position
  and UV only, so coincident duplicates bound to different bones (lstar's glow shell)
  could pair crosswise. Normals and weights now break those ties; the limits are
  unchanged and each model matches within them.

In game (R5R v2.6.52): `tools/build_r5r_jiggle_test.py` packages the retail charm_nessy
(three jiggle bones) decompiled and rebuilt, the same rebuild without its jiggle bones,
the rebuild with its include count patched to an embedded rig (retail's form for the
charm), and the retail ptpov_vinson (20 RUI panels, one jiggle bone) rebuilt (RPak
SHA-256 `640f18b9...`). `ingame54.py --jiggle` (`709d0512...`) spawns them on the server
and client, then steps the charms 30 units sideways and samples MENU_CAMERA_FOCUS (on
the last jiggle bone) relative to the prop every frame for 4 s, beside the installed
retail charm. The run passed (exit 0): all spawns and client props were created, and

| Charm | Probe peak after the step | Last 0.5 s |
| --- | --- | --- |
| rebuilt (external rig) | 0.4147 | 0.0004 |
| rebuilt, embedded rig | 0.4147 | 0.0004 |
| rebuilt without jiggle bones | 0.0000 | 0.0000 |
| retail (installed) | 0.1714 | 0.0000 |

Found by these runs, each confirmed against retail and fixed before the passing run:

- R5R crashed (r5apex.exe+0x1CA771, an animation descriptor read through a wrong base)
  whenever the rebuilt vinson and another rebuilt model were drawn together. Bisected
  to models without retail's linear bone table (present in all 677 multi-bone retail
  models); with the table written the crash is gone.
- With the jiggle records also written into the external rig, the rebuilt charm's
  jiggle bones were never posed (probe at the prop origin); with them removed but the
  bones' usage flags kept, its pose was NaN. Retail rigs keep no procedural bones and
  only flag 0x20 on those bones (10 S3 rigs exported with RSX); in that form the
  external-rig charm swings exactly as the embedded one does.
- The bone-controller offset is the unpadded end of the per-bone slot table in all 114
  retail jiggle models; the compiler had padded it to 4.

The rebuilt charms rest at the bind pose stored in the model (the probe at
(0.357, -0.33, 0), as the pose-to-bone matrices give); the installed retail charm,
which has no sequence asset and an empty `ref`, rests rotated from it in R5R, so the
swing amplitudes are not compared. The vinson viewmodel's geometry is not in the
screenshots (it is placed relative to the eye), so its rendering and its RUI panels
(read by weapon scripts) are not shown in game; it loaded, spawned and was drawn
alongside the charms without errors.

## Remaining limitations

- Measuring client-side ragdoll motion in game (not reachable from R5R scripts),
  non-jiggle procedural bones (none in S0-S3), RUI panels in a weapon's view and the
  rule for the v54 RUI mask count, importing arbitrary
  existing rig dependencies, native asset-GUID layers, IK rules, transition
  nodes and followers. Export also rejects sequence keyvalues, transitions and
  procedural weight fixups, and unknown animation/sequence flags or event types.
- S3 RPak loading and limited embedded playback/rendering have live evidence.
  Other profiles require a matching-season packager. External-rig-only playback,
  arbitrary external dependencies and general shader compatibility remain unverified.
  Exact per-vertex runtime geometry equivalence is not established.
- Early profiles retain the 256-bone and 16-influence limits. Unshareable VG
  extra-weight lists with starting indices above 65535 fail explicitly. Extreme
  positive weight ratios that exceed the fixed quantization budget also fail.
- Render comparisons do not establish material GUID, skin-family, tangent, bounds,
  arbitrary sequence metadata, procedural or collision equivalence. Compact retail
  animation decoding still needs broader external-rig validation.
- Historical TF2 corpus reports/tests are reference material, not Apex evidence.
  No R5 release has been tagged or published.
