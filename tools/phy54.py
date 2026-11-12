"""Reader for early-Apex (S0-S3) PHY files: convex hulls with polygon faces.

Layout (measured over every installed S0-S3 PHY; docs/mdl-v54-format.md):
  header   int size (20), int id (1), int16 solids, int16 0, int checksum, int keyvalue offset
  table    at 0x14: int64 solid table offset (0x20), int64 solid count, int64 0, int64 data size
  solid    0x90: int64 hull offset, int64 hull count, float 1.0 + 3 zero words, centre (vec4),
           inertia per unit mass about the solid origin (3 vec4 rows), centre again (vec4),
           bounds min/max (vec3 + vec3), two zero words
  hull     0x40: centroid + inscribed radius (vec4), then {offset, count} int64 pairs for
           float3 vertices, 32-byte faces (byte vertex loops ended by 0xFF) and edges
           (two vertex bytes; S3 adds the face running v0->v1 and the face running v1->v0)
Offsets inside the solid data are relative to byte 0x14. Keyvalue text follows the data.
"""
import struct

BASE = 0x14
SOLID_SIZE = 0x90
HULL_SIZE = 0x40
FACE_SIZE = 32


class PhyError(ValueError):
    pass


def edge_size(target):
    return 4 if target == 's3' else 2


def parse(data, target):
    """Parse and structurally validate a PHY; returns dict(checksum, solids, text)."""
    es = edge_size(target)
    if len(data) < BASE + 0x20:
        raise PhyError('truncated header')
    size, ident, count, align, checksum, kv = struct.unpack_from('<iihhii', data, 0)
    table, z0, count2, z1, z2, z3, total, z4 = struct.unpack_from('<8i', data, BASE)
    if (size, ident, align, table) != (20, 1, 0, 0x20) or any((z0, z1, z2, z3, z4)):
        raise PhyError('unknown PHY header')
    if count2 != count or count <= 0 or kv != BASE + total or kv > len(data):
        raise PhyError('inconsistent solid count or size')
    end = data.find(b'\0', kv)
    if end < 0:
        raise PhyError('unterminated keyvalue text')
    text = data[kv:end].decode('latin-1')

    def at(offset, n):
        if offset < 0 or BASE + offset + n > kv:
            raise PhyError('offset outside the solid data')
        return BASE + offset

    def vec(o):
        return struct.unpack_from('<3f', data, o)

    spans = [(0, 0x20)]
    solids = []
    for si in range(count):
        so = at(table + si * SOLID_SIZE, SOLID_SIZE)
        spans.append((so - BASE, so - BASE + SOLID_SIZE))
        hull_off, hz, nh, hz2 = struct.unpack_from('<4i', data, so)
        if hz or hz2 or nh <= 0:
            raise PhyError('bad hull table')
        solid = dict(
            unknown_10=struct.unpack_from('<4i', data, so + 0x10),
            centre=vec(so + 0x20),
            inertia=[vec(so + 0x30 + 16 * r) for r in range(3)],
            centre2=vec(so + 0x60),
            mins=vec(so + 0x70), maxs=vec(so + 0x7C),
            hulls=[])
        for hi in range(nh):
            ho = at(hull_off + hi * HULL_SIZE, HULL_SIZE)
            spans.append((ho - BASE, ho - BASE + HULL_SIZE))
            cx, cy, cz, radius = struct.unpack_from('<4f', data, ho)
            parts = [struct.unpack_from('<4i', data, ho + 16 + 16 * k) for k in range(3)]
            if any(p[1] or p[3] for p in parts):
                raise PhyError('bad hull pointer')
            (vo, _, nv, _), (fo, _, nf, _), (eo, _, ne, _) = parts
            o = at(vo, 12 * nv)
            verts = [vec(o + 12 * k) for k in range(nv)]
            o = at(fo, FACE_SIZE * nf)
            faces = []
            for k in range(nf):
                raw = data[o + FACE_SIZE * k:o + FACE_SIZE * (k + 1)]
                loop = list(raw.split(b'\xff')[0])
                if any(b != 0xFF for b in raw[len(loop):]) or len(loop) < 3 or any(v >= nv for v in loop):
                    raise PhyError('bad face')
                faces.append(loop)
            o = at(eo, es * ne)
            edges = [tuple(data[o + es * k:o + es * (k + 1)]) for k in range(ne)]
            spans += [(vo, vo + 12 * nv), (fo, fo + FACE_SIZE * nf), (eo, eo + es * ne)]
            solid['hulls'].append(dict(centroid=(cx, cy, cz), radius=radius, verts=verts, faces=faces, edges=edges))
        solids.append(solid)
    spans.sort()
    pos = 0
    for a, b in spans:
        if a != pos:
            raise PhyError('gap or overlap in solid data at %#x' % (BASE + min(a, pos)))
        pos = b
    if pos != total:
        raise PhyError('unused bytes after the solid data')
    return dict(checksum=checksum, solids=solids, text=text)


