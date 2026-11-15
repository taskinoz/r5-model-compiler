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
        # Position and UV order the triangles; normals and weights only break ties, so
        # coincident duplicates (e.g. a glow shell bound to another bone) pair up stably.
        lods.append(sorted(triangles,key=lambda tri:(tuple(round(x,4) for v in tri for x in (*v['pos'],*v['uv'])),
                                                     tuple(round(x,3) for v in tri for x in v['normal']),
                                                     tuple(tuple((k,round(w,4)) for k,w in sorted(v['weights'])) for v in tri))))
    return lods


def compare_animation_metadata(model, reference, metrics=None):
    """Compare the exported sequence subset and every decoded blend frame."""
    differences=[]
    def equal(a,b):
        if isinstance(a,dict) and isinstance(b,dict): return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
        if isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)): return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
        if isinstance(a,float) or isinstance(b,float):
            return isinstance(a,(int,float)) and isinstance(b,(int,float)) and abs(a-b)<=1e-6
        return a==b
    if not equal(model.pose_parameters(),reference.pose_parameters()): differences.append('pose parameters')
    if not equal(model.ik_chains(),reference.ik_chains()): differences.append('IK chains')
    if [b['name'] for b in model.bones]!=[b['name'] for b in reference.bones]: differences.append('animation bone identities')
    if len(model.sequences)!=len(reference.sequences): differences.append('sequence count')
    for index,(seq,ref) in enumerate(zip(model.sequences,reference.sequences)):
        if len(seq['animations'])!=len(ref['animations']): differences.append(f'sequence {index} blend count')
        a,b=model.sequence_metadata(seq),reference.sequence_metadata(ref)
        for field in a:
            if not equal(a[field],b[field]): differences.append(f'sequence {index} {field}')
        for blend,(desc,rdesc) in enumerate(zip(seq['animations'],ref['animations'])):
            if not equal(model.movements(desc),reference.movements(rdesc)):
                differences.append(f'sequence {index} blend {blend} movements')
            fm,rfm=model.frame_movement(desc),reference.frame_movement(rdesc)
            bad=bool(fm)!=bool(rfm)
            if fm and rfm:
                bad=len(fm['samples'])!=len(rfm['samples'])
                for a,b in zip(fm['samples'],rfm['samples']):
                    for c,(x,y) in enumerate(zip(a,b)):
                        error=abs(x-y)
                        if metrics is not None:
                            key='position' if c<3 else 'yaw'
                            metrics[key]=max(metrics[key],error)
                        if error>(.001 if c<3 else .005): bad=True
            if bad: differences.append(f'sequence {index} blend {blend} frame movement')
            # noforceloop steers compilation, not playback.
            if (model.get('i',desc+12)&~0x8000) != (reference.get('i',rdesc+12)&~0x8000):
                differences.append(f'sequence {index} blend {blend} flags')
            if abs(model.get('f',desc+8)-reference.get('f',rdesc+8))>1e-6:
                differences.append(f'sequence {index} blend {blend} fps')
            frames,rframes=model.animation(desc),reference.animation(rdesc)
            bad=len(frames)!=len(rframes)
            for frame,rframe in zip(frames,rframes):
                if len(frame)!=len(rframe): bad=True; break
                for bone,rbone in zip(frame,rframe):
                    for channel,(values,rvalues) in enumerate(zip(bone,rbone)):
                        for x,y in zip(values,rvalues):
                            if not math.isfinite(x) or not math.isfinite(y): bad=True; continue
                            error=abs(x-y)
                            if channel==1: error=abs((x-y+math.pi)%(2*math.pi)-math.pi)
                            if error>(.001,.0002,.0016)[channel]: bad=True
            if bad: differences.append(f'sequence {index} blend {blend} poses')
        # a reference descriptor's inline clip: present, name, frames, fps, whether it has
        # tracks, and its poses within the animation limits above
        clip,rclip=seq.get('reference_clip'),ref.get('reference_clip')
        if (clip is None)!=(rclip is None): differences.append(f'sequence {index} reference clip presence')
        elif clip is not None:
            if (model.string(clip+model.get('i',clip+4))!=reference.string(rclip+reference.get('i',rclip+4))
                    or model.get('i',clip+16)!=reference.get('i',rclip+16)
                    or abs(model.get('f',clip+8)-reference.get('f',rclip+8))>1e-6
                    or (model.get('i',clip+12)^reference.get('i',rclip+12))&0x20000):
                differences.append(f'sequence {index} reference clip descriptor')
            frames,rframes=model.reference_frames(seq),reference.reference_frames(ref)
            bad=len(frames)!=len(rframes)
            for frame,rframe in zip(frames,rframes):
                for bone,rbone in zip(frame,rframe):
                    for channel,(values,rvalues) in enumerate(zip(bone,rbone)):
                        for x,y in zip(values,rvalues):
                            error=abs(x-y) if channel!=1 else abs((x-y+math.pi)%(2*math.pi)-math.pi)
                            if not math.isfinite(error) or error>(.001,.0002,.0016)[channel]: bad=True
            if bad: differences.append(f'sequence {index} reference clip poses')
    return differences


def validate(path,target,against=None,*,animation_metadata=False):
    m=Model(path,target); render=m.render() if m.meshes else []
    m.ik_chains()
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
        if animation_metadata: m.sequence_metadata(seq)
        for desc in seq['animations']:
            m.movements(desc)
            m.frame_movement(desc)
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
        if animation_metadata:
            result['frame_movement_limits']=dict(position=.001,yaw=.005)
            result['frame_movement_max_error']=dict(position=0.,yaw=0.)
            result['differences']+=compare_animation_metadata(m,ref,result['frame_movement_max_error'])
            result['scope']='render plus supported sequence/IK-chain metadata, piecewise/native frame motion and full-frame blend poses; no physics/BVH/rig/runtime equivalence claim'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('model')
    p.add_argument('--target',required=True,choices=PROFILES); p.add_argument('--against'); p.add_argument('--out')
    p.add_argument('--animation-metadata',action='store_true')
    a=p.parse_args(); result=validate(a.model,a.target,a.against,animation_metadata=a.animation_metadata); text=json.dumps(result,indent=2)+'\n'
    if a.out: Path(a.out).write_text(text)
    print(text); raise SystemExit(bool(result['differences']))
