"""Validate the implemented v54 render/animation subset, optionally against a reference."""
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mdl54 import Model, PROFILES

LIMITS=dict(position=0.0001,normal=0.006,uv=0.00001,weight=2/32767)


def canonical(render):
    # Triangle lists may be reordered, and meshes may split by material during SMD export.
    lods=[]
    for lod in render:
        triangles=[]
        for mesh in lod:
            for tri in mesh['triangles']:
                # Keep winding; select a deterministic cyclic start.
                start=min(range(3),key=lambda i:(tuple(round(x,4) for x in tri[i]['pos']),tuple(tri[i]['uv'])))
                triangles.append(tri[start:]+tri[:start])
        lods.append(sorted(triangles,key=lambda tri:tuple(round(x,4) for v in tri for x in (*v['pos'],*v['uv']))))
    return lods


def validate(path,target,against=None):
    m=Model(path,target); render=m.render() if m.meshes else []
    result=dict(model=str(path),target=target,bones=len(m.bones),lods=len(render),
                triangles=sum(len(me['triangles']) for lod in render for me in lod),frames=0,
                limits=LIMITS,differences=[],max_error=dict.fromkeys(LIMITS,0.))
    for lod in render:
        for mesh in lod:
            for tri in mesh['triangles']:
                for v in tri:
                    if not all(math.isfinite(x) for x in (*v['pos'],*v['normal'],*v['uv'])):
                        raise ValueError('non-finite render data')
                    if any(b<0 or b>=len(m.bones) or w<0 or not math.isfinite(w) for b,w in v['weights']):
                        raise ValueError('invalid skin weights')
                    if abs(sum(w for _,w in v['weights'])-1)>1e-5: raise ValueError('unnormalized skin weights')
    for seq in m.sequences:
        for desc in seq['animations']:
            frames=m.animation(desc); result['frames']+=len(frames)
            if not all(math.isfinite(x) for pose in frames for bone in pose for channel in bone for x in channel):
                raise ValueError('non-finite animation pose')
    if against:
        ref=Model(against,target); a=canonical(render); b=canonical(ref.render() if ref.meshes else [])
        if [len(x) for x in a]!=[len(x) for x in b]: result['differences'].append('LOD triangle counts')
        else:
            for l1,l2 in zip(a,b):
                for t1,t2 in zip(l1,l2):
                    for v1,v2 in zip(t1,t2):
                        for field,kind in [('pos','position'),('normal','normal'),('uv','uv')]:
                            error=max(abs(x-y) for x,y in zip(v1[field],v2[field]))
                            result['max_error'][kind]=max(result['max_error'][kind],error)
                        w1,w2=dict(v1['weights']),dict(v2['weights'])
                        result['max_error']['weight']=max(result['max_error']['weight'],max((abs(w1.get(k,0)-w2.get(k,0)) for k in w1.keys()|w2.keys()),default=0))
            for key,limit in LIMITS.items():
                if result['max_error'][key]>limit: result['differences'].append(key)
        # This comparison deliberately reports only the selected render subset.
        result['scope']='render subset; no physics/BVH/material GUID/sequence metadata equivalence claim'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('model')
    p.add_argument('--target',required=True,choices=PROFILES); p.add_argument('--against'); p.add_argument('--out')
    a=p.parse_args(); result=validate(a.model,a.target,a.against); text=json.dumps(result,indent=2)+'\n'
    if a.out: Path(a.out).write_text(text)
    print(text); raise SystemExit(bool(result['differences']))
