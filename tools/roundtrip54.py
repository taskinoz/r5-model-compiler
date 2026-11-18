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
    """Model keyvalues byte for byte (size included); jiggle bones in procedural order,
    by bone name, with each record byte for byte; RUI panels exactly (hash, name,
    parent bones by name, vertices, faces, bounds, per-face masks and mask count); and
    hitbox sets: names, bones by name, groups, crit overrides, hit data groups and boxes
    within 0.0001 in. Retail hitboxes flagged as generated must come back generated."""
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
    def panels(m):
        return [dict(p,parents=[m.bones[k]['name'] for k in p['parents']]) for p in m.ui_panels()]
    if panels(a)!=panels(b): issues.append('RUI panels differ')
    def jiggles(m):
        # records by bone name, and the per-bone slot table up to the bone-controller
        # offset (retail: the unpadded table end), by bone name
        n,o2,bc=m.get('i',0x198),m.get('i',0x1A0),m.get('i',0xAC)
        slots=[] if not n else [(m.bones[k]['name'] if k<len(m.bones) else None,m.data[o2+k]) for k in range(bc-o2)]
        return [(m.bones[j['bone']]['name'],j['raw']) for j in m.jiggle_bones()],slots
    if jiggles(a)!=jiggles(b): issues.append('jiggle bones differ')
    def linear(m):
        # the linear bone table (0x194): present or not, and a copy of the bone records
        lb=m.get('i',0x194)
        if not lb: return None
        nb,bi=m.get('i',0xA0),m.get('i',0xA4); h=m.get('7i',lb)
        if h[0]!=nb: return 'count'
        fields=((1,4,0x94),(2,4,0x04),(3,12,0x20),(4,16,0x2C),(5,12,0x3C),(6,48,0x54))
        return all(m.data[lb+h[i]+size*k:lb+h[i]+size*(k+1)]==m.data[bi+0xB8*k+at:bi+0xB8*k+at+size]
                   for i,size,at in fields for k in range(nb))
    if linear(a)!=linear(b): issues.append('linear bone table differs: %r vs %r'%(linear(a),linear(b)))
    if a.get('i',0x9C)!=b.get('i',0x9C): issues.append('header flags differ: 0x%x vs 0x%x'%(a.get('i',0x9C),b.get('i',0x9C)))
    # -1 is the external-rig sentinel ($externalassets); neither side has include models
    if a.get('i',0x158)!=b.get('i',0x158): issues.append('include-model count differs: %d vs %d'%(a.get('i',0x158),b.get('i',0x158)))
    def surface(m):
        # the header's surface property and contents, and each bone's
        names=[m.string(m.get('i',0x13C)),m.get('i',0x154)]
        for k in range(len(m.bones)):
            q=m.get('i',0xA4)+0xB8*k; names.append((m.string(q+m.get('i',q+0xA4)),m.get('i',q+0xA8)))
        return names
    if surface(a)!=surface(b): issues.append('surface properties differ: %r vs %r'%(surface(a)[0],surface(b)[0]))
    def bone_words(m):
        # each bone's flags and BVH entry (+0x94, +0xB4)
        return [(m.get('i',m.get('i',0xA4)+0xB8*k+0x94),m.get('i',m.get('i',0xA4)+0xB8*k+0xB4)) for k in range(len(m.bones))]
    if bone_words(a)!=bone_words(b):
        diff=[k for k,(x,y) in enumerate(zip(bone_words(a),bone_words(b))) if x!=y]
        issues.append('bone flags/BVH entries differ on %d bones'%len(diff))
    def lookups(m):
        # surface-property ids: the header's and each bone's
        return m.get('i',0x180),[m.get('i',m.get('i',0xA4)+0xB8*k+0xAC) for k in range(len(m.bones))]
    if lookups(a)!=lookups(b): issues.append('surface property ids differ: %r vs %r'%(lookups(a)[0],lookups(b)[0]))
    def types(m):
        # each texture slot's native shader family (0xCC), by material name
        off=m.get('i',0xCC)
        return [(x['name'],m.data[off+i]) for i,x in enumerate(m.materials)] if off else None
    if types(a)!=types(b): issues.append('material types differ')
    def skins(m):
        # families by material name (slot order included) and their names
        s=m.skins(); names=[x['name'] for x in m.materials]
        return [[names[t] for t in row] for row in s['families']],s['names']
    if skins(a)!=skins(b): issues.append('skin families differ')
    def bodyparts(m):
        # body parts by name, each model's meshes (materials, in any order) and its
        # triangle count per LOD: the choices a body group offers
        render=m.render() if m.meshes else []
        index={id(x):k for k,x in enumerate(m.meshes)}
        return [(bp['name'],[(sorted(m.materials[x['material']]['name'] for x in md['meshes']),
                              [sum(len(lod[index[id(x)]]['triangles']) for x in md['meshes']) for lod in render])
                             for md in bp['models']]) for bp in m.bodyparts]
    if bodyparts(a)!=bodyparts(b): issues.append('body parts differ')
    if not a.get('i',0x9C)&1:
        sa,sb=sets(a),sets(b)
        if [(n,[x[:5] for x in bx]) for n,bx in sa]!=[(n,[x[:5] for x in bx]) for n,bx in sb]:
            issues.append('hitbox sets differ')
        elif any(abs(u-v)>1e-4 for (_,ba),(_,bb) in zip(sa,sb) for x,y in zip(ba,bb) for u,v in zip(x[5],y[5])):
            issues.append('hitbox bounds differ')
    return dict(issues=issues)


def run(paths,target,compiler,out,render_only=False,jobs=1,with_physics=False,discard_work=False,discard_sources=False):
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
        if discard_work or discard_sources:
            import shutil
            # the result is recorded; sources (and, unless kept, rebuilds) are regenerable
            shutil.rmtree(work/'sources' if discard_sources and not discard_work else work,ignore_errors=True)
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
    p.add_argument('--discard-sources',action='store_true',help='delete only the exported sources, keeping each rebuild for field-level comparison')
    a=p.parse_args()
    if a.with_physics and not a.render_only: p.error('--with-physics extends --render-only')
    if a.jobs<1: p.error('--jobs must be positive')
    paths=[]
    for value in a.models:
        path=Path(value); paths.extend(sorted(path.rglob('*.rmdl')) if path.is_dir() else [path])
    if not paths: p.error('no model files found')
    report=run(paths,a.target,a.compiler,a.out,a.render_only,a.jobs,a.with_physics,a.discard_work,a.discard_sources)
    raise SystemExit(any(r['status']!='pass' for r in report['results']))
