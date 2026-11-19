# Early Apex MDL v54 layout notes

Measured against the owner's installed S0-S3 common RPaks. Consulted r-ex/rsx layout
notes at 18cd364421c883d475a78643e3796caf19204355 and the installed R5 SDK studio.h.
Reference implementation code was not copied. Research tools remain ignored.

S0/S1 retain VTX7, VVD4 and optional VVC. S2/S3 use VG revision 1. All four surveyed
builds use IDST v54 and a 0x224-byte studio header. RPak asset versions are distinct
from studio versions. Later seasons change all three of studio layout, animations
and vertex data. The compiler does not yet implement RPak baking/relocations.

| Structure | Size / layout |
| --- | --- |
| bone | 0xB8; pose-to-bone 0x54, flags 0x94, procedure 0x98 |
| attachment / hitbox | 0x3C / 0x2C |
| model | 0x88; extra string 0x40, mesh count/index 0x4C/0x50 |
| mesh | 0x5C |
| material | 0x0C: relative int32 name, uint64 material GUID |
| animation descriptor | 0x34 |
| sequence | 0xD0; int32 sequence-relative animation descriptor offsets |
| event | 0x110; 256-byte options string |
| IK chain / link / lock | 0x14 / 0x10 / 0x10 |

Body parts use the header count/index at 0xEC/0xF0 and 16-byte records
(relative name, model count, selection base, relative model-table offset).
Each model choice owns its meshes; a zero-mesh choice is a blank, not an absent
body part. The exporter preserves this grouping instead of promoting every mesh
to a separate always-visible body part. Runtime evidence for the rebuilt Flatline
is recorded in VALIDATION.md. Material names are exact stored strings: suffixes,
case and slash styles are significant to the comparison. The exporter uses unique
mesh-material aliases and restores each name through `$renamematerial` after input
extension stripping. QC path backslashes are literal, unlike event-option escapes.

The header overlaps TF2 through 0x108. Mesh offset is 0x110; IK chains 0x124/128;
RUI 0x12C/130; poses 0x134/138; surface property 0x13C; mass 0x150; linear bones
0x194; procedural lookups 0x198..1A0; component offsets 0x1C0..1CC and sizes
0x1D0..1DC; followers 0x1E8/1EC; BVH offset 0x214; extra weights 0x21C/220.
RMDL length covers only studio data, not companions. Multi-model assets exposed
the native 0x88 model stride: a mistaken 0x8C can pass single-model checks.

## Native animation

Each section opens with one nibble per bone, padded to two bytes. Bits 1/2/4 mean
position/rotation/scale. A uint16 record header stores length in its low 13 bits
and varying scale/rotation/position flags in its high three bits. A varying channel
has a four-byte pointer: low 13-bit relative offset, high three active-axis bits
(X=4/Y=2/Z=1), followed by two uint8 offsets measured in 16-bit words.
Position also carries a float step. Position/scale samples are bind-relative (zero
base for delta animations); Euler samples are absolute. Rotation step is
0.00019175345 radians; scale step is 0.0030518509.

Native mode 0 stores one int16 per frame after the two-byte mode/count header.
Other modes encode byte deltas or polynomial/packed residuals. These are not Source
valid/total RLE blocks. The compiler emits mode 0 in 30-frame sections with overlap
and a trailing final-frame section. The independent reader also handles documented
constant half-vector/quaternion and compact modes; those need wider rig validation.
TF2 quantization vectors are absent from native v54 bones.

The 0xD0 sequence descriptor stores a rectangular blend grid at 0x44/0x48,
pose parameter indices at 0x4C/0x50, starts at 0x54/0x58 and ends at 0x5C/0x60.
Pose keys (pointer at 0xA0) contain width + height float32 values, axis 0 first.
The bone-weight list (0x9C) has one float per studio bone. Activity modifiers use
eight-byte records (relative name, negate byte, padding), counted at 0xBC.
Pose parameter records are 20 bytes: relative name, flags, start, end and loop.
These layouts were consulted in the native reference and checked on authored
round trips. Common retail models expose no pose parameters or embedded blends.

Events are 0x110 bytes: float32 cycle, int32 ID, int32 type, 256 bytes of terminated
options and an event-relative name offset at 0x10C. The compiler emits numeric
events as type 0 and named events as type 1024. `eventcycle` writes a normalized
float directly, avoiding integer-frame rounding on export. Legacy frame-zero
events on a one-frame authored clip retain the existing NaN cycle representation;
the reader represents that cycle as None for comparison and exports it as frame 0.
Other nonfinite cycles and unknown event types are rejected by the export path.

All 1,962 sequence descriptors in the 1,789 extracted common models have zero
counted blends and a 1x1 grid, including reference descriptors both with and
without flag 0x80000. Each still holds one inline clip (below).
This survey provides no retail animated-event parity evidence. Native autolayers
reference a uint64 sequence asset GUID, unlike TF2's local sequence index; the
compiler rejects layers until the native asset dependency path is implemented.

## Piecewise movement and IK chains

Animation descriptors retain a movement count/index at 0x14/0x18. Each record is
44 bytes: int32 end frame and motion flags, then nine floats (v0, v1, cumulative
yaw in degrees, direction XYZ, cumulative position XYZ). The compiler's explicit
`$legacymovement` path emits these native records and leaves the residual pose in
the bone tracks. Direct `movementrecord` import preserves the stored values.
Checks cover finite values, increasing end frames and frame/file bounds.
The separate descriptor field at 0x1C points to a frame-movement stream. These are
distinct representations.

