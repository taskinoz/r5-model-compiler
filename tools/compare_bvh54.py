"""Compare the BVH collision of a rebuilt model with the original.

Header: entry roles (studiohdr 0x218) and the 0x1F0 box (0.0001 in).

Trace entries are LOD 0 render triangles. The rebuilt trace must reproduce the
rebuilt render triangles, winding reversed, within 1.5 of its packing steps (the rule).
Retail built its BVH from source positions that its stored render vertices only
approximate (retail BVH vertices sit 0 to about 0.001 in above the render vertices),
so retail triangles are matched to rebuilt ones within 1.5 steps plus that model's
measured retail gap, which is reported as `retail_gap`.

Hull and solid entries (retail triangulates hull faces its own way): the set of
vertices within 1.5 steps and the enclosed volume within 0.1%. Retail entries using
leaf types 3 or 7 (not decoded yet) are reported as not comparable, never as passing.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bvh54  # noqa: E402

VOLUME = 1e-3
BOX = 1e-4


def _volume(tris):
    v = 0.0
    for a, b, c in tris:
        v += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6
    return v


class Index:
    """Spatial lookup of triangles by centroid or of points."""

    def __init__(self, items, cell, centre):
        self.cell, self.centre, self.cells = cell, centre, {}
        for it in items:
            self.cells.setdefault(self._key(centre(it)), []).append(it)

    def _key(self, p):
        return tuple(int(math.floor(x / self.cell)) for x in p)

    def near(self, p):
        k = self._key(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    yield from self.cells.get((k[0] + dx, k[1] + dy, k[2] + dz), ())


def _centroid(tri):
    return tuple(sum(p[k] for p in tri) / 3 for k in range(3))


def _same(tri, cand, tol, winding=True):
    rotations = [cand[r:] + cand[:r] for r in range(3)]
    if not winding:
        rev = (cand[0], cand[2], cand[1])
        rotations += [rev[r:] + rev[:r] for r in range(3)]
    return any(all(max(abs(rot[j][n] - tri[j][n]) for n in range(3)) <= tol for j in range(3)) for rot in rotations)


def _unmatched(tris, others, tol, reverse=False):
    index = Index(others, max(4 * tol, 1e-3), _centroid)
    missing = 0
    for tri in tris:
        want = (tri[0], tri[2], tri[1]) if reverse else tri
        if not any(_same(want, cand, tol) for cand in index.near(_centroid(tri))):
            missing += 1
    return missing


def _render(path):
    from mdl54 import Model, PROFILES
    data = open(path, 'rb').read()
    for target in ('s3', 's2', 's1', 's0'):  # the render reader needs the profile
        try:
            return [tuple(tuple(v['pos']) for v in t) for mesh in Model(path, target).render()[0] for t in mesh['triangles']]
        except Exception:
            continue
    raise ValueError('cannot read render triangles of %s' % path)


def compare(original, rebuilt):
    a, b = bvh54.from_model(original), bvh54.from_model(rebuilt, strict=True)
    issues, notes, metrics = [], [], {}
    if (a['hull'], a['trace']) != (b['hull'], b['trace']) or len(a['entries']) != len(b['entries']):
        issues.append('entry roles (%d, %d) x%d vs (%d, %d) x%d' % (a['hull'], a['trace'], len(a['entries']),
                                                                  b['hull'], b['trace'], len(b['entries'])))
        return dict(issues=issues, notes=notes, metrics=metrics)
    if max(abs(x - y) for x, y in zip(a['bounds'], b['bounds'])) > BOX:
        issues.append('0x1F0 box differs')
    for i, (ea, eb) in enumerate(zip(a['entries'], b['entries'])):
        if eb['problems']:
            issues.append('entry %d: rebuilt %s' % (i, ', '.join(eb['problems'])))
        step_b = eb['scale'] * 65536
        if eb['role'] == 'trace':
            # the rule: rebuilt trace = rebuilt render triangles, winding reversed
            # render triangles with two corners at one stored position are not collision (retail
            # drops them, and so does the compiler)
            g = lambda p: tuple(round(c / step_b) for c in p)
            own = [t for t in _render(rebuilt) if len({g(p) for p in t}) == 3]
            miss = _unmatched(eb['triangles'], own, 1.5 * step_b + 1e-6, reverse=True)
            if miss or len(eb['triangles']) != len(own):
                issues.append('entry %d trace: %d of %d rebuilt triangles are not its render triangles (%d render)' % (
                    i, miss, len(eb['triangles']), len(own)))
        undecoded = set(ea['types']) - {bvh54.NODE, bvh54.EMPTY, bvh54.FLOAT_TRIS, bvh54.PACKED_TRIS}
        if undecoded:
            notes.append('entry %d (%s): original uses leaf types %s; not compared' % (i, ea['role'], sorted(undecoded)))
            continue
        step = max(ea['scale'], eb['scale']) * 65536
        if ea['role'] == 'trace':
            render = [p for t in _render(original) for p in t]
            pts = Index(render, 0.01, lambda p: p)
            gap = 0.0
            for p in {q for t in ea['triangles'] for q in t}:
                gap = max(gap, min((max(abs(p[k] - r[k]) for k in range(3)) for r in pts.near(p)), default=math.inf))
            metrics['entry %d retail_gap' % i] = gap
            tol = 1.5 * step + gap + 1e-6
            miss = _unmatched(ea['triangles'], eb['triangles'], tol)
            if miss or len(ea['triangles']) != len(eb['triangles']):
                issues.append('entry %d trace: %d of %d retail triangles unmatched (%d rebuilt)' % (
                    i, miss, len(ea['triangles']), len(eb['triangles'])))
        else:
            tol = 1.5 * step + 1e-6
            used_a = list({p for t in ea['triangles'] for p in t})
            used_b = list({p for t in eb['triangles'] for p in t})
            ia, ib = Index(used_a, max(4 * tol, 1e-3), lambda p: p), Index(used_b, max(4 * tol, 1e-3), lambda p: p)
            close = lambda p, idx: any(max(abs(p[k] - q[k]) for k in range(3)) <= tol for q in idx.near(p))
            if not all(close(p, ib) for p in used_a) or not all(close(p, ia) for p in used_b):
                issues.append('entry %d %s: vertex sets differ' % (i, ea['role']))
            va, vb = _volume(ea['triangles']), _volume(eb['triangles'])
            if abs(va - vb) > VOLUME * max(abs(va), 1e-6):
                issues.append('entry %d %s: volume %.6g vs %.6g' % (i, ea['role'], va, vb))
    return dict(issues=issues, notes=notes, metrics=metrics)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('original')
    p.add_argument('rebuilt')
    args = p.parse_args()
    result = compare(args.original, args.rebuilt)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result['issues'] else 0)
