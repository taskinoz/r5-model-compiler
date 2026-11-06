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

## VG revision 1

Header: 0x100 bytes, magic 0x47567430, revision 1, byte length at 0x0C. Uint64
offset/count pairs locate bone maps (0x10), meshes (0x20), uint16 indices (0x30),
vertex bytes (0x40), extra weights (0x50), auxiliary records (0x60), LODs (0x70),
legacy weights (0x80), strips (0x90). Meshes are 0x48 bytes. LODs are eight bytes:
uint16 first mesh/count and a float switch point. Studio mesh IDs select LOD meshes.

The writer keeps positions as float32, uses identity bone mapping, native packed
normal/tangent and up to three influences, optional RGBA/UV2, and float32 UV0. Normal
packing uses major-axis index/sign and two nine-bit component ratios; tangent uses
a ten-bit angle plus handedness. Each mesh has triangle-list indices and one strip.
Runtime handling of auxiliary VG fields has not been verified.

Complex VVD/VVW/VG weights are detected but rejected. Native Apex PHY/BVH remain
unimplemented; TF2's collision writer is not a valid substitute.
