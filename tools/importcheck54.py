"""Offline round trip of retail sequence assets through import_anim54.py.

For every retail rig with exported sequences: import each sequence the exporter
supports, compile the include on a one-triangle stub body with --external-assets,
and compare every rebuilt .rseq with its retail original (validate54's animation
metadata comparison: sequence fields, events, IK rules, movements, frame movement and
every decoded frame). Sequences the exporter refuses are counted by reason.
A sequence belongs to the rig whose .rson lists it; with --models, a sequence no rig
lists belongs to the model (.rmdl) whose .rson lists it, and plays on its skeleton.

usage: python tools/importcheck54.py --target s3 --compiler build/r5studiomdl.exe
           --rigs test-output/retail-rigs --sequences test-output/native-animation-import-s3/animseq
           --out test-output/importcheck-s3 [--models test-output/s3-raw] [--jobs 8] [--limit N]
"""
import argparse
import collections
import concurrent.futures
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mdl54 import Model, SequenceAsset, PROFILES, asset_guid  # noqa: E402
from decompile54 import export_sequences, write_smd  # noqa: E402
from import_anim54 import import_animations  # noqa: E402
from validate54 import compare_animation_metadata  # noqa: E402


def asset_label(path):
    data = Path(path).read_bytes()
    return data[struct.unpack_from('<i', data, 4)[0]:].split(b'\0')[0].decode().replace('\\', '/').lower()


def rig_key(model):
    name = model.name.replace('\\', '/').lower()
    return name[len('animrig/'):-len('.rrig')] if name.startswith('animrig/') else name


RIG_FIELDS = {0x8: 'checksum', 0xA0: 'bones', 0xF4: 'attachments', 0xFC: 'nodes', 0x108: 'node unknown',
              0x124: 'IK chains', 0x134: 'pose parameters', 0x158: 'include models'}


def compare_rigs(new_rig, rig, built, rig_path):
    """A rebuilt rig against its retail rig: header counts, node names and the node
    transitions by sequence name (retail indices name the rig's .rson list; rebuilt ones
    the asset set; transitions through sequences that were not exported are skipped)."""
    differences = []
    if rig_path.suffix.lower() != '.rrig': return dict(status='skipped', reason='model skeleton')
    for off, name in RIG_FIELDS.items():
        if new_rig.get('i', off) != rig.get('i', off): differences.append(f'rig {name}: {new_rig.get("i", off)} != {rig.get("i", off)}')
    if new_rig.node_names() != rig.node_names(): differences.append('rig node names')
    names = {}
    for line in rig_path.with_suffix('.rson').read_text(encoding='utf-8', errors='replace').splitlines():
        word = line.strip()
        if word and all(c in '0123456789abcdefABCDEF' for c in word): names[len(names)] = int(word, 16)
    built_labels = {}
    for p in built.parent.glob(built.stem + '.seq*.rseq'):
        built_labels[int(p.name[len(built.stem) + 4:-5])] = asset_label(p)
    known = {asset_guid(label) for label in built_labels.values()}
    skipped = 0
    for n, (new, old) in enumerate(zip(new_rig.node_transitions(), rig.node_transitions())):
        retail = set()
        for node, index in old:
            guid = names.get(index)
            if guid in known: retail.add((node, guid))
            else: skipped += 1
        if {(node, asset_guid(built_labels[i])) for node, i in new} != retail:
            differences.append(f'rig node {n} transitions')
    if len(new_rig.node_transitions()) != len(rig.node_transitions()): differences.append('rig transition table')
    return dict(status='differ' if differences else 'pass', differences=differences, skipped_transitions=skipped)


