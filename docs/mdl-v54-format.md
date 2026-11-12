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
embedded blends and a 1x1 grid, including reference descriptors both with and
without flag 0x80000. They are decoded as descriptors, not fabricated as clips.
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

## BVH (decoding in progress; not written by the compiler)

Models with collision also carry a BVH at header 0x214 (bounds at 0x1F0..0x207). Models
with a BVH can be exported only with `--drop-bvh` or `--render-only`, which state that
it is not preserved. Measured over the S3 corpus (354 models, 1,394 entries):

- Block header: int a, int b, int c, int entry count. b = 0x10 + 0x20 * count; a follows
  b by 8 (sometimes 16-32) bytes of a small table whose words look like surface
  references (e.g. 0x001D0000); c = a + 4 and the word at a is 1 (8 in three models).
- Entries (0x20 each, at 0x10): int 1, then node, packed-vertex and leaf offsets
  (relative to the block), an integer origin (vec3) and a power-of-two scale
  (2^-30..2^-23). A packed vertex is three int16; position = origin + (v << 16) * scale.
- Entry roles: header 0x218 holds two int16: the physics-hull entry and the trace-mesh
  entry (-1 for none). Rigid models with a PHY have (1, 0) (entry 0 the collision mesh,
  entry 1 the convex hull) or (0, -1); static models (-1, 0); jointed models (-1, -1)
  with one entry per PHY solid.
- Nodes (BVH4, 0x40): per axis eight int16, four child minima then four child maxima,
  in the packed-vertex units of the entry (minima rounded down, maxima up). Then four
  words: child index in the high 24 bits; the low byte of word 2 holds the types of
  children 0 and 1 (low nibble first), that of word 3 children 2 and 3. Child types:
  0 node, 1 empty, 3 leaf list, 4 unpacked triangles, 5 packed triangles, 7 packed
  quads. Two slots of a node may point at the same child node with different boxes,
  each covering part of it (a DAG, not a strict tree).
- Type 5 leaves (index = word offset into the leaf data): header word with bits 12-15
  = triangle count - 1, bits 16-31 = first vertex, bits 0-11 = a small table index
  (0-3); then one word per triangle: A (11 bits) adds to a running base vertex (the
  first triangle's base is the first vertex), the corners are base, base + 1 + B (9
  bits) and base + 1 + C (9 bits); the top three bits were 7 in every S3 triangle.
  This decodes every triangle of the tested models exactly (positions within the
  packing step).
- Type 3 leaves (convex hull entries) list sub-leaves: a count, then one word per
  sub-leaf with its type in byte 1 and a 16-bit field (a type 5 field is its word offset
  after the list); quads (type 7) are one word each. Not fully decoded.


## Standalone rigs and sequences

`--external-assets` writes a render model retaining embedded clips with an empty
`ref` sequence at index zero, a full native studio-header `.rrig` containing the shared skeleton,
attachments, hitboxes, IK chains and pose parameters, and one `.rseq` per sequence.
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
its sequences. VG bytes go to a mandatory streaming file. The `.assetset` file is
a compiler packaging manifest, not an engine asset: ASCII `R5AS1`, target, sequence
count, each on a separate line. It prevents stale numbered sequence assets from
being accidentally linked after recompilation. These facts establish the packaged
asset structure; live rig resolution and streaming still require a runtime test.

## R5R playback and VG rendering findings

The sequence descriptor base at +0 must be zero for the native int32 relative
animation-reference table. A nonzero base selects legacy int16 animation indices
in R5R (`r5apex.exe+0x1C8AD0`). GetSequenceDuration rejects sequence indices <=0;
authored external sets therefore reserve `ref` at zero. Embedded native clips
play in R5R; external-rig-only playback remains unverified.

Animation descriptor base +0 is also zero, including embedded clips. All 25,405
surveyed S0-S3 descriptors use zero. Descriptor flag 0x20000 means usable bone
tracks; it is independent of the sequence's scale flag at the same bit. Omitting
it let cycles advance while bone poses stayed at rest. The native encoder writes
explicit tracks for every compiled bone and now sets this flag accordingly.

Studio field 0x158 uses -1 to request a virtual rig from RPak dependencies; zero
leaves the mapping absent. The surveyed S0-S3 models contain only zero or -1
(634 and 1,155 models respectively). The authored IK-chain model crashed with
zero and completed playback with -1. External-asset render models now write -1;
standalone rigs retain zero. The package verifies matching bones and IK chains.

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