The owned S0 raw sequence survey contains 3,301 files / 5,701 animation descriptors:
2,902 have frame-movement pointers and none have piecewise movement records. Thus
piecewise emission is supported by consulted native layout notes and authored
round trips, not by retail movement parity or an in-game playback check.

## Native frame movement

Descriptor flag 0x40000 and the descriptor-relative int32 pointer at 0x1C identify
frame movement. Early S0-S3 streams begin with four float32 scales (XYZ inches,
yaw degrees), int32 section-frame count at 16, and stream-relative **int32** section
offsets at 20. Section count is `(frames-1)/sectionFrames + 1`. A section begins
with four uint16 section-relative channel offsets; zero means an all-zero channel.
These are early-profile tables, not later retail packed offsets or TF2 RLE.

Each scalar packet has uint8 mode/count. Mode 0 stores count int16 samples; mode 1
stores an int16 base followed by count-1 signed byte deltas from that base. Modes
2..19 store an int16 base and `(mode-2)%6` int16 polynomial coefficients. With
`t=localFrame/(count-1)` (zero for count 1), coefficients multiply successive
powers of t. Modes 2..7 have no residuals, 8..13 add packed 2-bit residuals and
14..19 add packed 4-bit residuals: `2*value - ((1<<bits)-1)`. Arithmetic uses
float32, including the final scale multiplication. Packet sizes in 16-bit words:
`1+count`, `2+floor(count/2)`, or
`2+coefficients+ceil(bits*count/16)` respectively. The last two formulas include
word padding. Unknown modes, zero counts, invalid scales and out-of-file spans
are rejected. The native survey found no mode-1 signed16 overflows; imports reject such
overflows explicitly.

The authored encoder emits mode 0 with 30-frame sections, a next-section sample
for interpolation, and a duplicate final sample. It fits scales to authored ranges
rather than inheriting TF2's 128-inch/180-degree floors. Root removal uses exactly
the encoded quantization grid. Translation/yaw budgets are 0.001 inches/0.005
degrees; no sample is silently clipped. Delta clips retain their deltas with zero
extracted motion. Fixed decoded text tracks and validated `FM54` sidecar imports
are also supported. Sidecars retain the native bytes, including internal padding,
through the last referenced packet; unreferenced trailing file bytes are excluded.
This preserves polynomial compression; it does not regenerate it.

Owned S0/S1/S2/S3 raw sequences contain 2,902/3,022/2,929/4,172 movement streams
(13,025 total) and 288,411/305,147/281,611/417,711 decoded frames (1,292,880 total).
All modes 0..19 occur. Full decoding and zero-pose stub imports are offline movement
checks, not animation-rig, RPak or runtime equivalence.

IK chains are 20 bytes: relative name, link type, count, chain-relative link-array
offset, and a float at 0x10. Links are 16 bytes (bone int32, knee direction XYZ).
All 326 chains in 487 installed S0-S3 rigs have type 0, three links and the exact
float32 value 0.8660253882408142 (cos 30 degrees) at 0x10. This corrects the inherited
TF2 default. Explicit overrides preserve the raw scalar. The exporter supports
three explicit links and the first link's knee vector; it rejects other layouts.
The native rig chain descriptions were independently decoded and rebuilt, with
bone indices compared through their bone names. This does not produce a native
RPak rig asset or establish runtime IK/rule/lock equivalence.

## VG revision 1

Header: 0x100 bytes, magic 0x47567430, revision 1, byte length at 0x0C. Uint64
offset/count pairs locate bone maps (0x10), meshes (0x20), uint16 indices (0x30),
vertex bytes (0x40), extra weights (0x50), auxiliary records (0x60), LODs (0x70),
legacy weights (0x80), strips (0x90). Meshes are 0x48 bytes. LODs are eight bytes:
uint16 first mesh/count and a float switch point. Studio mesh IDs select LOD meshes.

The writer keeps positions as float32, uses identity bone mapping, native packed
normal/tangent and up to sixteen influences, optional RGBA/UV2, and float32 UV0. Normal
packing uses major-axis index/sign and two nine-bit component ratios; tangent uses
a ten-bit angle plus handedness. Each mesh has triangle-list indices and one strip.
Runtime handling of auxiliary VG fields has not been verified.

## Complex skinning

Studio flag 0x4000 selects the complex-weight layout for the entire model. The
compiler sets it automatically when any vertex needs more than three influences.
All influences survive source import, bone remapping and LOD unification. Counts
above 16 fail. Early profiles still use a maximum of 256 bones.

Packed values are signed int16 `q`, with weight `(q + 1) / 32768`. Every complex
VVD vertex in the installed S0/S1 common assets satisfies `sum(q) + count = 32768`:
5,651,844 encoded vertices, with influence counts from 1 through 16. This rule also
reconstructs all 10,989 bird vertices identically from S0 VVD/VVW and S3 VG, using
the original VTX vertex mapping. The writer apportions integer units while keeping
their sum at 32768, retains a positive unit per positive influence, and rejects a
weight ratio that exceeds the existing 2/32767 component error budget.

