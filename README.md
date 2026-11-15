# r5-model-compiler

`r5studiomdl` compiles QC with SMD or DMX sources into early **Apex Legends MDL v54**
assets. This is the experimental R5 sibling of
[r1-model-compiler](https://github.com/taskinoz/r1-model-compiler) and
[r2-model-compiler](https://github.com/taskinoz/r2-model-compiler).

**This is an initial development compiler, not a validated replacement for
Respawn's asset bakery.** Native render data and basic animation are implemented.
Native PHY physics, BVH collision, RUI panels and jiggle bones are implemented. External rig/sequence
output and an S3 RePak wrapper are available; limited R5R playback/render tests are
documented in [VALIDATION.md](VALIDATION.md).
No game assets, game binaries or extraction tools are distributed.

## Targets

Every invocation requires a target. The v54 number alone does not identify an Apex
format. Profiles describe the surveyed installed builds, not every hotfix in a season.

| Target | Asset generation | Output |
| --- | --- | --- |
| `s0` | early v54 / `mdl_` v8 | `.rmdl`, `.dx11.vtx`, `.vvd`, optional `.vvc` / `.vvw` |
| `s1` | early v54 / `mdl_` v8 | same component formats |
| `s2` | early v54 / `mdl_` v9 | `.rmdl`, `.vg` revision 1 |
| `s3` | early v54 / `mdl_` v10 | `.rmdl`, `.vg` revision 1 |

Retail and later self-hostable seasons are future profiles. `--target retail` fails.
Studio layout, animation encoding and vertex generation remain separate so later
profiles can implement their real formats.

## Compile

```powershell
.\build.bat
.\build\r5studiomdl.exe --target s0 -o out\box.rmdl examples\static_prop\box.qc
.\build\r5studiomdl.exe --target s3 -o out\animated.rmdl examples\animated_prop\animated_prop.qc
.\build\r5studiomdl.exe --list-targets
```

The siblings' `-game`, `-outdir`, `-path`, `-quiet`, `-verbose`, `-nop4` and Crowbar-style
arguments remain available. Output uses `.rmdl`. Keep each target in its own output
directory so companion sets do not mix.

Implemented: static/skinned meshes (up to sixteen influences per vertex), LODs, body
groups, attachments, hitboxes, skins, SMD and binary/keyvalues2 DMX input, basic
sequences/blends/events, piecewise root-motion records, native frame movement, and native position/rotation/scale tracks. VG supports float32 positions
or explicit packed positions; normals/tangents and weights use native packing.
Basic IK chain descriptors can be compiled, exported and compared. R5R has loaded
and played the authored chain-bearing model; solver equivalence is not established.

`$collisionmodel` and `$collisionjoints` write the native `.phy` beside the model (see
"Physics" below). `$uipanel` and `$jigglebone` write the native v54 RUI and jiggle-bone
data (see "RUI panels and jiggle bones" below). The compiler rejects non-jiggle
procedural bones (axis/quaternion interpolation, aim constraints), IK rules,
animation layers, transition nodes, followers, QC include-model rig imports and more than sixteen influences. Some
inherited QC commands remain unimplemented. No TF2 collision or animation structures
are presented as native Apex output.

SMD and DMX retain positive influences through bone remapping and LOD processing.
Models needing more than three influences automatically use native VVD/VVW for
S0/S1 or the VG extra-weight buffer for S2/S3. Packed weights sum to one; a ratio
that cannot fit the native quantization budget fails explicitly. See the
`complex_skinning/weighted_quad.qc` example for an animated four-influence mesh.

Sequence blocks accept `event <name/id> <integer frame> "options"`. For an event
between frames, use `eventcycle <name/id> <cycle> "options"`, where cycle is finite
and between 0 and 1 inclusive. This stores the native float cycle directly.
Numeric IDs use legacy event type 0; names use native event type 1024. The animated
prop example includes a two-way blend and a fractional-cycle event.

## Physics

`$collisionmodel` (one rigid solid, optionally `$concave`) and `$collisionjoints`
(one solid per bone, with `$jointconstrain`, `$jointmerge`, `$jointmass` and the other
joint options) compile to the early-Apex `.phy`: convex hulls with polygon faces,
per-hull centroid and inscribed radius, per-solid centre, inertia and bounds, and the
keyvalue text. S3 edges also record their two faces. The header records the PHY size
and the model checksum ties them together, so keep the `.phy` with its `.rmdl`.

Each convex piece may have at most 255 vertices, 255 faces and 32 corners per face; the
compiler fails rather than writing an unrepresentable hull. Retail measures volume and
inertia from the stored faces, and so does the compiler. `tools/phy54.py`
reads and checks a PHY; `tools/compare_phy54.py` compares two.

The model also carries a BVH collision block, which traces (bullets, line-of-sight)
use. Like retail, the compiler writes:

- for `$staticprop` (or `prop_data` with `"allowstatic" "1"`): a trace mesh of the LOD 0
  render triangles of each body part's default model;
- for `$collisionmodel`: the physics hull, as triangles;
- for `$collisionjoints`: one entry per solid, in bone order.

Coordinates are packed into int16 on a power-of-two grid around a whole-inch origin; a
model too large for packing uses float vertices. As in retail, flat parallelograms are
stored as quads and mixed leaves as leaf lists. `tools/bvh54.py` reads every retail
leaf type and checks a BVH; `tools/compare_bvh54.py` compares two. `--no-bvh` omits
the block, for diagnostics only.

Runtime use in R5R (see VALIDATION.md for what was measured):

- Spawn a static model as a `prop_dynamic` with `SOLID_VPHYSICS`, as R5R's map editor
  does. Ordinary traces (`TraceLine`) hit its physics hull, so give it a
  `$collisionmodel` if bullets should stop on it; `TraceLineHighDetail` hits the exact
  trace mesh, with or without a PHY.
- A physics model spawns as a `prop_physics`, which needs a `prop_data` keyvalue or
  the game deletes it. The compiler always writes one, as retail does in every model:
  `base` comes from `$keyvalues { prop_data { "base" "Metal.Medium" } }`, else it is
  empty. Keyvalues are stored in retail's compact form.
- A jointed model becomes a ragdoll (`BecomeRagdoll`) only if a sequence has the
  `ACT_DIERAGDOLL` activity, as retail's `ragdoll` sequence does. Retail stores it as a
  reference-pose descriptor (no clip); write that as
  `$sequence "ragdoll" { referencepose activity ACT_DIERAGDOLL 1 }` (it needs a `$body`
  before it). `--external-assets` builds embed a one-frame bind-pose clip in such a
  sequence, as R5R divides by its frame count otherwise; plain builds keep retail's
  descriptor, and its sequence asset always carries the clip.
- Traces report the model's `$surfaceprop`.

```powershell
.\build\r5studiomdl.exe --target s3 -o out\physics_box.rmdl examples\physics_prop\physics_box.qc
python tools\phy54.py out\physics_box.phy --target s3
python tools\bvh54.py out\physics_box.rmdl
```

## Piecewise root motion and IK chains

Use `$legacymovement` with animation controls `LX`, `LY`, `LZ`, `LZR` or
`walkframe <end frame> <controls...>` to extract piecewise motion into native
44-byte movement records. Root bone samples retain the remaining local pose.
The `root_motion/walking_triangle.qc` example has two movement blocks and an IK chain.
For exact record import, animation options also accept:

```text
movementrecord endFrame flags v0 v1 yaw directionX directionY directionZ positionX positionY positionZ
```

Records use animation-local frame numbers, normalized-block speed coefficients,
yaw in degrees and cumulative position in inches. End frames must increase and
remain within the clip; values must be finite. Export preserves records without
extracting motion a second time. This is a legacy piecewise path: the surveyed
S0 sequence assets instead use frame-movement streams.

For native frame movement, use `rm` (aliases `rootmotion` and `framemovement`)
on an animation to extract translation and yaw relative to its first frame.
Without `$legacymovement`, `LX`/`LY`/`LZ`/`LZR` and `walkframe` also produce native
frame streams. `root_motion/native_triangle.qc` demonstrates this path. Native
movement cannot be combined with `$legacymovement` or `$staticprop`.

`fmtrack "track.txt"` imports editable movement: four float scales on the first
line, then X/Y/Z in inches and yaw in degrees for every animation frame. Roots
must already be in place. Authored streams use native raw scalar packets and
30-frame sections, including a boundary sample. Quantization must stay within
0.001 inches and 0.005 degrees; samples that cannot meet this budget fail.

`fmstream "clip.fm54"` imports a validated native stream exported by
`decompile54.py`. The sidecar contains `FM54`, a little-endian uint32 frame count,
and the native payload. It preserves compressed polynomial packets without
re-quantizing them. Imported tracks must match the animation frame count and
cannot be combined with motion extraction or movement records. Raw stream
preservation does not imply a polynomial encoder or runtime playback validation.

`$ikchain leg foot links hip knee foot knee 1 0 0 angle_unknown 0.8660254` names
three explicit links, permitting intervening twist bones to be skipped. Omit
`links` to use the end bone's parent and grandparent. `knee` stores the first link's
direction; `angle_unknown` is the stored scalar, not an angle in degrees. Its
early-Apex default is cos(30 degrees), verified over 326 native chains. Use
`noautoik` on animations with chains: automatic release rules and explicit IK rules
are still unsupported. IK locks, asset dependencies and runtime solving are not
established by chain-field comparisons.

## RUI panels and jiggle bones

`$uipanel "name" [hash] { ... }` takes TF2's syntax (`parent`, `vertex`, `face`,
`bounds`) with one to two parents and no `ccw` (v54 panels have no winding flag; it is
refused). Two v54 options are stored verbatim: `facemask 0xNNNN` (one per face, default
0xffff) and `maskcount N` (default the face count, at most the face count).

`$jigglebone` takes studiomdl's syntax. The records are written in `$jigglebone` order,
which is the order the tables use. v54 additions:

- `tip_friction X` in the `is_flexible`/`is_rigid` section (the float after tip mass);
- an empty `is_rigid { }` before `is_flexible { ... }` sets both bits, as retail does;
- `stored_angle_limit A`, `stored_yaw_limits MIN MAX`, `stored_pitch_limits MIN MAX`
  store limit values without enabling the constraint;
- `base_values { ... }` sets the base-spring fields without enabling the spring;
- `bone_byte N` overrides the record's bone byte (default: the bone's own index).

