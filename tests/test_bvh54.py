"""Reader tests for the early-Apex BVH leaf formats, on hand-built blocks."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import bvh54  # noqa: E402


def block(vertices, leaf_words, child_type, packed=True, scale=2.0 ** -16, origin=(0, 0, 0)):
    """An rmdl-shaped buffer: header roles at 0x218, one entry, one node whose slot 0
    is `child_type` at leaf word 0, with a box around every vertex (+ one unit)."""
    start = 0x240
    step = scale * 65536
    q = [[int(round((v[a] - origin[a]) / step)) for a in range(3)] for v in vertices]
    if packed:
        vbytes = b''.join(struct.pack('<3h', *p) for p in q)
    else:
        vbytes = b''.join(struct.pack('<3f', *v) for v in vertices)
    vbytes += b'\0' * (-len(vbytes) % 4)
    lbytes = struct.pack('<%dI' % len(leaf_words), *leaf_words)
    header_size = 0x10 + 0x20 + 8 + 4 + 4  # entry, table, contents, pad
    verts = header_size
    leaves = verts + len(vbytes)
    nodes = leaves + len(lbytes)
    nodes += -nodes % 64
    lo = [min(p[a] for p in q) - 1 for a in range(3)]
    hi = [max(p[a] for p in q) + 1 for a in range(3)]
    node = b''
    for a in range(3):
        node += struct.pack('<8h', lo[a], 32767, 32767, 32767, hi[a], -32768, -32768, -32768)
    node += struct.pack('<4I', 0, 0, child_type | 1 << 4, 1 | 1 << 4)
    data = bytearray(start)
    struct.pack_into('<2h', data, 0x218, 0, -1)  # entry 0 is the physics hull
    struct.pack_into('<i', data, 0x214, start)
    blk = bytearray(struct.pack('<4i', 0x10 + 0x20 + 8, 0x30, 0x10 + 0x20 + 12, 1))
    blk += struct.pack('<4i4f', 1 if packed else 0, nodes, verts, leaves, *origin, scale)
    blk += struct.pack('<2I', 0, 0) + struct.pack('<I', 1) + b'\0' * 4
    blk += vbytes + lbytes
    blk += b'\0' * (nodes - len(blk)) + node
    return bytes(data + blk), start


CUBE = [(x, y, z) for x in (0.0, 4.0) for y in (0.0, 4.0) for z in (0.0, 4.0)]


def quad_word(da, b, c):
    return da | b << 10 | c << 19 | 0xF << 28


def tri_word(da, b, c):
    return da | b << 11 | c << 20 | 7 << 29


class BvhLeaves(unittest.TestCase):
    def test_packed_quad_fourth_corner_is_not_stored(self):
        # bottom face 0,2,6,(4): store a=0, b=2, c=4 (vertex 4 = (4,0,0)); d = b + c - a
        data, start = block(CUBE[:6], [0 << 16 | 0 << 12, quad_word(0, 1, 3)], bvh54.PACKED_QUADS)
        (entry,) = bvh54.parse(data, start, strict=True)['entries']
        self.assertEqual(entry['problems'], [])
        (q,) = entry['quads']
        self.assertEqual(q[3], (4.0, 4.0, 0.0))  # vertex 6 was not in the vertex data
        self.assertEqual(len(entry['triangles']), 2)
        area = 0.0
        for a, b, c in entry['triangles']:
            area += abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2
        self.assertEqual(area, 16.0)

    def test_leaf_list_with_quads_and_triangles(self):
        # list: a one-quad leaf (2 words) and a two-triangle leaf (3 words), in order
        words = [2, 7 << 8 | 2 << 16, 5 << 8 | 3 << 16,
                 0 << 16 | 0 << 12 | 1, quad_word(0, 1, 3),
                 0 << 16 | 1 << 12 | 1, tri_word(1, 0, 2), tri_word(1, 1, 4)]
        data, start = block(CUBE, words, bvh54.LIST)
        (entry,) = bvh54.parse(data, start, strict=True)['entries']
        self.assertEqual(entry['problems'], [])
        self.assertEqual(entry['types'].get(bvh54.PACKED_QUADS), 1)
        self.assertEqual(entry['types'].get(bvh54.PACKED_TRIS), 1)
        self.assertEqual(len(entry['quads']), 1)
        # triangles: base 1 -> (1, 2, 4); base 2 -> (2, 4, 7)
        self.assertEqual(entry['plain'], [(CUBE[1], CUBE[2], CUBE[4]), (CUBE[2], CUBE[4], CUBE[7])])

    def test_leaf_list_length_mismatch_is_reported(self):
        words = [1, 5 << 8 | 4 << 16, 0 << 16 | 0 << 12, tri_word(0, 0, 1)]
        data, start = block(CUBE, words, bvh54.LIST)
        (entry,) = bvh54.parse(data, start, strict=True)['entries']
        self.assertIn('leaf list length does not match its sub-leaf', entry['problems'])

    def test_float_quads(self):
        data, start = block(CUBE[:6], [0, quad_word(0, 1, 3)], bvh54.FLOAT_QUADS, packed=False)
        (entry,) = bvh54.parse(data, start, strict=True)['entries']
        self.assertEqual(entry['problems'], [])
        self.assertEqual(entry['quads'][0][3], (4.0, 4.0, 0.0))

    def test_quad_page_offsets(self):
        # 1,100 vertices on a line; a quad on page 1 (vertex 1024 + 30)
        verts = [(float(i), 0.0, 0.0) for i in range(1100)]
        verts[1054] = (0.0, 0.0, 0.0)
        verts[1055] = (2.0, 0.0, 0.0)
        verts[1056] = (0.0, 3.0, 0.0)
        data, start = block(verts, [1 << 16, quad_word(30, 0, 1)], bvh54.PACKED_QUADS, scale=2.0 ** -20)  # a 1/16 in step
        (entry,) = bvh54.parse(data, start, strict=True)['entries']
        self.assertEqual(entry['problems'], [])
        self.assertEqual(entry['quads'][0], ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0), (2.0, 3.0, 0.0)))


if __name__ == '__main__':
    unittest.main()