For S0/S1, the 48-byte VVD vertex keeps its size. The first 12 bytes become three
int16 weights, an int16 padding field, and an int32 extra-weight array index.
The three uint8 bone IDs and uint8 influence count remain at offsets 12 and 15.
Even vertices with at most three influences use packed values when the model flag
is set. A VVW companion has a 44-byte header (checksum, version 1, eight LOD count
slots, data offset), followed by int16 weight/bone pairs for influences 4..16.
The first count slot is the VVD vertex count; the other seven are zero. VVW follows
VTX, VVD and optional VVC in the header's component offset space (0x21C/0x220).
Native complex VTX uses direct VVD bone IDs, no hardware palette state changes,
and maximum strip/face/vertex bone counts of 256/48/16.

VG keeps an eight-byte weight/index block. In complex mode it contains the first
packed weight, a uint16 index into the mesh's extra-weight array, first/last bone
IDs, one unused byte, and the influence count minus one. Middle influences use
four-byte weight/bone records at the group's extra-weight offset plus the mesh's
byte offset; the vertex index is measured in records. The last weight is one minus
the decoded explicit weights. Simple VG similarly uses an implicit final weight.
Repeated middle-weight lists share storage. An unshareable list whose starting
index exceeds 65535 fails rather than wrapping. Header VVW spans are zero in VG
profiles; legacy VTX/VVD allocation sizes are computed, but companions are not
written for those profiles. Their size fields at 0x1D0..0x1D8 remain populated;
component offsets at 0x1C0..0x1C8 are zero. RePak uses the sizes for allocation.

These layout/geometry checks do not establish runtime compatibility.

## PHY (S0-S3)

The `.phy` beside the model is not IVP. Measured over all 938 installed S0-S3 files
(every byte accounted for; `tools/phy54.py`):

| Offset | Content |
| --- | --- |
| 0x00 | int size (20), int id (1), int16 solid count, int16 0, int model checksum, int keyvalue offset |
| 0x14 | int64 solid-table offset (0x20), int64 solid count, int64 0, int64 data size (keyvalue offset - 0x14) |
| table | 0x90 per solid |
| data | per solid: its 0x40 hull records, then each hull's vertices, faces and edges |
| kv | keyvalue text as in TF2 (`solid`, `ragdollconstraint`, `collisionrules`, `editparams`, ...), NUL-terminated |

All offsets after the header are int64 and relative to 0x14. There is no alignment
padding: hull data follows directly, even after an odd number of two-byte edges.

