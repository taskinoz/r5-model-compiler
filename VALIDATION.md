# Apex early-season compiler validation - 6 November 2026

This is the first experimental R5 implementation, not a stable release or a claim
of full Apex model/compiler equivalence. No in-game run or RPak bake was performed.
Latest retail is installed but is not a compiler target.

Windows x64 MSVC Release: build/r5studiomdl.exe
SHA-256: `c5a9b6316f06332bc3a8469a307f9b2d418fdb031070dde573ed63f3188d0dc0`.

## Automated checks

- 16 native authored-input regressions pass on Python 3.10 and locked uv/Python 3.14.
- Both CTest groups pass: inherited convex-hull math and native compiler regressions.
  The hull test is not Apex physics emission evidence; native physics is rejected.
- Native tests exercise all four profiles, native structure strides, geometry,
  weights, material GUID binding, multiple body models, nonascending LOD order,
  attachments, hitboxes, events with long options, blend descriptor offsets, delta
  animation, 95-frame section boundaries, full-frame position/rotation/scale values,
  decompile/recompile geometry, unsupported complex weights and malformed files.
- Position animation error is checked at 0.001 inches, rotation at 0.0002 radians,
  scale at 0.0016. Native quantization steps and an explicit 0.01-inch position
  budget are encoded in the compiler; exceeding representable range fails.
- Packaging compiles, exports and recompiles three authored examples for all four
  targets from a clean extraction, using only the ZIP contents. The independent
  reader checks every stored output animation frame for finite poses and compares
  render geometry. This check does not assert complete metadata equivalence.

## Installed-asset survey

Raw models were extracted with a local research copy of RSX 2.4.1 from the owner's
S0-S3 common RPaks, including their patch chains. No reference code or game assets
are shipped. These counts cover the common RPaks, not every installed map/skin pak.
Reports: test-output/survey-s0.json through survey-s3.json. Each records its actual
reader hash; the survey preceded a small reader addition for optional VVC attributes.

| Target | Studio structures parsed | Render geometry decoded | Unsupported complex weights | Triangles decoded (all LODs) |
| --- | ---: | ---: | ---: | ---: |
| s0 | 360/360 | 251 | 109 | 5,257,101 |
| s1 | 420/420 | 296 | 124 | 5,630,956 |
| s2 | 428/428 | 293 | 135 | 6,015,121 |
| s3 | 581/581 | 390 | 191 | 8,468,331 |

All reported geometry exclusions are explicit complex-weight rejections; they are
not passing models. Parsing a studio structure is not a render/animation/runtime
equivalence result. Complex models are common among characters and animated props.

## Retail render rebuilds

Reports under test-output/render-check-s0 through render-check-s3 test eight named
models per target: at_gib5, bangalore_rockets_projectile, bird, bullet_rifle,
caber_shot_thrown, caustic_flask, caustic_mug and concrete_chunk02a.
Each target has seven passing render rebuilds and one explicit unsupported bird
model (complex weights): **28 passes, four unsupported; no render differences**.
These are explicitly --render-only runs. They remove physics/BVH, rigs and sequence
metadata and do not prove those features. Reports identify exact compiler/tool
hashes and input hashes. Fixed render thresholds are position 0.0001 inches, normal
component 0.006, UV 0.00001 and weight 2/32767; none was widened to pass an asset.
The wider native normal/weight bounds account for their packed representations.

## Unfinished and unverified

- Native PHY/BVH collision and ragdolls; complex VVD/VVW/VG skinning; procedures;
  RUI; external animation rigs and sequence assets; root-motion tracks; IK rules;
  transition nodes; followers. These inputs fail explicitly.
- RPak packaging/baking, streaming and relocation, material dependency resolution,
  shader compatibility, animation-rig integration and runtime entity behaviour.
- Default export preserves only its implemented QC subset. Render comparisons do
  not cover material GUIDs, skin-family identity, tangents, bounds, arbitrary
  sequence metadata, procedural behaviour or collision geometry equivalence.
- Compact retail animation decoding needs wider animation-rig corpus validation.
  Authored compiler output uses raw native tracks, not those compact modes.
- Retail and later self-hostable season profiles remain future work. S0-S3 share
  a header but differ at the vertex-buffer boundary; v54 alone is not a profile.

Historical TF2 corpus figures under docs/reference and tests/legacy_v53 are not
R5 evidence. Reports contain local game paths and stay ignored. No release tag or
claim of full runtime compatibility accompanies this development build.
