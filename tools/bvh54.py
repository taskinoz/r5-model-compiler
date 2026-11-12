"""Reader for the early-Apex BVH collision block (studiohdr 0x214).

Layout (measured on the installed S3 corpus; docs/mdl-v54-format.md): a 16-byte header
(contents offset, table offset, contents end, entry count), 0x20-byte entries (packed
flag, node/vertex/leaf offsets relative to the block, integer origin, power-of-two
scale), 64-byte BVH4 nodes, and leaves: triangle lists (4 float vertices, 5 packed int16),
parallelogram quad lists (6 float, 7 packed; the fourth corner is b + c - a) and leaf
lists (3: a count, then one word per sub-leaf with its type in byte 1 and its length in
words in byte 2, the sub-leaves following in order).
"""
import struct

NODE, EMPTY, LIST, FLOAT_TRIS, PACKED_TRIS, FLOAT_QUADS, PACKED_QUADS = 0, 1, 3, 4, 5, 6, 7
DECODED = {NODE, EMPTY, LIST, FLOAT_TRIS, PACKED_TRIS, FLOAT_QUADS, PACKED_QUADS}
# quads as triangles: corners a, b, c and d = b + c - a, outline a, b, d, c
QUAD_TRIANGLES = ((0, 1, 3), (0, 3, 2))


class BvhError(ValueError):
    pass