Solid (0x90): int64 hull offset, int64 hull count; float 1.0 then three zero words;
centre (vec3 + pad); inertia tensor (three vec3 + pad rows); centre again; bounds min,
bounds max (vec3 each); two zero words. The centre is the hulls' volume centroid. The
inertia is per unit mass about the solid-space origin, I = I_centroid/V + |c|^2 E - c c^T
(e.g. a box's parallel-axis terms appear off the diagonal). Bounds minima are the hull
extents; maxima start at FLT_MIN in Respawn's tool, so a negative maximum is stored as
1.1754944e-38 (all 3,356 solids). The pad words after the vectors hold uninitialised
values in retail (for example after the second centre); the compiler writes zero.

Hull (0x40): centroid (vec3) and the distance from it to the nearest face plane (the
inscribed radius), then {int64 offset, int64 count} for float3 vertices, 32-byte faces
and edges. A face is a loop of byte vertex indices, counter-clockwise seen from outside,
ended by 0xFF when shorter than 32. S0-S2 edges are two vertex bytes; S3 edges are four
bytes: v0, v1, the face running v0->v1 and the face running v1->v0. Each hull is a closed
polyhedron (V - E + F = 2; one S3 retail axe hull is the exception). S3 hull points are
the volume centroid (1,246/1,246); S0/S1 retail used another interior point, and S2 has
both kinds. The radius is measured from the stored point (99.5%; the rest differ by
non-planar faces or one outlier). Keyvalue `volume` is the polygon volume of the stored
faces, each fanned from its first vertex; bent faces make it differ slightly from the
convex hull of the points. Rigid solids are in model space; `$collisionjoints` solids
are in their bone's space. Header: PHY offset 0x1CC holds -123456, size 0x1DC the file size.

The compiler limits each hull to 255 vertices and faces and 32 vertices per face (byte
indices with a 0xFF terminator) and fails beyond them. TF2's IVP surfaces and
map-collision block are not written for Apex.

## BVH collision (studiohdr 0x214)

The block traces use (bullets, line of sight). Written by the compiler (`src/write/bvh54.cpp`);
read by `tools/bvh54.py`. Measured over the S3 corpus (354 models, 1,394 entries) and
confirmed in R5R where noted.

- Placement: on a 64-byte boundary after the string table. 0x1F0..0x207 hold the hull
  box (0x6C) extended to include the origin when a BVH is present (all 1,128 S0-S3
  models with a BVH), else the hull box unchanged (all 227 S3 models without one).
- Block header: contents offset, table offset, contents end, entry count (relative to
  the block). table = 0x10 + 0x20 * count. The table has two words per leaf table
  index (see the leaf header): its size is 8 * (largest index + 1) in all 354 S3
  models. The first word's high 16 bits are an index into the game's surface-property
  list (R5R reports 15 concrete, 16 glass, 22 metal, 51 rock), zero in 285 models and
  otherwise set per material rather than per model (glass 16, rock mostly 15; models
  whose `$surfaceprop` is `metal` carry 22, 27 or 41); the second word was always 0.
  In R5R traces of a prop report the model's `$surfaceprop`, not this value
  (concrete_chunk02a's table says 15, traces report its `rock`, 51), for ordinary and
  high-detail traces alike; the compiler writes zeros. The contents list holds one
  word, 1 (CONTENTS_SOLID; 8 in three models).
- Entries (0x20 each, at 0x10): packed flag (1 packed int16 vertices, 0 float vec3
  vertices; only the 2,400-inch `mp_setting_menu` uses floats), node, vertex and leaf
  offsets, an integer origin (vec3) and a power-of-two scale (2^-30..2^-23). A packed
  vertex is three int16; position = origin + (v << 16) * scale.
- Entry roles: header 0x218 holds two int16, the physics-hull entry and the trace-mesh
  entry (-1 for none; (0, 0) without a BVH). Static models with a PHY have (1, 0)
  (entry 0 the trace mesh, entry 1 the convex hull); dynamic rigid models (0, -1);
  static models without a PHY (-1, 0); jointed models (-1, -1) with one entry per PHY
  solid, ordered by bone index (not PHY solid order).
- The trace mesh is the LOD 0 render triangles (retail positions sit 0-0.001 in above
  the stored render vertices: retail built it from source positions). Its triangles keep
  the render winding; hull and solid triangles wind the other way (negative volume).
- Nodes (BVH4, 0x40): per axis eight int16, four child minima then four child maxima,
  in the entry's packed units (minima rounded down, maxima up). An empty slot has an
  inverted box. Then four words: child index in the high 24 bits; the low byte of word
  2 holds the types of children 0 and 1 (low nibble first), that of word 3 children 2
  and 3. Child types: 0 node, 1 empty, 3 leaf list, 4 float-vertex triangles, 5 packed
  triangles, 6 float-vertex quads, 7 packed quads (2 never seen). Retail may point two slots of a node at one child node,
  each box covering part of it (a DAG); the compiler writes a plain tree.
- Type 4/5 leaves (index = word offset into the leaf data): a header word, bits 12-15
  = triangle count - 1, bits 16-31 = a 1024-vertex page, bits 0-11 = a table index
  (0-3 in retail, e.g. 0 for at_gib5's trace leaves and 1 for its hull leaves; 0 from
  the compiler). Then one word per triangle: A (11 bits) adds to
  a running base, which starts at page * 1024; the corners are base, base + 1 + B
  (9 bits) and base + 1 + C (9 bits); the top three bits were 7 in every S3 triangle.
  The page unit was found in R5R: with the first vertex stored as a plain number, every
  leaf after the first traced at the wrong place (`static_step` in VALIDATION.md); with
  pages, `crypto_drone_holo` (2,711 vertices) decodes all 2,812 triangles, against
  1,305 read as a plain number.
- Type 6/7 leaves: parallelogram quads. The header is as for triangles (bits 12-15 =
  quad count - 1). Then one word per quad: A (10 bits) adds to the running base, B
  (9 bits) and C (9 bits) give corners base + 1 + B and base + 1 + C, and the top four
  bits were 0xF in all 6,690 quads. The fourth corner is not stored: it is
  b + c - a, opposite the base, and retail leaves vertices it can compute this way out
  of the vertex data (`crypto_drone`'s box hull stores seven corners). In 4,008 of
  4,259 S3 quads b + c - a is a stored vertex; in 47 it is one packing unit from one
  (retail sizes the boxes from the true corner, so a reader allows one step there).
  A quad is two triangles; render meshes split quads along either diagonal.
- Type 3 leaves list sub-leaves: a count (2-4), then one word per sub-leaf, its type
  (4-7) in byte 1 and its length in words (header + items) in byte 2, other bytes
  zero; the sub-leaves follow the list in order (14,581 of 14,581 list words).
- Decoded this way, all 3,865 S0-S3 entries have valid trees (every leaf inside its
  box); every hull and solid entry encloses its retail PHY solid's volume, wound the
  hull way, except wood_gib01c's (a bent face split along the other diagonal); and
  every trace triangle and quad is a render triangle or triangle pair.
- The compiler writes leaves as retail does: vertices once per stored position,
  triangle pairs that form an exact parallelogram on the packed grid as quads (the
  computed corner left out of the vertex data unless another item uses it), the rest
  as triangles, and a type 3 list where a leaf has both. Float entries keep triangles
  (b + c - a is not exact in floats). Rebuilt blocks are close to retail's size
  (40,128 against 41,024 bytes over ten sampled models).
- Use in R5R (v2.6.52): an ordinary trace of a SOLID_VPHYSICS prop_dynamic reads the
  physics-hull entry and misses models without one; `TraceLineHighDetail` reads the
  trace-mesh entry. Jointed entries are not traced on a prop_dynamic, retail's or
  rebuilt (TRACE_MASK_SHOT hits hitboxes instead).


Hull polygons in the compiler's BVH are recursively split at the shortest internal
diagonal, measured on the source float positions before BVH quantization. Winding
is retained. This policy reproduces the native bent-face split in wood_gib01c;
fixed first-vertex fans gave the wrong enclosed volume. An independent survey of
765 rigid PHY/BVH pairs over S0-S3 has no volume failures at the existing 0.1%
budget with this policy (the fixed fan fails wood_gib01c in each profile). This is
not a claim that every coplanar native triangle diagonal is reproduced byte for
byte. PHY polygon mass properties continue to use their measured first-vertex fan.

## Keyvalues, hitboxes and reference-pose sequences

- Keyvalues (0x140 offset, 0x144 size): in all 1,789 S0-S3 models exactly
  `mdlkeyvalue{prop_data{base "X"}}` plus a newline, compact (keys unquoted, no
  spaces), stored with two NULs (size = text length + 2); `base` is empty in 1,268
  models. The compiler writes this form and always a prop_data block with a base.
  R5R deletes a prop_physics whose model has no prop_data.
- Hitbox sets (0xB0 count, 0xB4 offset): 12-byte sets (name offset, box count, box
  offset, relative to the set), 0x2C-byte boxes: bone, group, min (vec3), max (vec3),
  name offset, crit override, hit-data-group offset (relative to the box). Header
  flag 1 marks generated hitboxes.
- Include-model count (0x158) -1, in 386 of 581 S3 models: not an include model but the
  external-rig linkage (the loader builds the virtual rig from asset references).
- Reference-pose descriptors (retail `ref`, and `ragdoll` with ACT_DIERAGDOLL): a 1x1
  sequence whose blend count (0x38) is 0 but whose animation index (0x3C) still holds
  one sequence-relative entry, read through the grid (r5apex.exe 0x1401C8AD0). It points
  at a clip descriptor right after the entry, named `@` + label, 30 fps, its data on a
  16-byte boundary (all 1,962 S0-S3 descriptors). The clip is the reference pose: one
  frame in most, up to 191 in viewmodels (`ref`); 1,453 have tracks and differ from the
  bind pose (e.g. bangalore_rockets_projectile turned 90 degrees, charm_nessy); the
  other 509 (all single-bone props) hold the bind pose with no tracks (flag 0x20000
  clear, data offset at the boundary). Collision is not posed by it (the rocket's
  physics matches the bind pose). Without the clip R5R reads a descriptor from the
  following bytes (crashes at r5apex.exe+0x1CA771/0x1CA80B) and BecomeRagdoll divides by
  its frame count (0x1CAEFA). The descriptor flags have the single-frame bit 0x80000 or
  not.
- Animation tracks: a bone record's mode bits (header >> 13) select tracks: 4 position,
  2 rotation, 1 scale. A clear bit stores a constant: three absolute half floats for
  position or scale, a 64-bit quaternion for rotation. Retail stores constant positions
  that way (empty_lights' ref clip at 179 inches); the compiler does when the half value
  is no less accurate than the track. A track pointer is a uint16 (axis mask in the top
  three bits, 4 = x, 2 = y, 1 = z; start offset in the rest) followed by one byte per
  axis slot: x streams from the start, y from the word offset in byte +2, z from byte
  +3. Each axis keeps its slot when an earlier axis is absent: drone_EMP's def_c_base
  stores y at word 0 and z at word 25 with x absent. Reading them as consecutive
  streams returned y's values for z; R5R posed the installed drone 6.8 inches from
  that reading, and exactly as the per-slot reading gives.
- Sections: a clip's frames per section (descriptor +0x30; 0 = one section) is
  ceil(frames / n) with n = (frames + 32) // 64 sections, and the clip stays whole when
  n is 1 or it has at most 96 frames. This fits 284 of the 285 distinct (frames, size)
  pairs in the 4,249 S3 assets; the exception is 96 frames, kept whole, whose frame
  movement takes the rule's two 48-frame sections. Its frame-movement stream stores its own section size,
  equal to the clip's in 4,162 of 4,172 retail S3 clips (the rest: 96-frame whole clips
  with 48-frame movement sections). Decompiled clips keep their stored value
  (`sectionframes`).
- Standalone sequence assets: flag 0x40000 is set exactly when the sequence's clips
  have frame movement (all 4,249 retail S3 assets: 2,426 with it, 1,823 without). No
  retail model embeds a counted clip, so in-model sequences give no evidence; the
  compiler leaves the bit off them. Asset labels are asset paths
  (`animseq/props/crypto_drone/crypto_drone/drone_EMP.rseq`), and R5R resolves a short
  label (`Anim_PlayOnly( "drone_EMP" )`) by the asset's file name: a rebuilt drone with
  assets named `seqN.rseq` found none of the short names.

- Illumination attachment (0x190): the `__illumPosition` attachment's index + 1 (always
  the last attachment), else 0, in 1,779 of 1,789 S0-S3 models; ten R-301 models store
  a value 8 past it, apparently stale.

## Fields measured against all 581 S3 models

- Skins (0xE0 slots, 0xE4 families, 0xE8 table): slots always equal the texture count
  and family 0 is the identity; after the int16 table (4-aligned) come int32 string
  offsets naming families 1.. (empty strings allowed); keyvalues follow.
- Studio flags (0x9C): bits retail sets that the model data does not determine are
  0x2, 0x4, 0x8, 0x80 and 0x800 (material properties; 0x4 and 0x8 occur together in
  148 models). 0x4000 selects the complex-weight layout; 78 S3 models set it without
  any vertex needing more than three influences.
- Material types (0xCC): one byte per texture slot in every S3 model.
- Surface ids: header 0x180 and bone +0xAC hold the id of the surface property in the
  game's surfaceproperties table (580 of 581; the other names a property the table
  lacks and stores 0). Every bone shares the header's property; contents are 1.
- Bone +0xB4: the bone's BVH entry (0 without a BVH or with only the trace mesh, -1
  with a rigid physics hull, else the index of the bone's solid entry, numbered in bone
  order, -1 for bones without one): all 581 models.
