# Apex early-season compiler validation - 6 November 2026

Experimental development build with native external rig/sequence output and S3
RePak packaging, native frame movement, piecewise root motion, IK-chain export,
complex skinning and animation metadata round trips. Offline structure/render and
authored-animation checks pass. A six-model RPak bake succeeds. R5R was launched
from a separate test directory but Windows displayed a firewall prompt before the
netconsole became available; no models were spawned and no runtime model pass is
claimed. This is not a stable release or proof of full Apex model equivalence.
Retail and later self-hostable seasons remain future targets.

Windows x64 MSVC Release: build/r5studiomdl.exe
SHA-256: `7b66989d02f8807581ee2d4311aaa4a757e768e248b8f5bf5e75231c3b3b5b52`.
Independent reader SHA-256: `294ecb9eff3f705a0e35c24fa8d83b77575abebcec3353c3f2506571bd188f69`.

## Automated checks

- All 51 native compiler/packaging/runtime-harness regressions pass on ordinary Python 3.10 and locked uv/Python 3.14.
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

The installed RePak built six authored example models into 23 assets: six models,
six rigs and eleven sequences. The mandatory streaming file contains six VG assets.
RePak SHA-256: `afaf61c9f462444adbe49d87a494a63bdc813be8945d8857c9d692847f1a5ca2`.
RPak SHA-256: `491d5e0ae0dc5577ddb774e6f9a5b3a6acbb09a4a8a54d726cf53ac4102ced11`.
Streaming SHA-256: `5bd0797a4c27b70d17d722ded41c1c23a548dbbae76ced056a0d745429cce7ac`.
Build map, tool hashes, source hashes and per-model sequence paths are recorded in
`test-output/r5r-authored/pak/r5c_authored.report.json`. This is successful packaging,
not evidence that the runtime has resolved or played the new assets.

The first isolated R5R v2.6.52 startup attempt used
`F:\Games\Apex Detours\r5c-test-runtime`. Configs/platform scripts/mods were copied;
large resource data uses links to the installed R5R LIVE assets. Current retail was
not modified or launched. The SDK netconsole timed out while a Windows firewall
permission prompt was visible. Live model loading, material resolution, external
rig linkage, skinning, root-motion behavior and event dispatch remain pending.
The experimental harness records explicit failures for missing spawns/sequences
or incomplete playback samples; collecting those samples alone does not establish
geometry or motion equivalence. Its generated Squirrel probe still needs its first
successful runtime execution.

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

## Remaining limitations

- Native PHY/BVH collision and ragdolls, procedural bones, RUI, importing arbitrary
  existing rig dependencies, native asset-GUID layers, IK rules, transition
  nodes and followers. Export also rejects sequence keyvalues, transitions and
  procedural weight fixups, and unknown animation/sequence flags or event types.
- RPak baking/streaming/relocations, material dependencies, shader compatibility
  and runtime entity behaviour remain unverified. The S3 RePak bake succeeds; other profiles still require
  a matching-season packager. No runtime compatibility claim accompanies this build.
- Early profiles retain the 256-bone and 16-influence limits. Unshareable VG
  extra-weight lists with starting indices above 65535 fail explicitly. Extreme
  positive weight ratios that exceed the fixed quantization budget also fail.
- Render comparisons do not establish material GUID, skin-family, tangent, bounds,
  arbitrary sequence metadata, procedural or collision equivalence. Compact retail
  animation decoding still needs broader external-rig validation.
- Historical TF2 corpus reports/tests are reference material, not Apex evidence.
  No R5 release has been tagged or published.
