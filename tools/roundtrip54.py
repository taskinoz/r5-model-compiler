"""Rebuild supported v54 sources; render-only mode explicitly excludes runtime metadata.

--with-physics (with --render-only) also exports, rebuilds and compares the PHY collision."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import subprocess
from decompile54 import decompile
from mdl54 import Model, PROFILES
from validate54 import validate
from compare_phy54 import compare as compare_phy
from compare_bvh54 import compare as compare_bvh


def compare_extras(original,rebuilt,target):
    """Model keyvalues byte for byte (size included), and hitbox sets: names, bones by
    name, groups, crit overrides, hit data groups and boxes within 0.0001 in. Retail
    hitboxes flagged as generated (header flag 1) must come back generated."""
    a,b=Model(original,target),Model(rebuilt,target); issues=[]
    def kv(m):
        i,n=m.get('i',0x140),m.get('i',0x144); return m.data[i:i+n]
    if kv(a)!=kv(b): issues.append('keyvalues differ: %r vs %r'%(kv(a),kv(b)))
    if (a.get('i',0x9C)^b.get('i',0x9C))&1: issues.append('generated-hitbox flag differs')
    def sets(m):
        out=[]
        for s in range(m.get('i',0xB0)):
            p=m.get('i',0xB4)+12*s; boxes=[]
            for k in range(m.get('i',p+4)):
                q=p+m.get('i',p+8)+0x2C*k
                name=lambda off: m.string(q+m.get('i',q+off)) if m.get('i',q+off) else ''
                boxes.append((m.bones[m.get('i',q)]['name'],m.get('i',q+4),name(0x20),m.get('i',q+0x24),name(0x28),
                              m.get('3f',q+8)+m.get('3f',q+0x14)))
            out.append((m.string(p+m.get('i',p)),boxes))
        return out
    if not a.get('i',0x9C)&1:
        sa,sb=sets(a),sets(b)
        if [(n,[x[:5] for x in bx]) for n,bx in sa]!=[(n,[x[:5] for x in bx]) for n,bx in sb]:
            issues.append('hitbox sets differ')
        elif any(abs(u-v)>1e-4 for (_,ba),(_,bb) in zip(sa,sb) for x,y in zip(ba,bb) for u,v in zip(x[5],y[5])):
            issues.append('hitbox bounds differ')
    return dict(issues=issues)


def run(paths,target,compiler,out,render_only=False,jobs=1,with_physics=False,discard_work=False):
    out=Path(out).resolve(); out.mkdir(parents=True,exist_ok=True); compiler=Path(compiler).resolve()
    scope='render plus PHY' if with_physics else 'render-only' if render_only else 'implemented native subset'
    manifest=dict(target=target,scope=scope,
                  compiler=str(compiler),compiler_sha256=hashlib.sha256(compiler.read_bytes()).hexdigest(),
                  tools={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*54.py')},
                  results=[])
    def one(item):
        index,path=item; path=Path(path).resolve(); work=out/f'{index:05d}-{path.stem}'
        result=dict(source=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        try:
            qc=decompile(path,work/'sources',target,render_only=render_only,with_physics=with_physics)
            rebuilt=work/'rebuilt.rmdl'
            command=[str(compiler),'--target',target,'-quiet','-o',str(rebuilt),str(qc)]
            process=subprocess.run(command,capture_output=True,text=True,timeout=180)
            if process.returncode: raise RuntimeError(process.stdout+process.stderr)
            result.update(status='pass',validation=validate(rebuilt,target,path,animation_metadata=not render_only))
            if result['validation']['differences']: result['status']='differ'
            retail_phy=path.with_suffix('.phy')
            # the full export includes physics, like --render-only --with-physics
            if (with_physics or not render_only) and retail_phy.exists():
                rebuilt_phy=rebuilt.with_suffix('.phy')
                if not rebuilt_phy.exists(): result['physics']=dict(issues=['no rebuilt PHY'])
                else: result['physics']=compare_phy(retail_phy,rebuilt_phy,target)
                if result['physics']['issues']: result['status']='differ'
            # keyvalues and hitboxes are exported in every mode
            result['extras']=compare_extras(path,rebuilt,target)
            if result['extras']['issues']: result['status']='differ'
            # BVH collision is rebuilt from the render mesh and PHY solids in every mode
            if Model(path,target).get('i',0x214) or Model(rebuilt,target).get('i',0x214):
                if render_only and not with_physics and path.with_suffix('.phy').exists():
                    result['bvh']=dict(issues=[],notes=['PHY not exported; BVH not compared'])
                else:
                    result['bvh']=compare_bvh(path,rebuilt)
                    if result['bvh']['issues']: result['status']='differ'
        except Exception as e: result.update(status='error',error=str(e))
        if discard_work:
            import shutil
            shutil.rmtree(work,ignore_errors=True)  # the result is recorded; sources and rebuilds are regenerable
        return result
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for result in pool.map(one,enumerate(paths)):
            manifest['results'].append(result)
            (out/'results.json').write_text(json.dumps(manifest,indent=2)+'\n')
            print(result['status'],result['source'],flush=True)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('models',nargs='+')
    p.add_argument('--target',choices=PROFILES,required=True); p.add_argument('--compiler',required=True)
    p.add_argument('--out',required=True); p.add_argument('--jobs',type=int,default=1)
    p.add_argument('--render-only',action='store_true')
    p.add_argument('--with-physics',action='store_true',help='with --render-only: also rebuild and compare PHY collision')
    p.add_argument('--discard-work',action='store_true',help='delete each model work folder (sources, rebuild) after recording its result')
    a=p.parse_args()
    if a.with_physics and not a.render_only: p.error('--with-physics extends --render-only')
    if a.jobs<1: p.error('--jobs must be positive')
    paths=[]
    for value in a.models:
        path=Path(value); paths.extend(sorted(path.rglob('*.rmdl')) if path.is_dir() else [path])
    if not paths: p.error('no model files found')
    report=run(paths,a.target,a.compiler,a.out,a.render_only,a.jobs,a.with_physics,a.discard_work)
    raise SystemExit(any(r['status']!='pass' for r in report['results']))