- Bone flags: a static prop's bone has 0xFFFF00. Elsewhere retail sets 0x20 on about
  a third of bones and 0x100000 on a tenth, and in 129 models (mostly viewmodels) marks
  bones used by LOD 0 vertices that no vertex weights; no stored data predicts them.
- Empty tables: local animations (0xBC) and nodes (0x100) store 0; flex descriptors
  (0x10C) point at the body parts; the bone-follower offset (0x1EC) is the file length.
- VG component offsets (0x1C0..0x1C8): VTX -1, VVD = the VTX size, VVC = VTX + VVD
  sizes when there is vertex colour, else 0. The sizes themselves (0x1D0..) follow the
  legacy VTX/VVD layout and differ from ours where vertex splitting differs (the
  rebuilt geometry matches; RePak uses them only for allocation).
- Pose-to-bone matrices are recomputed from the bone chain: they match retail within
  2.5e-5 (float32 rounding).

## RUI panels (studiohdr 0x12C count, 0x130 offset)

Measured on all 6,621 panels in 379 S0-S3 models. The table holds 8-byte entries
(uint32 name hash, int32 mesh offset relative to the entry); the hash is MurmurHash3
of the name with every byte ANDed with 0xDF, as in TF2. The include-model index
(0x15C) equals the panel-table offset in every retail model.