Jiggle angles are converted in double precision, so exported angles (written with 17
significant digits) rebuild to the same floats. A model with jiggle bones may have at
most 255 bones.

## Materials and loading

Default output contains model components. `--external-assets` additionally writes a
`.rrig` skeleton, numbered `.seqN.rseq` sequence assets and a `.assetset` manifest.
The render model retains embedded playback clips and reserves index zero for the
native empty `ref` sequence. The native external-rig sentinel enables the runtime
virtual-rig mapping, including IK chains. Separate rig/sequence-only playback is not yet proved.
The manifest records the target and sequence count so
stale sequence files cannot enter the package. This output is available for all
four profiles. Importing arbitrary existing rig dependencies through QC is still
unsupported.

`-game` chooses an output directory. The explicit packaging and runtime tools below
perform the additional steps. Existing material assets are required.

Bind a material to an existing asset with a repeatable option:

```powershell
.\build\r5studiomdl.exe --target s3 --material-guid models/my_material=0123456789abcdef -o out\box.rmdl box.qc
```

Unbound slots contain zero GUIDs for a downstream packager to resolve. Binding does
not create a material or validate RPak dependencies.

The stored slot name must match the bound material; use `$renamematerial` when
binding an existing material with a different name. `--material-type slot=rgdp`
sets its shader family. Supported families are `rgdu`, `rgdp`, `rgdc`, `sknu`,
`sknp`, `sknc`, `wldu`, `wldc`, `ptcu`, `ptcs`. The surveyed RGDP/SKNP shaders require
`--packed-positions` (S2/S3 only). This uses the native 1/1024-inch position grid
and rejects coordinates outside its range or exceeding 0.0001-inch error.

