"""Export the supported early-Apex model subset to QC + SMD (no game assets included)."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import argparse
import math
from mdl54 import Model, SequenceAsset, PROFILES
from decompile53 import write_dmx, matrix_angles, qc_quote


def literal_quote(name, kind='asset name'):
    # QC asset paths use literal backslashes; only event options decode escapes.
    if any(c in name for c in ('"','\n','\r','\0')):
        raise ValueError(kind+' cannot be represented as a QC string')
    return '"'+name+'"'


# studio flags the compiler derives: generated hitboxes, static prop, complex weights,
# the single-bone/collision bit, vertex colour and UV2
DERIVED_FLAGS=0x1|0x10|0x4000|0x800000|0x1000000|0x2000000
MATERIAL_TYPES=('rgdu','rgdp','rgdc','sknu','sknp','sknc','wldu','wldc','ptcu','ptcs')


def material_quote(name):
    return literal_quote(name,'material name')


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


def _invert34(m):
    """Inverse of a row-major 3x4 affine matrix (rotation/scale + translation)."""
    a=[m[0:3],m[4:7],m[8:11]]; t=(m[3],m[7],m[11])
    det=(a[0][0]*(a[1][1]*a[2][2]-a[1][2]*a[2][1])-a[0][1]*(a[1][0]*a[2][2]-a[1][2]*a[2][0])
         +a[0][2]*(a[1][0]*a[2][1]-a[1][1]*a[2][0]))
    inv=[[(a[(c+1)%3][(r+1)%3]*a[(c+2)%3][(r+2)%3]-a[(c+1)%3][(r+2)%3]*a[(c+2)%3][(r+1)%3])/det for c in range(3)] for r in range(3)]
    return [row+[-sum(row[k]*t[k] for k in range(3))] for row in inv]


def _apply34(m,p):
    return tuple(sum(m[r][c]*p[c] for c in range(3))+m[r][3] for r in range(3))


def _rotate34(m,n):
    v=[sum(m[r][c]*n[c] for c in range(3)) for r in range(3)]
    length=math.sqrt(sum(x*x for x in v)) or 1
    return tuple(x/length for x in v)


def _hull_radius(hull):
    """The compiler's inscribed radius: the nearest Newell face plane (through the face's
    farthest vertex) from the stored centroid."""
    c=hull['centroid']; best=None
    for loop in hull['faces']:
        pts=[hull['verts'][i] for i in loop]; n=[0.,0.,0.]
        for k in range(len(pts)):
            p,q=pts[k],pts[(k+1)%len(pts)]
            n[0]+=(p[1]-q[1])*(p[2]+q[2]); n[1]+=(p[2]-q[2])*(p[0]+q[0]); n[2]+=(p[0]-q[0])*(p[1]+q[1])
        length=math.sqrt(sum(x*x for x in n))
        if not length: continue
        n=[x/length for x in n]
        d=max(sum(a*b for a,b in zip(n,p)) for p in pts)-sum(a*b for a,b in zip(n,c))
        best=d if best is None else min(best,d)
    return max(best or 0.,0.)


def export_physics(m, out, target):
    """$collisionmodel / $collisionjoints for the model's native PHY: each hull becomes
    one piece of DMX polygons (its stored faces), so the compiler rebuilds the same
    hulls; per-solid keyvalues become explicit joint options."""
    import re
    import phy54
    from decompile53 import write_dmx
    parsed=phy54.parse(m.path.with_suffix('.phy').read_bytes(),target)
    text=parsed['text']
    props=[dict(re.findall(r'"([^"]+)"\s+"([^"]*)"',blk)) for blk in re.findall(r'\bsolid\s*\{([^}]*)\}',text)]
    if len(props)!=len(parsed['solids']): raise ValueError('PHY solid metadata count differs from solid count')
    names=[p.get('name','') for p in props]
    by_name={b['name'].lower():i for i,b in enumerate(m.bones)}
    jointed=len(parsed['solids'])>1 or 'parent' in text or 'ragdollconstraint' in text
    for si,s in enumerate(parsed['solids']):
        for hull in s['hulls']:
            problems=phy54.check_hull(hull,target=='s3')
            if problems: raise ValueError('PHY solid %d has an invalid hull: %s'%(si,', '.join(problems)))
    # solid space -> model space: jointed solids follow their bone; rigid solids are in model space
    bone_to_model=[_invert34(list(b['pose_to_bone'])) for b in m.bones]
    identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0]]
    faces=[]; piece=0
    for si,s in enumerate(parsed['solids']):
        bone=by_name.get(names[si].lower(),0) if jointed else 0
        if jointed and names[si].lower() not in by_name: raise ValueError('PHY solid %r has no bone'%names[si])
        xf=bone_to_model[bone] if jointed else identity
        for hull in s['hulls']:
            # a distinct normal per piece keeps flush or overlapping pieces apart
            n=len(s['hulls']); k=s['hulls'].index(hull)
            z=1-2*(k+.5)/n; r=math.sqrt(max(0.,1-z*z)); angle=k*math.pi*(3-math.sqrt(5))
            normal=_rotate34(xf,(r*math.cos(angle),r*math.sin(angle),z))
            placed=[_apply34(xf,v) for v in hull['verts']]
            for loop in hull['faces']:
                faces.append(('phys',piece,[(placed[v],normal,[(bone,1.0)],{}) for v in loop]))
            piece+=1
    order=None
    if jointed:
        wanted=[by_name[n.lower()] for n in names]+list(range(len(m.bones)))
        order=[]
        for i in wanted:  # parents first, solids in retail order
            chain=[]
            while i!=-1 and i not in order and i not in chain:
                chain.append(i); i=m.bones[i]['parent']
            order+=reversed(chain)
    skeleton=[(b['pos'],b['rot'],b['scale']) for b in m.bones]
    write_dmx(out/'physics.dmx',m.bones,skeleton,faces,joint_order=order,model_space=True)
    total=re.search(r'"totalmass"\s+"([^"]+)"',text)
    lines=[('$collisionjoints' if jointed else '$collisionmodel')+' "physics.dmx"','{']
    if total: lines.append('\t$mass '+total.group(1))
    root=re.search(r'"rootname"\s+"([^"]*)"',text)
    if root and root.group(1): lines.append('\t$rootbone '+qc_quote(root.group(1)))
    if not jointed: lines.append('\t$collisionname '+qc_quote(names[0]))
    for parent,child in re.findall(r'"jointmerge"\s+"([^",]+),([^"]+)"',text):
        lines.append('\t$jointmerge %s %s'%(qc_quote(parent),qc_quote(child)))
    lines.append('\t$explicitjointconstraints')
    for name,p in zip(names,props):
        for field,command in (('mass','jointmass'),('damping','jointdamping'),('rotdamping','jointrotdamping'),
                              ('inertia','jointinertia'),('massbias','jointmassbias'),('drag','jointdrag')):
            if field in p: lines.append('\t$%s %s %s'%(command,qc_quote(name),p[field]))
        lines.append('\t$jointsurfaceprop %s %s'%(qc_quote(name),qc_quote(p.get('surfaceprop','default'))))
        if jointed: lines.append('\t$jointparent %s %s'%(qc_quote(name),qc_quote(p.get('parent',''))))
    # retail keeps "concave" in editparams when the source was compiled with $concave,
    # even when that produced a single hull
    concave='"concave" "1"' in text
    if concave or (not jointed and len(parsed['solids'][0]['hulls'])>1): lines.append('\t$concave')
    if jointed and any(len(s['hulls'])>1 for s in parsed['solids']): lines.append('\t$concaveperjoint')
    for blk in re.findall(r'ragdollconstraint\s*\{([^}]*)\}',text):
        kv=dict(re.findall(r'"([^"]+)"\s+"([^"]*)"',blk))
        child=names[int(kv['child'])]
        for ax in 'xyz':
            lines.append('\t$jointconstrain %s %s limit %s %s %s'%(qc_quote(child),ax,kv[ax+'min'],kv[ax+'max'],kv[ax+'friction']))
    for a,b in re.findall(r'"collisionpair"\s+"(\d+),(\d+)"',text):
        lines.append('\t$jointcollide %s %s'%(qc_quote(names[int(a)]),qc_quote(names[int(b)])))
    if re.search(r'"selfcollisions"\s+"0"',text): lines.append('\t$noselfcollisions')
    # stored vertices no face uses, kept in their hull (solid space)
    for si,s in enumerate(parsed['solids']):
        for hi,hull in enumerate(s['hulls']):
            used={v for loop in hull['faces'] for v in loop}
            for k,v in enumerate(hull['verts']):
                if k not in used: lines.append('\t$hullpoint %d %d %s'%(si,hi,' '.join(format(x,'.9g') for x in v)))
    # a stored inscribed radius the compiler's rule (nearest Newell face plane from the
    # centroid) does not give: six S3 hulls with bent faces; kept verbatim
    for si,s in enumerate(parsed['solids']):
        for hi,hull in enumerate(s['hulls']):
            if abs(_hull_radius(hull)-hull['radius'])>1e-5*max(hull['radius'],1e-6):
                lines.append('\t$hullradius %d %d %s'%(si,hi,format(hull['radius'],'.9g')))
    af=re.search(r'animatedfriction\s*\{([^}]*)\}',text)
    if af:
        kv=dict(re.findall(r'"([^"]+)"\s+"([^"]*)"',af[1]))
        lines.append('\t$animatedfriction '+' '.join(kv[k] for k in
            ('animfrictionmin','animfrictionmax','animfrictiontimein','animfrictiontimehold','animfrictiontimeout')))
    lines.append('}')
    breaks=re.findall(r'\bbreak\s*\{([^}]*)\}',text)
    if breaks: lines+=['$collisiontext','{']+[x for b in breaks for x in ('break','{',b.strip(),'}')]+['}']
    return lines


def export_keyvalues(m):
    """The model keyvalues (studiohdr 0x140) as a $keyvalues block. Retail text is compact,
    `mdlkeyvalue{prop_data{base "X"}}`; the compiler writes the same form back."""
    import re
    index,size=m.get('i',0x140),m.get('i',0x144)
    if not size: return []
    text=m.data[index:index+size].split(b'\0')[0].decode('utf-8')
    tokens=re.findall(r'"[^"]*"|[{}]|[^\s{}"]+',text)
    if tokens[:2]!=['mdlkeyvalue','{'] or tokens[-1]!='}': raise ValueError('unexpected model keyvalue text')
    lines=['$keyvalues','{']; depth=1; i=2
    while i<len(tokens)-1:
        t=tokens[i]
        if t=='}': depth-=1; lines.append('  '*depth+'}'); i+=1; continue
        key=t.strip('"')
        if i+1<len(tokens) and tokens[i+1]=='{':
            lines+=['  '*depth+key,'  '*depth+'{']; depth+=1; i+=2
        else:
            lines.append('  '*depth+qc_quote(key)+' '+qc_quote(tokens[i+1].strip('"'))); i+=2
    if depth!=1: raise ValueError('unbalanced model keyvalue text')
    return lines+['}']


def export_jiggle_bones(m):
    """$jigglebone blocks in procedural order (the order sets the record slots). Every
    stored value is written so that the record is rebuilt byte for byte: floats with 9
    significant digits, angles in degrees with 17 (the compiler converts them in double
    precision), the v54 tip_friction, an empty is_rigid section when retail sets both the
    rigid and flexible bits, and the stored bone byte where it is not the bone's own index.
    Limits stored without their flag use the stored_* options."""
    g=lambda v: format(v,'.9g')
    deg=lambda v: format(math.degrees(v),'.17g')
    lines=[]
    for j in m.jiggle_bones():
        f=j['flags']
        if j['pad']: raise ValueError('jiggle record padding is not zero')
        if f&~0x7F: raise ValueError('unknown jiggle flags 0x%x'%f)
        body=['$jigglebone '+qc_quote(m.bones[j['bone']]['name']),'{']
        if f&0x03==0x03: body+=['\tis_rigid','\t{','\t}']
        if f&0x03:
            body+=['\t'+('is_flexible' if f&0x01 else 'is_rigid'),'\t{']
            body+=['\t\t%s %s'%(k,g(j[n])) for k,n in (('length','length'),('tip_mass','tipMass'),('tip_friction','tipFriction'),
                   ('yaw_stiffness','yawStiffness'),('yaw_damping','yawDamping'),('pitch_stiffness','pitchStiffness'),
                   ('pitch_damping','pitchDamping'),('along_stiffness','alongStiffness'),('along_damping','alongDamping'))]
            if f&0x20: body.append('\t\tallow_length_flex')
            if f&0x10: body.append('\t\tangle_constraint '+deg(j['angleLimit']))
            elif j['angleLimit']: body.append('\t\tstored_angle_limit '+deg(j['angleLimit']))
            if f&0x04: body.append('\t\tyaw_constraint %s %s'%(deg(j['minYaw']),deg(j['maxYaw'])))
            elif j['minYaw'] or j['maxYaw']: body.append('\t\tstored_yaw_limits %s %s'%(deg(j['minYaw']),deg(j['maxYaw'])))
            body+=['\t\tyaw_friction '+g(j['yawFriction']),'\t\tyaw_bounce '+g(j['yawBounce'])]
            if f&0x08: body.append('\t\tpitch_constraint %s %s'%(deg(j['minPitch']),deg(j['maxPitch'])))
            elif j['minPitch'] or j['maxPitch']: body.append('\t\tstored_pitch_limits %s %s'%(deg(j['minPitch']),deg(j['maxPitch'])))
            body+=['\t\tpitch_friction '+g(j['pitchFriction']),'\t\tpitch_bounce '+g(j['pitchBounce']),'\t}']
        else:
            raise ValueError('jiggle bone without a flexible or rigid section')
        # base values are stored (and reproduced) even without a base spring section
        body+=['\thas_base_spring' if f&0x40 else '\tbase_values','\t{']
        body+=['\t\t%s %s'%(k,' '.join(g(j[n]) for n in ns)) for k,ns in (
               ('stiffness',['baseStiffness']),('damping',['baseDamping']),('base_mass',['baseMass']),
               ('left_constraint',['baseMinLeft','baseMaxLeft']),('left_friction',['baseLeftFriction']),
               ('up_constraint',['baseMinUp','baseMaxUp']),('up_friction',['baseUpFriction']),
               ('forward_constraint',['baseMinForward','baseMaxForward']),('forward_friction',['baseForwardFriction']))]
        body.append('\t}')
        if j['bone_byte']!=j['bone']: body.append('\tbone_byte %d'%j['bone_byte'])
        lines+=body+['}']
    return lines


def export_ui_panels(m):
    """RUI panel meshes as $uipanel blocks: parents, vertices, faces, per-face bounds.
    v54 stores TF2's ccw faces last, after mask_count other faces: those faces get `ccw`,
    so the compiler derives the count. Per-face masks follow from the bounds; they are
    written (all of them) only if one differs from the derived mask."""
    from decompile53 import ui_panel_hash
    fmt=lambda v: format(v,'.9g')
    lines=[]
    for p in m.ui_panels():
        hsh='' if p['hash']==ui_panel_hash(p['name']) else ' 0x%08x'%p['hash']
        lines+=['$uipanel '+qc_quote(p['name'])+hsh,'{']
        lines+=['\tparent '+qc_quote(m.bones[b]['name']) for b in p['parents']]
        lines+=['\tvertex %d %s %s %s'%(v[0],fmt(v[1]),fmt(v[2]),fmt(v[3])) for v in p['vertices']]
        lines+=['\tface %d %d %d%s'%(*f,' ccw' if k>=p['mask_count'] else '') for k,f in enumerate(p['faces'])]
        lines+=['\tbounds '+' '.join(fmt(x) for x in b) for b in p['bounds']]
        if any(x!=Model.ui_face_mask(b) for x,b in zip(p['masks'],p['bounds'])):
            lines+=['\tfacemask 0x%04x'%x for x in p['masks']]
        lines+=['}']
    return lines


def export_hitboxes(m):
    """Hitbox sets (studiohdr 0xB0/0xB4; 0x2C-byte boxes: bone, group, min, max, name,
    crit override, hit data group). Models whose hitboxes were generated (header flag 1)
    get none, so the compiler generates them again."""
    if m.get('i',0x9C)&1: return []
    lines=[]
    count,index=m.get('i',0xB0),m.get('i',0xB4)
    for s in range(count):
        p=index+12*s
        name=m.string(p+m.get('i',p)); boxes=m.get('i',p+4); start=p+m.get('i',p+8)
        lines.append('$hboxset '+qc_quote(name))
        for k in range(boxes):
            q=start+0x2C*k
            bone,group=m.get('i',q),m.get('i',q+4)
            box=list(m.get('3f',q+8))+list(m.get('3f',q+0x14))
            off=m.get('i',q+0x20); label=m.string(q+off) if off else ''
            crit=m.get('i',q+0x24); off=m.get('i',q+0x28); hitdata=m.string(q+off) if off else ''
            if not 0<=bone<len(m.bones): raise ValueError('hitbox bone outside the skeleton')
            lines.append('$hbox '+str(group)+' '+qc_quote(m.bones[bone]['name'])+' '+' '.join(format(x,'.9g') for x in box)
                         +' '+qc_quote(label)+' '+str(crit)+(' '+qc_quote(hitdata) if hitdata else ''))
    return lines


def export_skeleton(m, *, metadata=True):
    """QC skeleton/pose/IK definitions shared by model and standalone-rig export."""
    lines=[]
    if metadata:
        # transition nodes in table order, including any no sequence uses
        lines+=['$node '+qc_quote(name) for name in m.node_names()]
        if m.get('i',0x108): lines+=['$localnodeunk '+str(m.get('i',0x108))]
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
    if metadata:
        for chain in m.ik_chains():
            links=chain['links']
            if chain['type']!=0 or len(links)!=3 or any(any(x!=0 for x in link['knee']) for link in links[1:]):
                raise ValueError('unsupported IK chain type/link layout')
            names=[qc_quote(m.bones[link['bone']]['name']) for link in links]
            lines+=['$ikchain '+qc_quote(chain['name'])+' '+names[-1]+' links '+' '.join(names)+
                    ' knee '+' '.join(format(x,'.9g') for x in links[0]['knee'])+
                    ' angle_unknown '+format(chain['unknown'],'.9g')]
    return lines


IK_RULE_SIZE=0x88


def fnv1a64(data, h=0xcbf29ce484222325):
    for b in data: h=((h^b)*0x100000001b3)&0xFFFFFFFFFFFFFFFF
    return h


def write_native_stream(path, m, desc, smd):
    """AN54: frames, frames per section, bone count, FNV-1a 64 of the bone names (joined
    by newlines) and of the SMD file, then each native section (u32 size, bytes)."""
    import struct
    sf,sections=m.native_sections(desc)
    names=chr(10).join(b['name'] for b in m.bones).encode()
    data=b'AN54'+struct.pack('<3I',m.get('i',desc+16),sf,len(m.bones))
    data+=struct.pack('<QQI',fnv1a64(names),fnv1a64(Path(smd).read_bytes()),len(sections))
    for section in sections: data+=struct.pack('<I',len(section))+section
    Path(path).write_bytes(data)




def release_rules(m, desc):
    """Chains of an animation's IK rules when every rule is a whole-range release, the
    only kind retail sequence assets store (studiomdl's automatic releases: index k,
    slot = chain, bone 0, range 0-0-1-1, an empty error stream past the rule array).
    v54 rules are 0x88 bytes: v53's fields with 0x1C bytes inserted at +0x3C."""
    import struct
    count=m.get('i',desc+0x24)
    if not count: return []
    base=desc+m.get('i',desc+0x28); chains=[]
    nchains=len(m.ik_chains())
    for k in range(count):
        q=base+k*IK_RULE_SIZE
        words=struct.unpack_from('<34I',m.data,q)
        index,kind,chain,bone,slot=struct.unpack_from('<5i',m.data,q)
        start,peak,tail,end=struct.unpack_from('<4f',m.data,q+0x64)
        expected=list(words); expected[0]=k; expected[1]=4; expected[2]=expected[4]=chain
        expected[0x58//4]=(count-k)*IK_RULE_SIZE
        expected[0x6C//4]=expected[0x70//4]=0x3F800000
        for i,w in enumerate(words):
            if i not in (0,1,2,4,0x58//4,0x6C//4,0x70//4): expected[i]=0
        if list(words)!=expected or not 0<=chain<nchains:
            raise ValueError('IK rules other than whole-range releases need a richer native export')
        chains.append(chain)
    return chains


def export_sequences(m, out, *, namespace="", asset_paths=()):
    """Export the supported sequence subset using its owning skeleton. Autolayers name
    their sequence asset by path when it is in asset_paths (or is this asset), else by
    GUID."""
    from mdl54 import asset_guid
    known={asset_guid(path):path for path in asset_paths}
    if isinstance(m,SequenceAsset): known.setdefault(asset_guid(m.name),m.name)
    lines=[]
    prefix=namespace+"_" if namespace else ""
    for si,seq in enumerate(m.sequences):
        p=seq['offset']
        # These fields have no supported source representation in this exporter.
        if any(m.get('i',p+off) for off in (0x40,0x64,0x88,0x8C,0xA4,0xB0)) or any(m.get('f',p+off) for off in (0x7C,0x80,0x84)):
            raise ValueError('sequence nodes/layers/IK/keyvalues need a richer native export')
        meta=m.sequence_metadata(seq)
        # a 1x1 descriptor without a clip holds the reference pose (retail ref, ragdoll)
        reference=not seq['animations']
        if seq['flags'] & ~0xE47FF: raise ValueError('unsupported sequence flags')
        # 0x40000 marks a standalone sequence whose clips have frame movement (retail
        # assets: exactly when all do); the compiler derives it
        if seq['flags'] & 0x40000 and not (seq['animations'] and all(m.get('i',d+12)&0x40000 for d in seq['animations'])):
            raise ValueError('sequence frame-movement flag without frame-movement clips')
        names=[]
        for ai,desc in enumerate(seq['animations']):
            rules=release_rules(m,desc)
            flags=m.get('i',desc+12)
            # 0x20 (all-zeros) is derived; 0x40 is kept with animflags
            if flags & ~0x68077: raise ValueError('unsupported animation flags')
            frames=m.animation(desc); filename=f'{prefix}anim{si}_{ai}.smd'
            write_smd(out/filename,m.bones,frames)
            name=f'{prefix}r5c_anim_{si}_{ai}'; names.append(name)
            # the clip's native sections as stored (its frame movement is laid out by them)
            options=' fps '+format(m.get('f',desc+8),'.9g')+' noautoik sectionframes '+str(m.get('i',desc+0x30))
            # retail's sections verbatim: its curve-mode tracks cannot be re-encoded exactly;
            # the compiler uses them while the SMD and skeleton are unchanged
            if flags&0x20000:  # a clip without tracks (all-zeros) has no sections
                stream=f'{prefix}anim{si}_{ai}.an54'
                write_native_stream(out/stream,m,desc,out/filename)
                options+=' animstream '+qc_quote(stream)
            for bit,word in ((1,'loop'),(2,'snap'),(4,'delta'),(0x10,'post'),(0x8000,'noforceloop')):
                if flags&bit: options+=' '+word
            if flags&0x40: options+=' animflags 0x40'
            movement=m.frame_movement(desc)
            if movement:
                import struct
                stream=f'{prefix}anim{si}_{ai}.fm54'
                (out/stream).write_bytes(b'FM54'+struct.pack('<I',len(frames))+movement['payload'])
                options+=' fmstream '+qc_quote(stream)
            # Decoded samples already contain the loop boundary.
            if flags&1 and not flags&0x8000: options+=' noforceloop'
            for move in m.movements(desc):
                values=(move['v0'],move['v1'],move['angle'],*move['vector'],*move['position'])
                options+=' movementrecord '+str(move['end_frame'])+' '+str(move['flags'])+' '+' '.join(format(x,'.9g') for x in values)
            chains=m.ik_chains()
            for chain in rules: options+=' ikrule '+qc_quote(chains[chain]['name'])+' release'
            lines+=['$animation '+qc_quote(name)+' '+qc_quote(filename)+options]
        # the sequence's rule count is its animations' largest (the compiler derives it)
        if m.get('i',p+0x90)!=max([m.get('i',d+0x24) for d in seq['animations']] or [0]):
            raise ValueError('sequence IK rule count differs from its animations')
        weightname=f'{prefix}r5c_weights_{si}'
        lines+=['$weightlist '+qc_quote(weightname)+' {']
        lines+=['  '+qc_quote(b['name'])+' '+format(w,'.9g') for b,w in zip(m.bones,meta['weights'])]
        pose=''
        if reference and seq['reference_clip'] is not None:
            # its clip ('@' + label, 30 fps): exported when it has tracks; without them
            # it is the bind pose, which the compiler writes the same way
            desc=seq['reference_clip']; flags=m.get('i',desc+12)
            if flags&~0x20000 or abs(m.get('f',desc+8)-30)>1e-6 or m.string(desc+m.get('i',desc+4))!='@'+seq['name']:
                raise ValueError('unsupported reference clip')
            if flags&0x20000:
                filename=f'{prefix}ref{si}.smd'
                write_smd(out/filename,m.bones,m.reference_frames(seq)); pose=' '+qc_quote(filename)
        lines+=['}', '$sequence '+literal_quote(seq['name'],'sequence name')+' {','  referencepose'+pose if reference else '  '+' '.join(qc_quote(n) for n in names),
                # a clip-less descriptor keeps its single-frame bit (retail has both); 0x20000
                # is stored data (not its clips' bit), so it is kept too
                '  seqflags '+str(seq['flags']&~(0 if reference else 0xC0000)),'  seqweights '+qc_quote(weightname),
                '  blendwidth '+str(meta['grid'][0]),
                '  fadein '+format(meta['fade'][0],'.9g')+' fadeout '+format(meta['fade'][1],'.9g'),
                '  bbox '+' '.join(format(x,'.9g') for x in meta['bounds']),
                '  ikresetmask '+str(meta['ik_reset'])+' unk_c4 '+str(meta['unknown_c4'])]
        entry,exit_,nodeflags=(m.get('i',p+off) for off in (0x70,0x74,0x78))
        if entry or exit_:
            names=m.node_names()
            if nodeflags&~1 or not (0<=entry<=len(names) and 0<=exit_<=len(names)): raise ValueError('invalid transition nodes')
            if entry==exit_ and not nodeflags: lines+=['  node '+qc_quote(names[entry-1])]
            elif entry and exit_: lines+=['  '+('rtransition' if nodeflags else 'transition')+' '+qc_quote(names[entry-1])+' '+qc_quote(names[exit_-1])]
            elif nodeflags: raise ValueError('reversible transition without both nodes')
            # one side only (3 S3 mantle sequences have just an exit node)
            elif entry: lines+=['  entrynode '+qc_quote(names[entry-1])]
            else: lines+=['  exitnode '+qc_quote(names[exit_-1])]
        elif nodeflags: raise ValueError('node flags without transition nodes')
        for layer in m.autolayers(seq):
            if layer['unused']: raise ValueError('autolayer with a nonzero second index')
            target=qc_quote(known[layer['guid']]) if layer['guid'] in known else '0x%016x'%layer['guid']
            text='  autolayer '+target
            poses=m.pose_parameters()
            if layer['pose'] or layer['flags']&0x4000:
                if not 0<=layer['pose']<len(poses): raise ValueError('autolayer pose parameter out of range')
                text+=' pose '+qc_quote(poses[layer['pose']]['name'])
            if layer['flags']: text+=' flags 0x%x'%layer['flags']
            if any(layer['ramp']): text+=' range '+' '.join(format(x,'.9g') for x in layer['ramp'])
            lines+=[text]
        for record in m.unk_cc(seq):
            bone=m.bones[record['bone']]['name'] if record['bone']>=0 else ''
            lines+=['  unk_cc '+qc_quote(bone)+' '+' '.join(format(x,'.9g') for x in (record['value'],*record['ramp']))]
        if meta['activity']: lines+=['  activity '+qc_quote(meta['activity'])+' '+str(meta['activity_weight'])]
        poses=m.pose_parameters()
        for axis,index in enumerate(meta['params']):
            if index>=0:
                # an axis-1 blend without an axis-0 one names its axis
                lines+=['  '+('blendaxis 1 ' if axis==1 and meta['params'][0]<0 else 'blend ')+qc_quote(poses[index]['name'])+' '+format(meta['start'][axis],'.9g')+' '+format(meta['end'][axis],'.9g')]
            else:
                # an axis without a pose parameter stores 0..1 in sequence assets and 0..0 in
                # models; keep any other stored range (11 S3 assets)
                default=(0.,1.) if isinstance(m,SequenceAsset) else (0.,0.)
                stored=(meta['start'][axis],meta['end'][axis])
                if stored!=default:
                    lines+=['  axisrange '+str(axis)+' '+' '.join(format(x,'.9g') for x in stored)]
        if not meta['posekeys'] and meta['grid'][0]*meta['grid'][1]>1: lines+=['  noposekeys']
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
    return lines


def decompile(path, outdir, target, *, render_only=False, with_physics=False):
    m=Model(path,target); out=Path(outdir); out.mkdir(parents=True,exist_ok=True)
    # Unsupported information is never silently claimed to roundtrip.
    unsupported=[]
    # The BVH is rebuilt by the compiler from the render mesh ($staticprop trace) and the
    # PHY solids, so it is not listed here; roundtrip54 compares it.
    for label,offset in [
                         ('followers',0x1E8),('include models',0x158),
                         ('IK autoplay locks',0x148)]:
        # include-model count -1 is not an include model: it is the external-rig linkage
        # (the loader builds the virtual rig from asset references), 386 of 581 S3 models
        if offset==0x158 and m.get('i',offset)==-1: continue
        if m.get('i',offset): unsupported.append(label)
    if any(b['proctype'] not in (0,5) for b in m.bones): unsupported.append('non-jiggle bone procedures')
    if unsupported and not render_only:
        raise ValueError('unsupported for native export: '+', '.join(unsupported)+'; use --render-only for an explicit geometry export')
    skeleton=[(b['pos'],b['rot'],b['scale']) for b in m.bones]
    lines=['// r5 --target '+target]
    if render_only and with_physics: lines+=['// Geometry and physics export: rigs and sequence metadata are not preserved.']
    elif render_only: lines+=['// Geometry export: physics, rigs and sequence metadata are not preserved.']
    name=m.name.replace('\\','/')
    if name.startswith('mdl/'): name=name[4:]
    lines+=['$modelname '+qc_quote(name), '$cdmaterials ""', '$origin 0 0 0 -90']
    # Mesh readers strip extensions and compare source names case/slash-insensitively.
    # Give each material slot its own source alias, then restore the exact asset name
    # after import; foo and foo.vmt must not collapse into the same material.
    prefix='r5c_material_'
    stored_names={mat['name'].lower() for mat in m.materials}
    while any((prefix+str(i)).lower() in stored_names for i in range(len(m.materials))):
        prefix+='alias_'
    material_aliases=[prefix+str(i) for i in range(len(m.materials))]
    lines+=['$renamematerial '+qc_quote(alias)+' '+material_quote(mat['name'])
            for alias,mat in zip(material_aliases,m.materials)]
    # the skin table as stored: the first family lists every texture slot in order (so it
    # also fixes the texture order), later families are named
    skins=m.skins()
    if skins['families']:
        lines+=['$skinfamilies','{']
        for f,row in enumerate(skins['families']):
            # QC strings are literal (no escapes outside event options): retail names
            # such as "purple\blue fade" are written as stored
            name=skins['names'][f-1] if f else ''
            if '"' in name: raise ValueError('skin family name contains a quote: %r'%name)
            label='' if not f else '"%s" '%name
            lines+=['  '+label+'{ '+' '.join(qc_quote(material_aliases[t]) for t in row)+' }']
        lines+=['}']
    # the stored hull box (it also sets the BVH box at 0x1F0); collision can widen a
    # computed one, so keep retail's exactly
    lines+=['$bbox '+' '.join(format(x,'.9g') for x in m.get('6f',0x6C))]
    if m.get('i',0x9C)&16: lines+=['$staticprop']
    # studio flags the compiler cannot derive (retail's material bits 0x2/0x4/0x8/0x80/
    # 0x800): kept verbatim; 0x4000 also selects the complex-weight vertex layout
    # the stored lighting origin (0x60; derived otherwise from sequence 0's box, which 451
    # S3 models do not follow); $illumposition is rotated like studiomdl's: stored = (-y, x, z)
    ix,iy,iz=m.get('3f',0x60)
    lines+=['$illumposition %s %s %s'%(format(iy,'.9g'),format(-ix,'.9g'),format(iz,'.9g'))]
    fade=m.get('f',0x16C)
    if fade!=-1: lines+=['$fadedistance '+format(fade,'.9g')]
    # header mass of a model without physics (the compiler's default is 1)
    if not m.get('i',0x1DC) and m.get('f',0x150)!=1: lines+=['$mass '+format(m.get('f',0x150),'.9g')]
    # the model's surface property (every bone shares it in all 581 S3 models)
    surface=m.string(m.get('i',0x13C))
    if surface.lower()!='default': lines+=['$surfaceprop '+qc_quote(surface)]
    # the game's surface-property ids stored as lookups (header 0x180, bone +0xAC)
    ids={}
    ids[m.string(m.get('i',0x13C))]=m.get('i',0x180)
    for k in range(len(m.bones)):
        p=m.get('i',0xA4)+0xB8*k
        ids.setdefault(m.string(p+m.get('i',p+0xA4)),m.get('i',p+0xAC))
    lines+=['$surfacepropid '+qc_quote(name)+' '+str(v) for name,v in ids.items() if v]
    # each bone's stored flags: retail usage bits and 0x20/0x100000 follow rules the
    # stored data does not give
    lines+=['$boneflags '+qc_quote(b['name'])+' 0x%x'%(b['flags']&0xffffffff) for b in m.bones]
    flags=m.get('i',0x9C)
    extra=flags&~DERIVED_FLAGS
    if extra: lines+=['$headerflags 0x%x'%extra]
    if flags&0x4000: lines+=['$complexweights']
    # include-model count -1: the model ships with an external rig and sequence assets
    # (386 of 581 S3 models; single-bone models and static props never, otherwise a
    # build choice the stored data does not predict)
    if m.get('i',0x158)==-1: lines+=['$externalassets']
    # each texture slot's material asset (so the model packages without bindings)
    lines+=['$materialguid '+material_quote(mat['name'])+' 0x%016x'%mat['guid'] for mat in m.materials if mat['guid']]
    # each texture slot's native shader family (studiohdr 0xCC, one byte per slot)
    types=m.get('i',0xCC)
    if types:
        lines+=['$materialtype '+material_quote(mat['name'])+' '+MATERIAL_TYPES[m.data[types+i]]
                for i,mat in enumerate(m.materials)]
    lines+=export_skeleton(m,metadata=not render_only)
    lods=m.render() if m.meshes else [[]]
    vertex_ids={}
    mesh_index={id(mesh):mi for mi,mesh in enumerate(m.meshes)}
    # Body parts keep their names and choices: one DMX per studio model and LOD (all of
    # its meshes), empty models as `blank`. A part with one studio model is a $body.
    model_files=[]
    for bi,bp in enumerate(m.bodyparts):
        options=[]
        for mdi,md in enumerate(bp['models']):
            if not md['meshes']: options.append('blank'); continue
            base=f'part{bi}_model{mdi}'
            for li,lod in enumerate(lods):
                faces=[]
                for mesh in md['meshes']:
                    mi=mesh_index[id(mesh)]; mat=material_aliases[mesh['material']]
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
                write_dmx(out/f'{base}_lod{li}.dmx',m.bones,skeleton,faces,model_space=True)
            options.append('studio '+qc_quote(f'{base}_lod0.dmx')); model_files.append(base)
        if len(options)==1 and options[0]!='blank':
            lines+=['$body '+qc_quote(bp['name'])+' '+options[0][7:]]
        else:
            lines+=['$bodygroup '+qc_quote(bp['name']),'{']+['  '+o for o in options]+['}']
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
        lines+=['  replacemodel '+qc_quote(f'{b}_lod0.dmx')+' '+qc_quote(f'{b}_lod{li}.dmx') for b in model_files]
        lines+=['}']
    lines+=export_keyvalues(m)+export_hitboxes(m)+export_ui_panels(m)+export_jiggle_bones(m)
    for a in m.attachments:
        lines+=['$attachment '+qc_quote(a['name'])+' '+qc_quote(m.bones[a['bone']]['name'])+' 0 0 0 matrix '+' '.join(format(x,'.9g') for x in a['matrix'])]
    # header 0x190 is derived from the __illumPosition attachment; a few retail models
    # store another (stale) value, kept verbatim
    derived=next((i+1 for i,a in enumerate(m.attachments) if a['name'].lower()=='__illumposition'),0)
    if m.get('i',0x190)!=derived: lines+=['$illumpositionattachment '+str(m.get('i',0x190))]
    if not render_only:
        lines+=export_sequences(m,out)
    else:
        write_smd(out/'bind.smd',m.bones,[skeleton])
        lines+=['$sequence idle "bind.smd"']
    if not m.sequences and not render_only:
        write_smd(out/'bind.smd',m.bones,[skeleton]); lines+=['$sequence idle "bind.smd"']
    if m.get('i',0x1DC) and (with_physics or not render_only): lines+=export_physics(m,out,target)
    qc=out/'model.qc'; qc.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return qc


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('model'); p.add_argument('outdir')
    p.add_argument('--target',choices=PROFILES,required=True); p.add_argument('--render-only',action='store_true')
    p.add_argument('--with-physics',action='store_true',help='with --render-only: also export the PHY collision')
    a=p.parse_args()
    if a.with_physics and not a.render_only: p.error('--with-physics extends --render-only')
    print(decompile(a.model,a.outdir,a.target,render_only=a.render_only,with_physics=a.with_physics))