def check_hull(hull, edge_faces):
    """Topology problems of one hull (empty when it is a closed polyhedron)."""
    problems = []
    nv, nf, ne = len(hull['verts']), len(hull['faces']), len(hull['edges'])
    directed = {}
    for f, loop in enumerate(hull['faces']):
        for k in range(len(loop)):
            directed[(loop[k], loop[(k + 1) % len(loop)])] = f
    undirected = {frozenset(e[:2]) for e in hull['edges']}
    if len(undirected) != ne or undirected != {frozenset(k) for k in directed}:
        problems.append('edges do not match the face loops')
    if any((b, a) not in directed for a, b in directed):
        problems.append('open surface')
    if nv - ne + nf != 2:
        problems.append('Euler characteristic %d' % (nv - ne + nf))
    if edge_faces:
        for e in hull['edges']:
            if len(e) == 4 and (directed.get((e[0], e[1])) != e[2] or directed.get((e[1], e[0])) != e[3]):
                problems.append('edge face links differ')
                break
    return problems


def hull_mass(hull):
    """Volume, centroid and inertia about the centroid (unit density) of a hull."""
    verts = hull['verts']
    vol = 0.0
    c = [0.0] * 3
    s = [[0.0] * 3 for _ in range(3)]
    for loop in hull['faces']:
        a = verts[loop[0]]
        for k in range(1, len(loop) - 1):
            b, d = verts[loop[k]], verts[loop[k + 1]]
            v = (a[0] * (b[1] * d[2] - b[2] * d[1]) - a[1] * (b[0] * d[2] - b[2] * d[0]) + a[2] * (b[0] * d[1] - b[1] * d[0])) / 6
            vol += v
            for i in range(3):
                c[i] += v * (a[i] + b[i] + d[i]) / 4
                for j in range(3):
                    s[i][j] += v / 20 * (a[i] * a[j] + b[i] * b[j] + d[i] * d[j] + (a[i] + b[i] + d[i]) * (a[j] + b[j] + d[j]))
    if vol == 0:
        return 0.0, (0.0, 0.0, 0.0), [[0.0] * 3 for _ in range(3)]
    c = [x / vol for x in c]
    for i in range(3):
        for j in range(3):
            s[i][j] -= vol * c[i] * c[j]
    inertia = [[(s[0][0] + s[1][1] + s[2][2] - s[i][i]) if i == j else -s[i][j] for j in range(3)] for i in range(3)]
    return vol, tuple(c), inertia


if __name__ == '__main__':
    import argparse
    import json
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phy')
    p.add_argument('--target', required=True, choices=('s0', 's1', 's2', 's3'))
    a = p.parse_args()
    parsed = parse(open(a.phy, 'rb').read(), a.target)
    for i, s in enumerate(parsed['solids']):
        print('solid', i, 'hulls', len(s['hulls']), 'centre', [round(x, 4) for x in s['centre']])
        for h in s['hulls']:
            print('  hull verts %d faces %d edges %d radius %.4f' % (len(h['verts']), len(h['faces']), len(h['edges']), h['radius']),
                  check_hull(h, a.target == 's3') or 'closed')
    print(parsed['text'])