v54 changes the mesh header from TF2's: uint16 parent, vertex, face and mask counts,
then int32 offsets (relative to the mesh) of the parents, vertices, masks, faces and
bounds, and the zero-padded name at +28. There is no winding (ccw) bitfield; the mask
count replaces it (below). The arrays are packed backwards from the 16-aligned vertex
array:

- `vertices = align16(28 + len(name) + 1 + 2*parents + 6*faces + 2*faces)`;
- `masks = vertices - 2*faces` (one uint16 per face), `faces = masks - 6*faces`
  (three int16 vertex indices), `parents = faces - 2*parents` (int16 bones);
- `bounds = vertices + 16*vertexcount` (eight floats per face).

Vertices are 16 bytes (int32 parent slot, vec3). As in TF2, bounds points 0-2 are
the panel coordinates of the face's three vertices (the client solves each face's
panel-to-model map from them, r5apex.exe 0x1403006F0). Retail maxima: 2 parents, 238
vertices, 85 faces, mask count 47.

- **Per-face mask:** bit `4*row + column` is set for each cell of a 4x4 grid over the
  panel's unit square (x across, y down the rows) whose interior the convex hull of the
  face's four bounds points overlaps; a hull that only touches a cell's edge does not
  set it. This reproduces all 33,173 S0-S3 retail faces (a bounding-box test misses
  118). The panel draw skips faces whose mask misses a mask it computes for the panel
  (for panels of 8 or more faces).
- **Mask count:** the client's panel draw (r5apex.exe 0x1402FF7A0) loops over the faces
  and switches from one index writer to one with the opposite winding at face index
  `maskcount`. So it is the number of leading faces drawn with the stored winding; the
  rest are TF2's `ccw` faces, stored last. The flag cannot be derived from the stored
  geometry: the two faces of the health injector's panel have the same stored normal
  and bounds, but only the second is drawn reversed. It does follow the source winding:
  32,766 of the 32,779 surveyed v54 faces with a clear Z direction have a +Z normal
  exactly when they are trailing faces, and in TF2's ptpov_rspn101 all 78 such faces
  have a +Z normal exactly when their ccw bit is set.

## Jiggle bones (studiohdr 0x198..0x1A0)

Measured on all 748 procedural bones in 114 S0-S3 models; every one is a jiggle bone
(type 5). Models without procedural bones store zeros in all three header fields.

- External rigs: retail rigs carry no procedural bones (zeros at 0x198, proctype 0) even
  when the model has jiggle bones (all 10 S3 rigs paired with jiggle models); the rig's
  copies of those bones have flags 0 or 0x20 (97 and 2 bones). The bone byte is the
  model's bone index, not the rig's. In R5R a rebuilt external-rig charm whose rig
  carried the jiggle records left the jiggle bones unposed; with the jiggle bones'
  usage flags still in the rig it produced NaN poses; with retail's rig form it swings.
- Records: 0x7C bytes, straight after the bone array, one per procedural bone in
  procedural (`$jigglebone`) order, which differs from bone order in 26 models. Each
  bone's procindex (+0x9C) points at its record, relative to the bone.
- Record: uint8 flags, uint8 bone index, int16 0, then 30 floats: TF2's
  mstudiojigglebone_t floats with one more after tipMass (values 0, 0.1 and 0.3; taken
  to be tip friction). The bone byte is the bone's own index in 743 records; Wraith's
  bones 64-70 store 63.
- Flags as in TF2 (0x01 flexible, 0x02 rigid, 0x04 yaw limits, 0x08 pitch limits, 0x10
  angle limit, 0x20 length flex, 0x40 base spring); retail sets both 0x01 and 0x02
  (0x2f, 0x3f, 0x33, 0x37) and keeps limit values whose flag is clear.