The complete vertex layout must also match the shader. For example, the installed
S3 `opaque_normalz_front_sknc` debug material accepts float positions and requires
vertex colors. A runtime copy of the animated-prop QC can use:

```text
$usevertexcolor
$renamematerial "models/electricalboxes/pipesmulti" "opaque_normalz_front_sknc"
```

Bind that slot with `--material-type opaque_normalz_front_sknc=sknc` and
`--material-guid opaque_normalz_front_sknc=1421bd566ca23287`, without packed
positions. `$usevertexcolor` supplies white colors for SMD vertices. This tested
debug binding preserves the original geometry; it does not create a textured material.

For S3 / R5R, use a compatible, separately installed RePak:

```powershell
.\build\r5studiomdl.exe --target s3 --external-assets --material-guid models/electricalboxes/pipesmulti=0123456789abcdef -o out\box.rmdl examples\static_prop\box.qc
python -I tools\pack54.py --target s3 --repak "C:\Tools\RePak\repak.exe" --out out\pak --name r5c_models out\box.rmdl
```

Replace the example GUID with an asset available in the target game. Every
material slot must have a nonzero binding. The wrapper validates the component set,
stages model/rig/sequence asset paths, invokes RePak and writes a hashed report.
A model with physics needs its `.phy` beside it; the wrapper checks its size and
checksum against the model and stages it for RePak.
It produces an RPak v8 with model v10, rig v4 and sequence v7 assets plus the
mandatory streaming file. RePak and game data are not included in this repository.
A successful bake alone does not establish runtime compatibility. S0/S1/S2 RPak
packaging is not implemented by this wrapper.
Embedded IK chains require the native external-rig sentinel written by
`--external-assets`; recompile older outputs. The packager checks that the model
and rig contain matching chain descriptions. IK rules and locks remain unsupported.

