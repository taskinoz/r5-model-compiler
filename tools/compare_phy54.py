"""Compare two early-Apex PHY files (retail vs rebuilt) field by field.

Solids are compared in order; hulls, vertices and faces regardless of order. Hull
points: S3 stores the hull's volume centroid; S0-S2 retail stores another interior
point, so for those profiles the rebuilt centroid is checked against the centroid of
the retail hull and the stored point only for lying inside it. Every measured error is
reported with the fixed limits below; limits are never widened to make a model pass.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phy54  # noqa: E402

POSITION = 1e-4      # inches: vertices and bounds (float32 copies)
DERIVED = 1e-4       # relative to the hull/solid size: centroids, radii, centres
INERTIA = 1e-4       # relative to the largest inertia component of the solid
KEYVALUE = 1e-5      # relative, for numeric keyvalues (written with six decimals)


def _keyvalues(text):
    blocks = []
    for name, body in re.findall(r'(\w+)\s*\{([^}]*)\}', text):
        blocks.append((name, re.findall(r'"([^"]+)"\s+"([^"]*)"', body)))
    return blocks


def _same_value(a, b):
    try:
        x, y = float(a), float(b)
    except ValueError:
        return a.lower() == b.lower(), 0.0
    err = abs(x - y) / max(1.0, abs(x))
    return err <= KEYVALUE, err


def _inside(hull, p):
    v = hull['verts']
    for loop in hull['faces']:
        a, b, c = v[loop[0]], v[loop[1]], v[loop[2]]
        n = [(b[1]-a[1])*(c[2]-a[2])-(b[2]-a[2])*(c[1]-a[1]), (b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]),
             (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])]
        if sum(n[j] * (p[j] - a[j]) for j in range(3)) > 1e-3 * math.sqrt(sum(x * x for x in n)):
            return False
    return True


def compare(retail_path, rebuilt_path, target):
    a = phy54.parse(Path(retail_path).read_bytes(), target)
    b = phy54.parse(Path(rebuilt_path).read_bytes(), target)
    issues, worst = [], dict(position=0.0, derived=0.0, inertia=0.0, keyvalue=0.0)
    if len(a['solids']) != len(b['solids']):
        return dict(issues=['solid count %d vs %d' % (len(a['solids']), len(b['solids']))], worst=worst)
    for si, (sa, sb) in enumerate(zip(a['solids'], b['solids'])):
        size = max(max(abs(x) for x in sa['mins'] + sa['maxs']), 1.0)
        if len(sa['hulls']) != len(sb['hulls']):
            issues.append('solid %d: hull count %d vs %d' % (si, len(sa['hulls']), len(sb['hulls'])))
            continue
        unmatched = list(range(len(sb['hulls'])))
        for hi, ha in enumerate(sa['hulls']):
            # pair hulls by vertex sets
            best, best_err = None, None
            for k in unmatched:
                hb = sb['hulls'][k]
                if len(hb['verts']) != len(ha['verts']):
                    continue
                err = max(min(math.dist(p, q) for q in hb['verts']) for p in ha['verts'])
                if best_err is None or err < best_err:
                    best, best_err = k, err
            if best is None:
                issues.append('solid %d hull %d: no rebuilt hull with %d vertices' % (si, hi, len(ha['verts'])))
                continue
            unmatched.remove(best)
            hb = sb['hulls'][best]
            worst['position'] = max(worst['position'], best_err)
            if best_err > POSITION:
                issues.append('solid %d hull %d: vertex error %.3g' % (si, hi, best_err))
                continue
            # faces as loops of retail vertex indices (each rebuilt vertex paired with its
            # nearest retail vertex), rotated to a canonical start: compares winding too
            pair = [min(range(len(ha['verts'])), key=lambda i: math.dist(ha['verts'][i], v)) for v in hb['verts']]

            def canonical(loop):
                k = loop.index(min(loop))
                return tuple(loop[k:] + loop[:k])
            faces_a = sorted(canonical(list(f)) for f in ha['faces'])
            faces_b = sorted(canonical([pair[v] for v in f]) for f in hb['faces'])
            if len(set(pair)) != len(pair) or faces_a != faces_b:
                issues.append('solid %d hull %d: faces differ (%d vs %d)' % (si, hi, len(ha['faces']), len(hb['faces'])))
            if len(ha['edges']) != len(hb['edges']):
                issues.append('solid %d hull %d: edge count %d vs %d' % (si, hi, len(ha['edges']), len(hb['edges'])))
            problems = phy54.check_hull(hb, target == 's3')
            if problems:
                issues.append('solid %d hull %d: rebuilt hull %s' % (si, hi, ', '.join(problems)))
            _, centroid, _ = phy54.hull_mass(ha)
            hull_size = max(max(abs(c) for v in ha['verts'] for c in v), 1.0)
            reference = ha['centroid'] if target == 's3' else centroid
            err = math.dist(reference, hb['centroid']) / hull_size
            worst['derived'] = max(worst['derived'], err)
            if err > DERIVED:
                issues.append('solid %d hull %d: centroid error %.3g' % (si, hi, err))
            if target != 's3' and not _inside(ha, ha['centroid']):
                issues.append('solid %d hull %d: retail interior point lies outside its hull' % (si, hi))
            if target == 's3':
                err = abs(ha['radius'] - hb['radius']) / hull_size
                worst['derived'] = max(worst['derived'], err)
                if err > DERIVED:
                    issues.append('solid %d hull %d: radius %.6g vs %.6g' % (si, hi, ha['radius'], hb['radius']))
        for field in ('centre', 'centre2'):
            err = math.dist(sa[field], sb[field]) / size
            worst['derived'] = max(worst['derived'], err)
            if err > DERIVED:
                issues.append('solid %d: %s error %.3g' % (si, field, err))
        for field in ('mins', 'maxs'):
            err = math.dist(sa[field], sb[field])
            worst['position'] = max(worst['position'], err)
            if err > POSITION:
                issues.append('solid %d: %s error %.3g' % (si, field, err))
        scale = max(max(abs(x) for row in sa['inertia'] for x in row), 1e-12)
        err = max(abs(sa['inertia'][r][c] - sb['inertia'][r][c]) for r in range(3) for c in range(3)) / scale
        worst['inertia'] = max(worst['inertia'], err)
        if err > INERTIA:
            issues.append('solid %d: inertia error %.3g' % (si, err))
    ka, kb = _keyvalues(a['text']), _keyvalues(b['text'])
    if [n for n, _ in ka] != [n for n, _ in kb]:
        issues.append('keyvalue blocks %s vs %s' % ([n for n, _ in ka], [n for n, _ in kb]))
    else:
        for (name, pa), (_, pb) in zip(ka, kb):
            # keys can repeat (jointmerge, collisionpair): compare each key's values in order
            va, vb = {}, {}
            for k, v in pa:
                va.setdefault(k, []).append(v)
            for k, v in pb:
                vb.setdefault(k, []).append(v)
            if set(va) != set(vb):
                issues.append('%s keys differ: %s' % (name, sorted(set(va) ^ set(vb))))
            for k in sorted(set(va) & set(vb)):
                if len(va[k]) != len(vb[k]):
                    issues.append('%s %s: %d vs %d values' % (name, k, len(va[k]), len(vb[k])))
                    continue
                for x, y in zip(va[k], vb[k]):
                    ok, err = _same_value(x, y)
                    worst['keyvalue'] = max(worst['keyvalue'], err)
                    if not ok:
                        issues.append('%s %s: %s vs %s' % (name, k, x, y))
    return dict(issues=issues, worst=worst)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('retail')
    p.add_argument('rebuilt')
    p.add_argument('--target', required=True, choices=('s0', 's1', 's2', 's3'))
    args = p.parse_args()
    result = compare(args.retail, args.rebuilt, args.target)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result['issues'] else 0)