- 0x198 count; 0x19C a byte table of bone indices in procedural order, straight after
  the records; 0x1A0 a per-bone byte table (each bone's procedural slot, or 255)
  straight after it. The bone-controller offset (0xAC) is the unpadded end of that table
  (in all 114 models; R5R crashed when it pointed past zero padding); the attachments
  follow 4-aligned.

## Linear bones (studiohdr 0x194)

Every multi-bone retail model has a linear bone table (677 of 677 surveyed S0/S3
models; none in single-bone models, none in the 138 S3 rigs). v54 layout: int32 bone
count, then six int32 offsets relative to the table: bone flags, parents, positions
(vec3), quaternions, Euler rotations (vec3) and pose-to-bone matrices (3x4), each a
copy of the bone records (all 677 match), with no TF2 scale or alignment arrays. It
sits right before the string table (0x1BC, the first string, follows its end). R5R
v2.6.52 crashed (r5apex.exe+0x1CA771, an animation descriptor read through a wrong
base) with two such rebuilt models in view while the table was missing.

## Standalone rigs and sequences

`--external-assets` writes a render model, a full native studio-header `.rrig` and
one `.rseq` per sequence, in retail's layout (measured on every S0-S3 model with a rig
and every S3 rig):
- The model keeps only its reference-pose descriptors: `ref` at index zero, and
  `ragdoll` where there is one (all 1,155 models with rigs: 1,005 `ref` only, 150 `ref`
  and `ragdoll`). It has no clips, pose parameters, IK chains or nodes.
- The rig (all 138 S3 rigs) has the skeleton, hitboxes, pose parameters, IK chains,
  node names and transitions, and no attachments. Its checksum is 0, its bones follow
  the header at 0x224, its pose parameters come before its IK chains, and the offsets
  of tables a rig never has are 0 (0xC4, 0xD4, 0xDC, 0xE8, 0xF0, 0x118, 0x120, 0x130,
  0x140, 0x14C, 0x15C, 0x178, 0x184, 0x18C, 0x1BC, 0x1EC).
- In a rig, 0x10C (a model's empty flex-descriptor table) indexes the node
  transitions: one absolute offset per node, then for each node an int32 count and
  (int16 exit node, int16 sequence index) pairs, sorted. Each sequence entering at one
  node and leaving at another is that transition; the index is the sequence's place in
  the rig's sorted sequence list (every transition of the 62 rigs with nodes; the 19
  whose sequences were all exported match exactly). The compiler writes asset-set
  indices and `pack54.py` maps them to the packaged order. R5R's player and viewmodel
  animation code looks transitions up there (r5apex.exe+0xB41910: the current node's
  list, searched for the goal node): returning from a one-handed Mastiff sequence
  (node 2) to a two-handed one (node 1) plays `switch_to_twohanded` first.

R5R depends on that layout. It maps a sequence's pose parameters and IK rules through
per-rig remap tables (virtual-model group +0x90 and +0xD0) and leaves them null when the
model has its own: a model that also carried pose parameters crashed at
r5apex.exe+0x1D450F playing a blend, and one with IK chains at +0x1CD1AA playing a
sequence with IK rules. Packaged as retail does, with the rig listing the sequences
and the model listing none, imported blend and IK sequences play and pose as retail's.
Each RSEQ starts with its 0xD0 sequence descriptor at byte zero. Its animation
reference table contains int32 offsets relative to that descriptor. Each referenced
0x34 animation descriptor has a zero base-pointer field; the other pointers remain
descriptor-relative. All 7,789 inspected installed S3 animation descriptors had a
zero animation base field. The writer keeps per-blend timing, native pose tracks,
piecewise/frame movement, events and sequence weights in the standalone asset.
Authored regressions compare embedded and standalone metadata and every decoded
frame across all four profiles, including a 3x2 blend grid and pose keys.

The local S3 RePak integration uses RPak version 8, model asset version 10, rig
version 4 and sequence version 7. The model lists the rig dependency; the rig lists
its sequences, in the engine's name order: byte order with A-Z folded to lower case
(all 78 S3 rigs with three or more exported sequences). R5R finds a sequence by name
with a binary search of that list (r5apex.exe+0x1EE220), for example an autolayer's
target: unsorted, a layer whose target the search missed played the model's `ref` in
its place. VG bytes go to a mandatory streaming file. The `.assetset` file is
a compiler packaging manifest, not an engine asset: ASCII `R5AS1`, target, sequence
count, each on a separate line. It prevents stale numbered sequence assets from
being accidentally linked after recompilation. These facts establish the packaged
asset structure; live rig resolution and streaming still require a runtime test.

## Sequence assets measured on all 4,249 S3 RSEQs

