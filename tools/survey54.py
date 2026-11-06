"""Survey raw Apex assets extracted from an owned install; no compiler parity claim."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mdl54 import Model, PROFILES


def survey(root,target,geometry=False):
    result=dict(target=target,profile=PROFILES[target],root=str(Path(root).resolve()),models=0,
                parsed=0,geometry_checked=0,triangles=0,bones=0,features={},errors=[])
    counts=collections.Counter()
    for path in sorted(Path(root).rglob('*.rmdl')):
        result['models']+=1
        try:
            m=Model(path,target); result['parsed']+=1; result['bones']+=len(m.bones)
            for name,off in [('sequences',0xC0),('physics',0x1DC),('bvh',0x214),('rui',0x12C),
                             ('procedural',0x198),('followers',0x1E8),('ik',0x124),('pose_parameters',0x134)]:
                counts[name]+=int(bool(m.get('i',off)))
            if geometry:
                render=m.render() if m.meshes else []
                result['triangles']+=sum(len(mesh['triangles']) for lod in render for mesh in lod)
                result['geometry_checked']+=1
        except Exception as e:
            result['errors'].append(dict(path=str(path),error=str(e)))
    result['features']=dict(counts)
    result['reader_sha256']=hashlib.sha256(Path(__file__).with_name('mdl54.py').read_bytes()).hexdigest()
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('root')
    p.add_argument('--target',choices=PROFILES,required=True); p.add_argument('--out',required=True)
    p.add_argument('--geometry',action='store_true'); a=p.parse_args()
    result=survey(a.root,a.target,a.geometry); Path(a.out).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('errors','features')},indent=2))
    print('errors:',len(result['errors']))