def check_rig(rig_path, sequence_paths, out, compiler, target):
    """Import, rebuild and compare one rig's sequences; returns per-sequence results."""
    rig = Model(rig_path, target); out.mkdir(parents=True, exist_ok=True)
    results = {}; supported = []
    with tempfile.TemporaryDirectory() as tmp:
        for p in sequence_paths:
            label = asset_label(p)
            try:
                export_sequences(SequenceAsset(p, rig), Path(tmp), namespace='probe')
                supported.append((p, label))
            except Exception as e:  # noqa: BLE001 - every refusal is recorded by reason
                results[label] = dict(status='refused', reason=str(e)[:120])
    if not supported: return results
    try:
        qci = import_animations(rig_path, [p for p, _ in supported], out / 'animations', target, namespace='r5c')
        bones = [dict(name=b['name'], parent=b['parent']) for b in rig.bones]
        pose = [[(b['pos'], b['rot'], (1, 1, 1)) for b in rig.bones]]
        tri = [('check/stub', [((0, 0, 0), (0, 0, 1), (0, 0), [(0, 1)]), ((1, 0, 0), (0, 0, 1), (1, 0), [(0, 1)]),
                               ((0, 1, 0), (0, 0, 1), (0, 1), [(0, 1)])])]
        write_smd(out / 'stub.smd', bones, pose, tri)
        qc = out / 'host.qc'
        qc.write_text('$modelname "r5c_check/host.rmdl"\n$origin 0 0 0 -90\n$body body "stub.smd"\n$include "' +
                      str(qci).replace('\\', '/') + '"\n', encoding='utf-8')
        built = out / 'host.rmdl'
        run = subprocess.run([str(compiler), '--target', target, '-quiet', '--external-assets', '-path', str(qci.parent),
                              '-o', str(built), str(qc)], capture_output=True, text=True, timeout=1800)
        if run.returncode:
            raise RuntimeError((run.stdout + run.stderr).strip()[-400:])
        new_rig = Model(built.with_suffix('.rrig'), target)
        rebuilt = {}
        for p in sorted(out.glob('host.seq*.rseq')):
            rebuilt[asset_label(p)] = p
        results['*rig'] = compare_rigs(new_rig, rig, built, rig_path)
        for p, label in supported:
            if label not in rebuilt:
                results[label] = dict(status='error', reason='no rebuilt sequence'); continue
            differences = compare_animation_metadata(SequenceAsset(rebuilt[label], new_rig), SequenceAsset(p, rig))
            results[label] = dict(status='differ' if differences else 'pass', differences=differences)
    except Exception as e:  # noqa: BLE001 - recorded per rig
        for _, label in supported:
            results.setdefault(label, dict(status='error', reason=str(e)[:400]))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--target', required=True, choices=PROFILES)
    ap.add_argument('--compiler', required=True)
    ap.add_argument('--rigs', required=True)
    ap.add_argument('--sequences', required=True)
    ap.add_argument('--models', help='folder of exported .rmdl/.rson; pairs sequences no rig lists with the model listing them')
    ap.add_argument('--out', required=True)
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--limit', type=int, help='check only the first N rigs (sorted)')
    ap.add_argument('--only', action='append', help='check only rigs whose path contains this text (repeatable)')
    args = ap.parse_args()
    out = Path(args.out).resolve(); compiler = Path(args.compiler).resolve()
    rigs = {}; listed = {}
    for p in sorted(Path(args.rigs).rglob('*.rrig')):
        key = rig_key(Model(p, args.target))
        rigs.setdefault(key, p)
        # RSX writes each rig's sequence GUIDs beside it (<rig>.rson "seqs"); a sequence
        # belongs to the rig that lists it (e.g. *_light banner sequences live in their
        # character's folder but play on empty_lights_<character>)
        rson = p.with_suffix('.rson')
        if rson.exists():
            for line in rson.read_text(encoding='utf-8', errors='replace').splitlines():
                word = line.strip()
                if word and all(c in '0123456789abcdefABCDEF' for c in word):
                    listed.setdefault(int(word, 16), key)
    # Models that play sequence assets on their own skeleton list them in their own
    # .rson (e.g. w_defender.rmdl lists charge_seq); rig lists take precedence.
    model_listed = {}
    for p in sorted(Path(args.models).rglob('*.rmdl')) if args.models else ():
        rson = p.with_suffix('.rson')
        guids = [int(w.strip(), 16) for w in rson.read_text(encoding='utf-8', errors='replace').splitlines()
                 if w.strip() and all(c in '0123456789abcdefABCDEF' for c in w.strip())] if rson.exists() else []
        if guids:
            key = rig_key(Model(p, args.target))
            rigs.setdefault(key, p)
            for g in guids: model_listed.setdefault(g, key)
    owned = collections.defaultdict(list); orphans = 0
    for p in sorted(Path(args.sequences).rglob('*.rseq')):
        label = asset_label(p); guid = asset_guid(label)
        owner = listed.get(guid) or model_listed.get(guid) or label[len('animseq/'):].rsplit('/', 1)[0]
        if owner in rigs: owned[owner].append(p)
        else: orphans += 1
    keys = [k for k in sorted(owned) if not args.only or any(o.lower() in k for o in args.only)][:args.limit]
    report = dict(target=args.target, compiler=str(compiler),
                  compiler_sha256=hashlib.sha256(compiler.read_bytes()).hexdigest(),
                  tools={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*54.py')},
                  sequences_without_rig=orphans, rigs={}, rig_checks={})
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(check_rig, rigs[k], owned[k], out / k.replace('/', '_'), compiler, args.target): k for k in keys}
        for f in concurrent.futures.as_completed(futures):
            k = futures[f]
            try: result = f.result()
            except Exception as e:  # noqa: BLE001
                result = {'*': dict(status='error', reason=str(e)[:400])}
            if '*rig' in result: report['rig_checks'][k] = result.pop('*rig')
            report['rigs'][k] = result
            counts = collections.Counter(r['status'] for r in result.values())
            print(k, dict(counts), report['rig_checks'].get(k, {}).get('status', ''), flush=True)
    totals = collections.Counter(r['status'] for rig in report['rigs'].values() for r in rig.values())
    reasons = collections.Counter(r.get('reason') or ', '.join(sorted(set((d.split(' ', 2)[-1] if d.startswith('sequence ') else d) for d in r['differences'])))
                                  for rig in report['rigs'].values() for r in rig.values() if r['status'] != 'pass')
    report['totals'] = dict(totals); report['reasons'] = dict(reasons.most_common())
    report['rig_totals'] = dict(collections.Counter(r['status'] for r in report['rig_checks'].values()))
    (out / 'importcheck.json').write_text(json.dumps(report, indent=1) + '\n')
    print('totals', dict(totals), 'sequences without an exported rig', orphans)
    print('rigs', report['rig_totals'])
    for k, r in sorted(report['rig_checks'].items()):
        if r['status'] == 'differ': print(' ', k, r['differences'][:4])
    for reason, n in reasons.most_common(25): print(n, reason)


if __name__ == '__main__':
    main()