- Asset GUIDs: an asset path's GUID is RTech's string hash. It reads the path four
  bytes at a time, folding letters to upper case and `\` to `/`; each word is mixed as
  `h = h*0x633D5F1 + ((word*0xFB8C4D96501) >> 24)`, then `h ^= h >> 61`. The final
  partial word is masked below the terminator, and `0xAE502812AA7333 * length` is
  subtracted. `mdl54.asset_guid` and the compiler's `AssetGuid` implement it. Checks:
  208 of the 292 GUIDs autolayers reference resolve to extracted sequences (the rest
  name assets not extracted), and the rigs' sequence lists (RSX `.rson`) resolve 4,158
  of the 4,249 sequences.
- IK rules (animation descriptor 0x24 count, 0x28 index): 0x88 bytes. These are v53's
  mstudioikrule_t with 0x1C bytes inserted at +0x3C and the unused tail dropped:
  index, type, chain, bone, slot, height, radius, floor, pos, quaternion, then
  +0x3C..0x57 (unknown, zero), error index +0x58 (rule-relative), iStart +0x5C, +0x60,
  start/peak/tail/end +0x64..0x70, contact, drop, top, attachment +0x80 and
  endHeight +0x84. Every one of 3,776 sampled rules is a whole-range release
  (studiomdl's automatic releases): index k, slot = chain, bone 0, range 0-0-1-1,
  and an error index pointing past the rule array. Sequence 0x90 holds the largest
  rule count of its clips.
- Autolayers (0x94 count, 0x98 index): 32 bytes each: the target sequence asset's
  GUID, an int16 pose parameter, an int16 that is always 0, int32 flags, then
  start/peak/tail/end. Flags seen: 0, 0x8000 and 0xC000 (with a pose parameter).
  R5R's layer loop (r5apex.exe+0x1D973E): equal start and end give full weight; 0x4000
  scales the weight by the pose parameter's ramp and the layer follows the base
  cycle; 0x8000 runs the layer on its own clock (its cycle from time). The pak loader
  turns the GUID into a pointer to the target asset, and the virtual model resolves it
  by that asset's name (r5apex.exe+0x1ECD40, through the sorted search above).
- Transition nodes: rigs keep node names (0xFC count, 0x104 name offsets) with index
  0x100 = 0 in all 62 S3 rigs that have nodes; their transitions are at 0x10C (see
  "Standalone rigs and sequences"). Sequences keep entry/exit nodes (0x70/0x74,
  1-based); three have only an exit node.
- 0xC8 (offset) / 0xCC (count): 24-byte records of a float, a bone index (-1 for
  none) and four floats, in 181 menu and banner sequences. Meaning unknown.
- Unused blend axes store start 0, end 1 (in-model descriptors store 0, 0). Eleven
  axes keep a stale range (e.g. -90..90). Pose keys (0xA0) are optional: 38 of 62 2x1
  blends have none.
- A sequence whose clips are all deltas has flags 0x4 | 0x10 (delta, post): all 416
  such assets; no other sequence has either. R5R plays a sequence without them as a
  whole pose: an authored `subtract` clip layered on a base pose replaced it.
- Sequence flag 0x20000 does not follow the clips' 0x20000 (set on 217 sequences).
  Flag 0x40 is set on 206 clips and on their sequences.
- Animation flag 0x20 (all-zeros): a delta clip that is zero throughout, with no
  0x20000, no tracks and its data offset at the next 16-byte boundary (231 clips, the
  centre blends of aim grids). Delta scale is additive: a delta clip stores 0 for an
  unchanged bone.
- Position tracks: the step is studiomdl's, with a 128-inch floor: the larger side of
  the offsets (at least -128..128) divided by 32768 (negative) or 32767 (positive).
  9,121 of 9,128 sampled tracks store 128/32767. Many tracks use the curve modes
  (fractional decoded values), so a re-encoded clip differs by up to half a step from
  retail; imports carry the native sections instead (`animstream`).

## R5R playback and VG rendering findings

The sequence descriptor base at +0 must be zero for the native int32 relative
animation-reference table. A nonzero base selects legacy int16 animation indices
in R5R (`r5apex.exe+0x1C8AD0`). GetSequenceDuration rejects sequence indices <=0;
authored external sets therefore reserve `ref` at zero. Sequences play from the rig's
sequence assets alone, as retail's do (the drone and Mastiff import tests); scripts
name them by the asset's file name.

Animation descriptor base +0 is also zero, including embedded clips. All 25,405
surveyed S0-S3 descriptors use zero. Descriptor flag 0x20000 means usable bone
tracks; it is independent of the sequence's scale flag at the same bit. Omitting
it let cycles advance while bone poses stayed at rest. The native encoder writes
explicit tracks for every compiled bone and now sets this flag accordingly.

Studio field 0x158 uses -1 to request a virtual rig from RPak dependencies; zero
leaves the mapping absent. The surveyed S0-S3 models contain only zero or -1
(634 and 1,155 models respectively). The authored IK-chain model crashed with
zero and completed playback with -1. External-asset render models now write -1;
standalone rigs retain zero. The package verifies matching bones, and requires -1 when
the rig has IK chains.

Studio offset 0xCC points to an optional byte-per-material shader-type table:
RGDU/RGDP/RGDC/SKNU/SKNP/SKNC/WLDU/WLDC/PTCU/PTCS are values 0..9.
Material path, GUID, shader family and vertex position layout must agree.
The shader may also require attributes such as COLOR. The installed S3 SKNC
`opaque_normalz_front_sknc` shader requires float positions, packed weights and
vertex colors. Its authored float-position probe renders with `$usevertexcolor`,
without snapping positions. The builtin error shader was not a valid visual
control for that complete mesh layout. A shader-family match alone is insufficient.

All 8,469 S2 and 11,808 S3 surveyed nonempty VG meshes include flag bits 0x840.
The writer emits these bits, an identity bone palette for skinned models, and
optionally native packed positions (21/21/22-bit XYZ with biases 1024/1024/2048,
scale 1024). The existing 0.0001-inch render budget is enforced before writing.

The VG offset/count pair at 0x60/0x68 describes 48-byte auxiliary records. In all
581 installed S3 models surveyed, its count equals the studio mesh count, without
multiplying by LOD count. Omitting the buffer suppressed drawing in an isolated
R5R concrete-model test; zero-filled records restored drawing. Individual fields
remain unknown. The writer allocates zeros rather than copying native payloads.
