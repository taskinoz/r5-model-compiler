"""Field-level comparison of studiohdr fields across a kept-rebuild round trip.

Reads the results.json files of a `roundtrip54.py --discard-sources` run and compares
each rebuilt model's header with its retail source: counts, flags and float fields by
value, offset fields by presence (zero or not), since a rebuild lays data out
differently. Prints each differing field with its model count and examples, to find
retail values the compiler does not reproduce yet.

usage: python tools/headerdiff54.py --target s3 test-output/<run>/out [--json report.json]
"""
import argparse
import collections
import json
from pathlib import Path
import re
import struct
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mdl54 import PROFILES

ROOT = Path(__file__).resolve().parent.parent


def header_fields():
    """Header field names and offsets from the native writer's table."""
    text = (ROOT / 'src/write/mdl_writer.cpp').read_text(encoding='utf-8')
    fields = {int(off, 16): name for name, off in re.findall(r'(H_[A-Z0-9_]+) = (0x[0-9A-F]+)', text)}
    fields.pop(0x224, None)  # H_SIZE is the header size, not a field
    return dict(sorted(fields.items()))


# fields whose value is an offset or a file-dependent size: compared by presence only
LAYOUT = re.compile(r'INDEX|OFFSET|LOOKUP|LENGTH|CHECKSUM|SIZE$|VIRTUALMODEL|NAME$|SZNAME')
FLOATS = {'H_EYEPOS': 3, 'H_ILLUMPOS': 3, 'H_HULLMIN': 3, 'H_HULLMAX': 3, 'H_VIEWMIN': 3, 'H_VIEWMAX': 3,
          'H_MASS': 1, 'H_FADEDISTANCE': 1, 'H_VERTANIMSCALE': 1}
BYTES = {'H_CONSTDIRLIGHTDOT', 'H_ROOTLOD', 'H_NUMALLOWEDROOTLODS'}


def value(data, off, name):
    if name in FLOATS: return tuple(round(v, 4) for v in struct.unpack_from('<%df' % FLOATS[name], data, off))
    if name in BYTES: return data[off]
    v = struct.unpack_from('<i', data, off)[0]
    return bool(v) if LAYOUT.search(name) else v


def compare(runs):
    fields = header_fields()
    diffs = collections.defaultdict(list); total = 0
    for results in runs:
        report = json.loads(Path(results).read_text())
        for i, r in enumerate(report['results']):
            if r.get('status') == 'error': continue
            src = Path(r['source']); rebuilt = Path(results).parent / f'{i:05d}-{src.stem}' / 'rebuilt.rmdl'
            if not rebuilt.exists(): continue
            a, b = src.read_bytes(), rebuilt.read_bytes(); total += 1
            for off, name in fields.items():
                va, vb = value(a, off, name), value(b, off, name)
                if va != vb: diffs[name].append((src.name, va, vb))
    return total, diffs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('out'); p.add_argument('--target', required=True, choices=PROFILES); p.add_argument('--json')
    a = p.parse_args()
    runs = sorted(Path(a.out).rglob('results.json'))
    total, diffs = compare(runs)
    print('models compared:', total)
    for name, rows in sorted(diffs.items(), key=lambda kv: -len(kv[1])):
        print(f'{name}: {len(rows)}  e.g. {rows[:3]}')
    if a.json:
        Path(a.json).write_text(json.dumps({k: v for k, v in diffs.items()}, indent=1, default=str))


if __name__ == '__main__': main()
