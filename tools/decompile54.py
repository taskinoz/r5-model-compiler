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
                         ('IK autoplay locks',0x148),('transition nodes',0xFC)]:
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
    if not render_only:
        for pose in m.pose_parameters():
            if pose['flags'] & ~1: raise ValueError('unsupported pose parameter flags')
            option=' loop '+format(pose['loop'],'.9g') if pose['flags']&1 else ''
            lines+=['$poseparameter '+qc_quote(pose['name'])+' '+format(pose['start'],'.9g')+' '+format(pose['end'],'.9g')+option]
    for b in m.bones:
        parent=m.bones[b['parent']]['name'] if b['parent']>=0 else ''
        rotation=b['rot']
        values=(*b['pos'],*(rotation[i]*180/math.pi for i in (1,2,0)),0,0,0,0,0,0)
        lines+=['$definebone '+qc_quote(b['name'])+' '+qc_quote(parent)+' '+' '.join(format(v,'.9g') for v in values)]
        if any(v!=1 for v in b['scale']): lines[-1]+=' scale '+' '.join(format(v,'.9g') for v in b['scale'])
    if not render_only:
        for chain in m.ik_chains():
            links=chain['links']
            if chain['type']!=0 or len(links)!=3 or any(any(x!=0 for x in link['knee']) for link in links[1:]):
                raise ValueError('unsupported IK chain type/link layout')
            names=[qc_quote(m.bones[link['bone']]['name']) for link in links]
            lines+=['$ikchain '+qc_quote(chain['name'])+' '+names[-1]+' links '+' '.join(names)+
                    ' knee '+' '.join(format(x,'.9g') for x in links[0]['knee'])+
                    ' angle_unknown '+format(chain['unknown'],'.9g')]
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
            # These fields have no supported source representation in this exporter.
            if any(m.get('i',p+off) for off in (0x40,0x64,0x70,0x74,0x78,0x88,0x8C,0x90,0x94,0xA4,0xB0,0xCC)) or any(m.get('f',p+off) for off in (0x7C,0x80,0x84)):
                raise ValueError('sequence nodes/layers/IK/keyvalues need a richer native export')
            meta=m.sequence_metadata(seq)
            if not seq['animations']: raise ValueError('reference-pose sequence without an embedded animation is not yet exportable')
            if seq['flags'] & ~0xA47BF: raise ValueError('unsupported sequence flags')
            names=[]
            for ai,desc in enumerate(seq['animations']):
                if m.get('i',desc+0x24):
                    raise ValueError('animation frame-movement/IK needs a richer native export')
                flags=m.get('i',desc+12)
                if flags & ~0x68017: raise ValueError('unsupported animation flags')
                frames=m.animation(desc); filename=f'anim{si}_{ai}.smd'
                write_smd(out/filename,m.bones,frames)
                name=f'r5c_anim_{si}_{ai}'; names.append(name)
                options=' fps '+format(m.get('f',desc+8),'.9g')+' noautoik'
                for bit,word in ((1,'loop'),(2,'snap'),(4,'delta'),(0x10,'post'),(0x8000,'noforceloop')):
                    if flags&bit: options+=' '+word
                movement=m.frame_movement(desc)
                if movement:
                    import struct
                    stream=f'anim{si}_{ai}.fm54'
                    (out/stream).write_bytes(b'FM54'+struct.pack('<I',len(frames))+movement['payload'])
                    options+=' fmstream '+qc_quote(stream)
                # Decoded samples already contain the loop boundary.
                if flags&1 and not flags&0x8000: options+=' noforceloop'
                for move in m.movements(desc):
                    values=(move['v0'],move['v1'],move['angle'],*move['vector'],*move['position'])
                    options+=' movementrecord '+str(move['end_frame'])+' '+str(move['flags'])+' '+' '.join(format(x,'.9g') for x in values)
                lines+=['$animation '+qc_quote(name)+' '+qc_quote(filename)+options]
            weightname=f'r5c_weights_{si}'
            lines+=['$weightlist '+qc_quote(weightname)+' {']
            lines+=['  '+qc_quote(b['name'])+' '+format(w,'.9g') for b,w in zip(m.bones,meta['weights'])]
            lines+=['}', '$sequence '+qc_quote(seq['name'])+' {','  '+' '.join(qc_quote(n) for n in names),
                    '  seqflags '+str(seq['flags']&~0xA0000),'  seqweights '+qc_quote(weightname),
                    '  blendwidth '+str(meta['grid'][0]),
                    '  fadein '+format(meta['fade'][0],'.9g')+' fadeout '+format(meta['fade'][1],'.9g'),
                    '  bbox '+' '.join(format(x,'.9g') for x in meta['bounds']),
                    '  ikresetmask '+str(meta['ik_reset'])+' unk_c4 '+str(meta['unknown_c4'])]
            if meta['activity']: lines+=['  activity '+qc_quote(meta['activity'])+' '+str(meta['activity_weight'])]
            poses=m.pose_parameters()
            for axis,index in enumerate(meta['params']):
                if index>=0:
                    lines+=['  blend '+qc_quote(poses[index]['name'])+' '+format(meta['start'][axis],'.9g')+' '+format(meta['end'][axis],'.9g')]
                elif axis==0 and meta['params'][1]>=0: raise ValueError('unsupported second-axis-only blend')
            if meta['posekeys']: lines+=['  posekeys '+str(len(meta['posekeys']))+' '+' '.join(format(x,'.9g') for x in meta['posekeys'])]
            if seq['flags']&0x80:
                index=meta['cycle_pose']
                if not 0<=index<len(poses): raise ValueError('invalid cycle pose index')
                lines+=['  posecycle '+qc_quote(poses[index]['name'])]
            for modifier in meta['modifiers']:
                lines+=['  activitymodifier '+qc_quote(modifier['name'])+(' negate' if modifier['negate'] else '')]
            for event in meta['events']:
                if event['type'] not in (0,1024): raise ValueError('unsupported event type')
                name=str(event['event']) if not event['type'] else event['name']
                if event['type'] and (not name or name[0].isdigit() or event['event']): raise ValueError('unsupported named event identity')
                timing='event '+qc_quote(name)+' 0' if event['cycle'] is None else 'eventcycle '+qc_quote(name)+' '+format(event['cycle'],'.9g')
                lines+=['  '+timing+' '+qc_quote(event['options'])]
            lines+=['}']
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
