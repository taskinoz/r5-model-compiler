# Apex early-season compiler validation - 6 November 2026

Experimental development build with piecewise root motion, IK-chain export, native complex skinning and animation metadata round trips. These are offline
structure, render and authored-animation checks, not a stable release or proof of
full Apex model equivalence. No in-game run or RPak bake was performed. Retail and
later self-hostable seasons remain future targets.

Windows x64 MSVC Release: build/r5studiomdl.exe
SHA-256: `35e4429f6670f3b804021f5deac207faad048108871f20b381cc790aaab9d459`.
Independent reader SHA-256: `92a8b40792a230fc31fd49a6df8fce8238396a006696cb79cbb5cd379d078f88`.

## Automated checks

- All 38 native regressions pass on ordinary Python 3.10 and locked uv/Python 3.14.
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
- The clean ZIP contains five authored examples, including the new two-block root-motion
  and IK-chain example. All five compile, export, recompile and pass render comparisons
  on all four targets: 20 package round trips. These also compare supported
  animation metadata and every decoded frame in every blend, including the animated
  example's new blend/event. This is not full model or runtime equivalence.

## Piecewise root motion and IK-chain evidence

The compiler now emits the native 44-byte piecewise movement records from explicit
`$legacymovement` extraction or `movementrecord` imports. Export preserves the
records and in-place local poses without applying extraction again. Native
frame-movement streams remain unsupported and explicitly rejected, even when an
`rm` request is combined with `$legacymovement` (which previously could drop it).
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
not retail root-motion parity. No frame-stream decoder or runtime movement proof
is implied. Reports are motion-ik-native-survey.json and ik-native-rebuilds.json
under test-output; they record source/compiler/reader hashes. The research-only
extractor copies and game-derived inputs/outputs are not distributed.

Movement-record and chain floats use the existing metadata tolerance 0.000001.
The native rig rebuild comparison was exact. No comparison limit was widened.
motion-ik-validation-manifest.json records source/tool/report/package hashes and
the automated check counts for this build.

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

## Remaining limitations

- Native PHY/BVH collision and ragdolls, procedural bones, RUI, external rigs and
  sequence assets, native asset-GUID layers, native frame-movement streams, IK rules, transition
  nodes and followers. Export also rejects sequence keyvalues, transitions and
  procedural weight fixups, and unknown animation/sequence flags or event types.
- RPak baking/streaming/relocations, material dependencies, shader compatibility
  and runtime entity behaviour remain unverified. Output components still require
  a matching-season packager. No runtime compatibility claim accompanies this build.
- Early profiles retain the 256-bone and 16-influence limits. Unshareable VG
  extra-weight lists with starting indices above 65535 fail explicitly. Extreme
  positive weight ratios that exceed the fixed quantization budget also fail.
- Render comparisons do not establish material GUID, skin-family, tangent, bounds,
  arbitrary sequence metadata, procedural or collision equivalence. Compact retail
  animation decoding still needs broader external-rig validation.
- Historical TF2 corpus reports/tests are reference material, not Apex evidence.
  No R5 release has been tagged or published.
