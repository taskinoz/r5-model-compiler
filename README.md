# r5-model-compiler

`r5studiomdl` compiles QC with SMD or DMX sources into early **Apex Legends MDL v54**
assets. This is the experimental R5 sibling of
[r1-model-compiler](https://github.com/taskinoz/r1-model-compiler) and
[r2-model-compiler](https://github.com/taskinoz/r2-model-compiler).

**This is an initial development compiler, not a validated replacement for
Respawn's asset bakery.** Native render data and basic animation are implemented.
Native Apex physics/BVH and procedural bones are unfinished. External rig/sequence
output and an S3 RePak wrapper are available; runtime validation is pending. See [VALIDATION.md](VALIDATION.md).
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
sequences/blends/events, piecewise root-motion records, native frame movement, and native position/rotation/scale tracks. VG positions stay
float32; normals/tangents and weights use native packing. Basic IK chain descriptors
can be compiled, exported and compared, but runtime IK has not been checked.

The compiler rejects physics/collision, procedures, RUI, IK rules,
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

## Materials and loading

Default output contains model components. `--external-assets` additionally writes a
`.rrig` skeleton, numbered `.seqN.rseq` sequence assets and a `.assetset` manifest.
The render model contains the native empty `ref` sequence; animations are linked
through the external rig. The manifest records the target and sequence count so
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

For S3 / R5R, use a compatible, separately installed RePak:

```powershell
.\build\r5studiomdl.exe --target s3 --external-assets --material-guid models/electricalboxes/pipesmulti=0123456789abcdef -o out\box.rmdl examples\static_prop\box.qc
python -I tools\pack54.py --target s3 --repak "C:\Tools\RePak\repak.exe" --out out\pak --name r5c_models out\box.rmdl
```

Replace the example GUID with an asset available in the target game. Every
material slot must have a nonzero binding. The wrapper validates the component set,
stages model/rig/sequence asset paths, invokes RePak and writes a hashed report.
It produces an RPak v8 with model v10, rig v4 and sequence v7 assets plus the
mandatory streaming file. RePak and game data are not included in this repository.
A successful bake alone does not establish runtime compatibility. S0/S1/S2 RPak
packaging is not implemented by this wrapper.

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
must be handled manually. The first local attempt stopped at a firewall prompt;
no in-game model validation is claimed yet. Movement samples and screenshots need
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
is a compiler extension for those sequence flags; scale/single-frame bits are derived.
Default mode rejects known unsupported metadata, including sequence layers, IK rules/locks,
weight fixups and reference descriptors without embedded clips. `--render-only`
explicitly discards physics, BVH, rigs and sequence metadata. A render-only pass does
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
