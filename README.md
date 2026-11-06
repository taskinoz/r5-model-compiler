# r5-model-compiler

`r5studiomdl` compiles QC with SMD or DMX sources into early **Apex Legends MDL v54**
assets. This is the experimental R5 sibling of
[r1-model-compiler](https://github.com/taskinoz/r1-model-compiler) and
[r2-model-compiler](https://github.com/taskinoz/r2-model-compiler).

**This is an initial development compiler, not a validated replacement for
Respawn's asset bakery.** Native render data and basic animation are implemented.
Native Apex physics/BVH, procedural bones and external animation
rigs are unfinished. There is no in-game validation yet. See [VALIDATION.md](VALIDATION.md).
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
sequences/blends/events, and native position/rotation/scale tracks. VG positions stay
float32; normals/tangents and weights use native packing. Basic IK chain descriptors
can be emitted, but runtime IK has not been checked.

The compiler rejects physics/collision, procedures, RUI, root motion, IK rules,
animation layers, transition nodes, followers, external rigs and more than sixteen influences. Some
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

## Materials and loading

These are **model components**, not a loadable RPak. A matching-season asset packager/
baker and material assets are still required. `-game` chooses an output directory;
it does not inject a model, build an RPak or launch Apex.

Bind a material to an existing asset with a repeatable option:

```powershell
.\build\r5studiomdl.exe --target s3 --material-guid models/my_material=0123456789abcdef -o out\box.rmdl box.qc
```

Unbound slots contain zero GUIDs for a downstream packager to resolve. Binding does
not create a material or validate RPak dependencies. Nothing modifies the installs.

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
Default mode rejects known unsupported metadata, including sequence layers, IK,
weight fixups and reference descriptors without embedded clips. `--render-only`
explicitly discards physics, BVH, rigs and sequence metadata. A render-only pass does
not establish full-model equivalence or runtime compatibility.

Default `roundtrip54.py` runs compare supported animation metadata and every frame
of every blend as well as render geometry. To request the same checks directly,
use `validate54.py --animation-metadata --against original.rmdl`. Event cycles and
numeric metadata use an absolute tolerance of 0.000001; full-frame position,
rotation and scale limits are 0.001 inches, 0.0002 radians and 0.0016 respectively.
Render-only runs keep their narrower scope. External animation rigs and runtime
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
The ZIP includes the compiler, native tools, docs and four authored examples. The
package check compiles and round-trips all four for all four targets, including
supported animation metadata and full-frame blend comparisons. Tags vX.Y.Z
require release-notes/vX.Y.Z.md and a matching pyproject.toml version; the release
workflow publishes the ZIP and SHA256SUMS. No R5 release has been tagged.

Derived from the MIT R2 compiler. GPL/AGPL references were consulted for format facts,
not copied into the compiler. See [format notes](docs/mdl-v54-format.md).
Not affiliated with Respawn Entertainment, Electronic Arts or Valve.