The experimental Windows harness prepares a separate R5R directory and records
spawns, every sequence lookup, playback/movement samples, optional `probe`
attachments and a screenshot:

```powershell
python -I tools\ingame54.py --game "F:\Games\R5R" --runtime "F:\Games\R5C-Test" --pak out\pak\r5c_models.rpak
```

Use a new directory on the same volume as R5R. Large assets use hard links or
directory junctions; configs, platform scripts and mods are copied. The harness
requires the package report, checks package hashes, uses offline settings and a
loopback SDK netconsole, and refuses to start alongside another game process.
It exits nonzero for startup failures, missing spawns/sequences or incomplete
samples. The report and netconsole log are written in the isolated directory.
`--keep-open` leaves that test game open for inspection. Windows security prompts
must be handled manually. R5R v2.6.52 has loaded the authored package and played
its sequences; see VALIDATION.md for the scope and remaining limits.
Movement samples and screenshots need
review before claiming geometry or root-motion equivalence.

## Inspect, export and validate

Python 3.10+, standard library only. Scripts support `-I` isolation. Export raw data
from your own installation with a compatible extractor; keep companions together.

```powershell
python -I tools\mdl54.py --target s0 out\box.rmdl
python -I tools\decompile54.py --target s3 out\animated.rmdl out\sources
python -I tools\validate54.py --target s3 out\animated.rmdl
python -I tools\roundtrip54.py --target s3 --compiler build\r5studiomdl.exe --out test-output\examples out\animated.rmdl
python -I tools\survey54.py --target s0 extracted\models --geometry --out test-output\survey.json
```

`decompile54.py` exports QC, keyvalues2 DMX meshes with preserved corner identities,
and SMD animations. Supported animation export includes rectangular blend grids,
pose parameters/keys, per-blend FPS and flags, numeric/named events, fades, activity
names/modifiers, bounds and sequence bone weights. Named `$animation` definitions
keep animation settings separate from sequence playback flags. Exported `seqflags`
is a compiler extension for those sequence flags; scale/single-frame bits are derived
(a clip-less descriptor keeps its single-frame bit as stored). Descriptors without a
clip (retail `ref` and `ragdoll`) export as `referencepose` sequences. Model keyvalues
and hitbox sets (unless generated) are exported in every mode, and an include-model
count of -1 (the external-rig linkage most retail models use) is accepted.
Default mode rejects known unsupported metadata, including sequence layers, IK rules/locks,
weight fixups and non-jiggle procedural bones. RUI panels and jiggle bones are
exported. `--render-only`
explicitly discards physics, rigs and sequence metadata; add `--with-physics` to
keep the PHY. The BVH is not exported: the compiler rebuilds it from the render mesh
(`$staticprop` trace mesh) and the PHY solids, and `roundtrip54.py` compares it with
`compare_bvh54.py`. A render-only pass does
not establish full-model equivalence or runtime compatibility.

Default `roundtrip54.py` runs compare supported animation metadata, piecewise
movement records, native frame streams, IK-chain fields and every frame
of every blend as well as render geometry. To request the same checks directly,
use `validate54.py --animation-metadata --against original.rmdl`. Event cycles and
numeric metadata use an absolute tolerance of 0.000001; full-frame position,
rotation and scale limits are 0.001 inches, 0.0002 radians and 0.0016 respectively.
Frame-movement limits are 0.001 inches and 0.005 degrees; validation reports their
maximum errors separately. Render-only runs keep their narrower scope. External asset bytes are covered by authored regressions; runtime rig loading and
event dispatch remain unverified.

The v53 helpers at tools/mdl53.py, decompile53.py and phy.py supply shared binary,
math and source-export utilities. Their TF2 commands and historical tests/docs are
not Apex validation.

## Build and package

```powershell
.\build.bat
Push-Location build; ctest --output-on-failure; Pop-Location
python -m unittest discover -s tests -p "test_*.py"
uv run --locked python -m unittest discover -s tests -p "test_*.py"
.\tools\package.ps1
.\tools\check_package.ps1
```

CI follows R1: build, CTest, locked uv tests, packaging and clean-extraction checks.
The ZIP includes the compiler, native tools, docs and six authored examples. The
package check compiles and round-trips all six for all four targets, including
supported animation metadata and full-frame blend comparisons. Tags vX.Y.Z
require release-notes/vX.Y.Z.md and a matching pyproject.toml version; the release
workflow publishes the ZIP and SHA256SUMS. No R5 release has been tagged.

Derived from the MIT R2 compiler. GPL/AGPL references were consulted for format facts,
not copied into the compiler. See [format notes](docs/mdl-v54-format.md).
Not affiliated with Respawn Entertainment, Electronic Arts or Valve.