def parse(data, block, strict=False):
    """Decode the BVH block at `block` in an rmdl; returns entries with triangles.

    Leaf boxes must contain their triangles. Retail may point two node slots at one
    child node, each box covering part of it, so node boxes are checked only when
    `strict` (compiler output, which builds a plain tree)."""
    if block <= 0 or block + 16 > len(data):
        raise BvhError('no BVH block')
    contents, table, contents_end, count = struct.unpack_from('<4i', data, block)
    if count <= 0 or table != 0x10 + 0x20 * count or not table < contents < contents_end:
        raise BvhError('unknown BVH header')
    hull, trace = struct.unpack_from('<2h', data, 0x218)
    raw = [struct.unpack_from('<4i4f', data, block + 0x10 + 0x20 * k) for k in range(count)]
    ends = sorted({v for e in raw for v in e[1:4]} | {len(data) - block})

    def end_of(offset):
        return min(x for x in ends if x > offset)
    entries = []
    for index, (packed, nodes, verts, leaves, ox, oy, oz, scale) in enumerate(raw):
        if packed not in (0, 1):
            raise BvhError('unknown entry kind %d' % packed)
        origin = (ox, oy, oz)
        step = scale * 65536
        size = 6 if packed else 12
        count_v = (end_of(verts) - verts) // size
        if packed:
            vertices = [tuple(origin[a] + v[a] * step for a in range(3))
                        for v in (struct.unpack_from('<3h', data, block + verts + 6 * k) for k in range(count_v))]
        else:
            vertices = [struct.unpack_from('<3f', data, block + verts + 12 * k) for k in range(count_v)]
        leaf_words = (end_of(leaves) - leaves) // 4
        node_count = (end_of(nodes) - nodes) // 64
        triangles, types, problems = [], {}, []
        quad_list, plain = [], []
        seen = set()

        def leaf(kind, index):  # returns the points of its corners (for the box check)
            if index >= leaf_words:
                problems.append('leaf index outside the leaf data')
                return []
            header = struct.unpack_from('<I', data, block + leaves + 4 * index)[0]
            if kind == LIST:
                count = header
                if not 1 <= count <= 16 or index + 1 + count > leaf_words:
                    problems.append('invalid leaf list')
                    return []
                points, at = [], index + 1 + count
                for k in range(count):
                    word = struct.unpack_from('<I', data, block + leaves + 4 * (index + 1 + k))[0]
                    sub, length = (word >> 8) & 0xFF, (word >> 16) & 0xFF
                    if word & 0xFF000000 or word & 0xFF or sub not in (FLOAT_TRIS, PACKED_TRIS, FLOAT_QUADS, PACKED_QUADS):
                        problems.append('unknown leaf list word %08x' % word)
                        return points
                    types[sub] = types.get(sub, 0) + 1
                    if length != 2 + ((struct.unpack_from('<I', data, block + leaves + 4 * at)[0] >> 12) & 0xF):
                        problems.append('leaf list length does not match its sub-leaf')
                    points += leaf(sub, at)
                    at += length
                return points
            if (kind in (PACKED_TRIS, PACKED_QUADS)) != bool(packed):
                problems.append('leaf type does not match the vertex kind')
            quads = kind in (FLOAT_QUADS, PACKED_QUADS)
            base = (header >> 16) * 1024  # a 1024-vertex page; the first offset adds the rest
            points = []
            for t in range(((header >> 12) & 0xF) + 1):
                if index + 1 + t >= leaf_words:
                    problems.append('leaf runs past the leaf data')
                    break
                w = struct.unpack_from('<I', data, block + leaves + 4 * (index + 1 + t))[0]
                if quads:  # A 10 bits, B 9, C 9, flags 4 (always 0xF in retail)
                    base += w & 0x3FF
                    ids = (base, base + 1 + ((w >> 10) & 0x1FF), base + 1 + ((w >> 19) & 0x1FF))
                else:  # A 11 bits, B 9, C 9, flags 3 (always 7 in retail)
                    base += w & 0x7FF
                    ids = (base, base + 1 + ((w >> 11) & 0x1FF), base + 1 + ((w >> 20) & 0x1FF))
                if max(ids) >= len(vertices):
                    problems.append('leaf vertex outside the vertex data')
                    continue
                corners = [vertices[i] for i in ids]
                if quads:
                    corners.append(tuple(corners[1][a] + corners[2][a] - corners[0][a] for a in range(3)))
                    tris = [tuple(corners[i] for i in t3) for t3 in QUAD_TRIANGLES]
                    quad_list.append(tuple(corners))
                else:
                    tris = [tuple(corners)]
                    plain.append(tris[0])
                triangles.extend(tris)
                # a computed quad corner is tagged: retail sizes boxes from the true corner,
                # which may be one packing step from b + c - a (m20_f_grenade_projectile)
                points.extend(corners[:3] + [corners[3] + ('computed',)] if quads else corners)
            return points

        def walk(index):
            if index >= node_count:
                problems.append('node index outside the node data')
                return []
            o = block + nodes + 64 * index
            axes = [struct.unpack_from('<8h', data, o + 16 * a) for a in range(3)]
            w = struct.unpack_from('<4I', data, o + 48)
            kinds = [w[2] & 0xF, (w[2] >> 4) & 0xF, w[3] & 0xF, (w[3] >> 4) & 0xF]
            points = []
            for c in range(4):
                kind, child = kinds[c], w[c] >> 8
                types[kind] = types.get(kind, 0) + 1
                if kind == EMPTY:
                    continue
                if kind == NODE:
                    if child in seen and strict:
                        problems.append('node reached twice')
                    sub = walk(child) if child not in seen else []
                    seen.add(child)
                elif kind in DECODED:
                    sub = leaf(kind, child)
                else:
                    problems.append('unknown child type %d' % kind)
                    sub = []
                if kind == NODE and not strict:
                    sub = []
                for p in sub:  # the slot's box contains everything below it
                    for a in range(3):
                        lo = origin[a] + axes[a][c] * step
                        hi = origin[a] + axes[a][4 + c] * step
                        slack = 1e-4 + (step if len(p) > 3 else 0)
                        if not lo - slack <= p[a] <= hi + slack:
                            problems.append('child box does not contain its geometry')
                            break
                points += sub if kind != NODE or strict else []
            return points
        seen.add(0)
        walk(0)
        role = 'hull' if index == hull else 'trace' if index == trace else 'solid'
        entries.append(dict(role=role, packed=bool(packed), origin=origin, scale=scale, vertices=vertices,
                            triangles=triangles, quads=quad_list, plain=plain, types=types,
                            problems=sorted(set(problems))))
    return dict(entries=entries, hull=hull, trace=trace, bounds=struct.unpack_from('<6f', data, 0x1F0))


def from_model(path, strict=False):
    with open(path, 'rb') as f:
        data = f.read()
    return parse(data, struct.unpack_from('<i', data, 0x214)[0], strict)


def triangle_key(tri, step):
    """Order-free key of a triangle's corners on the given grid."""
    return tuple(sorted(tuple(round(c / step) for c in p) for p in tri))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('model')
    a = p.parse_args()
    b = from_model(a.model)
    print('hull entry', b['hull'], 'trace entry', b['trace'], 'bounds', [round(x, 4) for x in b['bounds']])
    for i, e in enumerate(b['entries']):
        print('entry %d %s %s: %d vertices, %d triangles, types %s %s' % (
            i, e['role'], 'packed' if e['packed'] else 'float', len(e['vertices']), len(e['triangles']), e['types'],
            e['problems'] or 'ok'))
