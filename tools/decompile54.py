"""Export the supported early-Apex model subset to QC + SMD (no game assets included)."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import argparse
import math
from mdl54 import Model, PROFILES
from decompile53 import write_dmx, matrix_angles, qc_quote


def write_smd(path,bones,frames,tris=None):
    """Nine significant digits preserve float32 mesh attributes and angles."""
    fmt=lambda values:' '.join(format(x,'.9g') for x in values)
    with open(path,'w',encoding='utf-8',newline='\n') as f:
        f.write('version 1\nnodes\n')
        for i,b in enumerate(bones): f.write(f'{i} "{b["name"]}" {b["parent"]}\n')
        f.write('end\nskeleton\n')
        for index,frame in enumerate(frames):
            f.write(f'time {index}\n')
            for i,b in enumerate(frame): f.write(f'{i} '+fmt(x for channel in b for x in channel)+'\n')
        f.write('end\n')
        if tris is not None:
            f.write('triangles\n')
            for material,tri in tris:
                f.write(material+'\n')
                for pos,normal,uv,weights in tri:
                    row='0 '+fmt((*pos,*normal,uv[0],1-uv[1]))+' '+str(len(weights))
                    for bone,weight in weights: row+=f' {bone} {weight:.9g}'
                    f.write(row+'\n')
            f.write('end\n')


def decompile(path, outdir, target, *, render_only=False):
    m=Model(path,target); out=Path(outdir); out.mkdir(parents=True,exist_ok=True)
    # Unsupported information is never silently claimed to roundtrip.
    unsupported=[]
    for label,offset in [('physics',0x1DC),('BVH collision',0x214),('RUI',0x12C),
                         ('procedural bones',0x198),('followers',0x1E8),('include models',0x158),
                         ('IK chains',0x124),('pose parameters',0x134)]:
        if m.get('i',offset): unsupported.append(label)
    if any(b['proctype'] for b in m.bones): unsupported.append('bone procedures')
    if unsupported and not render_only:
        raise ValueError('unsupported for native export: '+', '.join(unsupported)+'; use --render-only for an explicit geometry export')
    skeleton=[(b['pos'],b['rot'],b['scale']) for b in m.bones]
    lines=['// r5 --target '+target]
    if render_only: lines+=['// Geometry export: physics, BVH, rigs and sequence metadata are not preserved.']
    name=m.name.replace('\\','/')
    if name.startswith('mdl/'): name=name[4:]
    lines+=['$modelname '+qc_quote(name), '$cdmaterials ""', '$origin 0 0 0 -90']
    if m.get('i',0x9C)&16: lines+=['$staticprop']
    for b in m.bones:
        parent=m.bones[b['parent']]['name'] if b['parent']>=0 else ''
        rotation=b['rot']
        values=(*b['pos'],*(rotation[i]*180/math.pi for i in (1,2,0)),0,0,0,0,0,0)
        lines+=['$definebone '+qc_quote(b['name'])+' '+qc_quote(parent)+' '+' '.join(format(v,'.9g') for v in values)]
        if any(v!=1 for v in b['scale']): lines[-1]+=' scale '+' '.join(format(v,'.9g') for v in b['scale'])
    lods=m.render() if m.meshes else [[]]
    vertex_ids={}
    for mi,mesh in enumerate(m.meshes):
        mat=m.materials[mesh['material']]['name']
        for li,lod in enumerate(lods):
            faces=[]
            for tri in lod[mi]['triangles']:
                corners=[]
                for i in (0,2,1):
                    v=tri[i]
                    key=(mi,tuple(v['pos']),tuple(v['normal']),tuple(v['uv']),tuple(v['weights']))
                    ident=vertex_ids.setdefault(key,len(vertex_ids))
                    extra=dict(uv=v['uv'],id=ident)
                    if 'uv2' in v: extra['uv2']=v['uv2']
                    if 'color' in v: extra['color']=[x/255 for x in v['color']]
                    corners.append((v['pos'],v['normal'],v['weights'],extra))
                faces.append((mat,mi,corners))
            write_dmx(out/f'mesh{mi}_lod{li}.dmx',m.bones,skeleton,faces,model_space=True)
        lines+=['$body '+qc_quote(f'body{mi}')+' '+qc_quote(f'mesh{mi}_lod0.dmx')]
    for li in range(1,len(lods)):
        # Switch points are read from the native vertex header.
        if PROFILES[target][1]=='vg1':
            from mdl54 import Reader
            vg=Reader(m.path.with_suffix('.vg').read_bytes()); lo=vg.get('Q',0x70)
            distance=vg.get('f',lo+li*8+4)
        else:
            from mdl54 import common
            vtx=common.parse_vtx(m.path.with_suffix('.dx11.vtx').read_bytes(),0)
            distance=vtx['bodyparts'][0]['models'][0]['lods'][li]['switchPoint']
        lines+=['$lod '+format(distance,'.9g')+' {']
        lines+=['  replacemodel '+qc_quote(f'mesh{mi}_lod0.dmx')+' '+qc_quote(f'mesh{mi}_lod{li}.dmx') for mi in range(len(m.meshes))]
        lines+=['}']
    for a in m.attachments:
        lines+=['$attachment '+qc_quote(a['name'])+' '+qc_quote(m.bones[a['bone']]['name'])+' 0 0 0 matrix '+' '.join(format(x,'.9g') for x in a['matrix'])]
    if not render_only:
        for si,seq in enumerate(m.sequences):
            p=seq['offset']
            if len(seq['animations'])!=1 or m.get('i',p+0x18) or m.get('i',p+0x94) or m.get('i',p+0xA4):
                raise ValueError('blends/events/layers/IK locks need a richer native export')
            desc=seq['animations'][0]; frames=m.animation(desc)
            filename=f'anim{si}.smd'; write_smd(out/filename,m.bones,frames)
            options=' fps '+format(m.get('f',desc+8),'.9g')
            if seq['flags']&1: options+=' loop'
            if seq['flags']&4: options+=' delta'
            lines+=['$sequence '+qc_quote(seq['name'])+' '+qc_quote(filename)+options]
    else:
        write_smd(out/'bind.smd',m.bones,[skeleton])
        lines+=['$sequence idle "bind.smd"']
    if not m.sequences and not render_only:
        write_smd(out/'bind.smd',m.bones,[skeleton]); lines+=['$sequence idle "bind.smd"']
    qc=out/'model.qc'; qc.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return qc


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('model'); p.add_argument('outdir')
    p.add_argument('--target',choices=PROFILES,required=True); p.add_argument('--render-only',action='store_true')
    a=p.parse_args(); print(decompile(a.model,a.outdir,a.target,render_only=a.render_only))
