"""Independent bounds-checked early Apex v54 reader (S0/S1 components, S2/S3 VG1)."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import argparse
import json
import math
import struct
import mdl53 as common

PROFILES = {'s0': (8, 'components'), 's1': (8, 'components'),
            's2': (9, 'vg1'), 's3': (10, 'vg1')}
ROT_STEP = 0.00019175345
SCALE_STEP = 0.0030518509


class Reader:
    def __init__(self, data):
        self.data = data

    def span(self, offset, size):
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise ValueError(f'binary span outside file: {offset:#x}+{size:#x}/{len(self.data):#x}')
        return offset

    def get(self, fmt, offset):
        fmt = '<' + fmt
        self.span(offset, struct.calcsize(fmt))
        vals = struct.unpack_from(fmt, self.data, offset)
        return vals[0] if len(vals) == 1 else vals

    def string(self, offset):
        self.span(offset, 1)
        end = self.data.find(b'\0', offset)
        if end < 0:
            raise ValueError('unterminated string')
        return self.data[offset:end].decode('utf-8', errors='replace')

    def array(self, count, offset, stride):
        if count < 0 or count > 1000000:
            raise ValueError('unreasonable array count')
        self.span(offset, count * stride)
        return range(offset, offset + count * stride, stride)


def unpack_normal(packed):
    axis = (packed >> 29) & 3
    if axis == 3:
        raise ValueError('invalid normal major axis')
    v = [0., 0., 0.]
    v[axis] = -255. if packed & (1 << 28) else 255.
    v[(axis+1) % 3] = ((packed >> 19) & 511) - 256.
    v[(axis+2) % 3] = ((packed >> 10) & 511) - 256.
    length = math.sqrt(sum(x*x for x in v))
    return tuple(x/length for x in v)


class Model(Reader):
    def __init__(self, path, target):
        if target not in PROFILES:
            raise ValueError('choose an explicit s0/s1/s2/s3 target')
        self.path = Path(path)
        self.target = target
        super().__init__(self.path.read_bytes())
        self.span(0, 0x224)
        if self.get('4s', 0) != b'IDST' or self.get('i', 4) != 54:
            raise ValueError('expected native IDST v54')
        if self.get('i', 0x50) != len(self.data):
            raise ValueError('model length does not match file size')
        self.name = self.string(self.get('i', 12))
        self.bones = []
        for p in self.array(self.get('i', 0xA0), self.get('i', 0xA4), 0xB8):
            parent = self.get('i', p+4)
            if parent < -1 or parent >= len(self.bones):
                raise ValueError('invalid or unsorted bone hierarchy')
            self.bones.append(dict(name=self.string(p+self.get('i', p)), parent=parent,
                                   pos=self.get('3f', p+0x20), quat=self.get('4f', p+0x2C),
                                   rot=self.get('3f', p+0x3C), scale=self.get('3f', p+0x48),
                                   pose_to_bone=self.get('12f', p+0x54),
                                   flags=self.get('i',p+0x94), proctype=self.get('i',p+0x98)))
        self.materials = []
        for p in self.array(self.get('i',0xD0),self.get('i',0xD4),12):
            self.materials.append(dict(name=self.string(p+self.get('i',p)),guid=self.get('Q',p+4)))
        self.bodyparts = []
        self.meshes = []
        for p in self.array(self.get('i',0xEC),self.get('i',0xF0),16):
            bp = dict(name=self.string(p+self.get('i',p)),models=[])
            for q in self.array(self.get('i',p+4),p+self.get('i',p+12),0x88):
                model=dict(name=self.data[q:q+64].split(b'\0')[0].decode('latin1'),
                           vertex_start=self.get('i',q+0x58)//48, meshes=[])
                for r in self.array(self.get('i',q+0x4C),q+self.get('i',q+0x50),0x5C):
                    mat=self.get('i',r)
                    if mat < 0 or mat >= len(self.materials):
                        raise ValueError('mesh material out of range')
                    mesh=dict(material=mat,count=self.get('i',r+8),vertex_offset=self.get('i',r+12),
                              id=self.get('i',r+32),lod_counts=self.get('8i',r+52),
                              vertex_start=model['vertex_start'])
                    model['meshes'].append(mesh); self.meshes.append(mesh)
                bp['models'].append(model)
            self.bodyparts.append(bp)
        self.attachments=[]
        for p in self.array(self.get('i',0xF4),self.get('i',0xF8),60):
            self.attachments.append(dict(name=self.string(p+self.get('i',p)),bone=self.get('i',p+8),
                                         flags=self.get('i',p+4),matrix=self.get('12f',p+12)))
        self.sequences=[]
        for p in self.array(self.get('i',0xC0),self.get('i',0xC4),0xD0):
            indices=[p+self.get('i',q) for q in self.array(self.get('i',p+0x38),p+self.get('i',p+0x3C),4)]
            self.sequences.append(dict(name=self.string(p+self.get('i',p+4)),flags=self.get('i',p+12),
                                       animations=indices,offset=p,reference_clip=self._reference_clip(p,indices)))

    def _reference_clip(self, p, indices):
        """A reference descriptor's clip: with no counted blends, a 1x1 sequence still holds
        one sequence-relative entry at its animation index, pointing at the descriptor that
        follows it (every S0-S3 ref/ragdoll descriptor; the client reads it through the
        grid). None when absent."""
        if indices or self.get('i',p) or self.get('2i',p+0x44)!=(1,1): return None
        entry=p+self.get('i',p+0x3C)
        if not 0<entry<=len(self.data)-4: return None
        desc=p+self.get('i',entry)
        if desc!=entry+4 or desc+0x34>len(self.data): return None
        return desc

    def reference_frames(self, seq):
        """Decoded poses of a reference clip; a clip without usable tracks (flag 0x20000
        clear) holds the bind pose."""
        desc=seq['reference_clip']
        if self.get('i',desc+12)&0x20000: return self.animation(desc)
        frames=self.get('i',desc+16)
        if not 0<frames<=1000000: raise ValueError('invalid frame count')
        return [[(tuple(b['pos']),tuple(b['rot']),tuple(b['scale'])) for b in self.bones] for _ in range(frames)]

    def frame_movement(self, descriptor):
        """Decode early-profile int32 section tables and bound every scalar packet."""
        self.span(descriptor,0x34)
        offset=self.get('i',descriptor+0x1C)
        if bool(offset)!=bool(self.get('i',descriptor+12)&0x40000):
            raise ValueError('frame-movement flag/pointer mismatch')
        if not offset: return None
        frames=self.get('i',descriptor+16)
        if not 1<=frames<=1000000 or offset<0: raise ValueError('invalid frame-movement descriptor')
        p=descriptor+offset; scales=self.get('4f',p); sf=self.get('i',p+16)
        if not 1<=sf<=1000000: raise ValueError('invalid frame-movement section size')
        if not all(math.isfinite(x) and x>=0 for x in scales): raise ValueError('invalid frame-movement scales')
        sections=(frames-1)//sf+1; header=20+4*sections; self.span(p,header); end=p+header
        samples=[]
        for s in range(sections):
            off=self.get('i',p+20+4*s)
            if off<header: raise ValueError('invalid frame-movement section offset')
            section=p+off; channels=self.get('4H',section); end=max(end,section+8)
            count=min(sf,frames-s*sf); values=[]
            for c,off in enumerate(channels):
                if not off: values.append([0.]*count); continue
                if off<8: raise ValueError('invalid frame-movement channel offset')
                q=section+off; covered=0
                while covered<count:
                    mode,total,words=self._packet(q)
                    covered+=total; end=max(end,q+words*2); q+=words*2
                channel=[self._f32(self._track(section+off,f)*scales[c]) for f in range(count)]
                if not all(math.isfinite(x) for x in channel): raise ValueError('non-finite frame movement')
                values.append(channel)
            samples.extend(zip(*values))
        return dict(scales=scales,section_frames=sf,samples=samples,payload=self.data[p:end])

    @staticmethod
    def _f32(value):
        try: return struct.unpack('<f',struct.pack('<f',value))[0]
        except OverflowError: raise ValueError('native scalar overflow') from None

    def _packet(self,p):
        mode,total=self.get('2B',p)
        if mode>19 or not total: raise ValueError('invalid native scalar packet')
        extra=(mode-2)%6 if mode>=2 else 0
        bits=0 if mode<8 else (2 if mode<14 else 4)
        words=1+total if mode==0 else 2+total//2 if mode==1 else 2+extra+(bits*total+15)//16
        self.span(p,words*2)
        return mode,total,words

    def unk_cc(self, seq):
        """The seqdesc 0xC8 (offset) / 0xCC (count) table: 24-byte records of a float, a
        bone index (-1 for none) and four floats (meaning unknown)."""
        p=seq['offset']; out=[]
        for q in self.array(self.get('i',p+0xCC),p+self.get('i',p+0xC8),24):
            value,bone,*ramp=self.get('fi4f',q)
            if not -1<=bone<len(self.bones): raise ValueError('unk_cc bone out of range')
            out.append(dict(value=value,bone=bone,ramp=tuple(ramp)))
        return out

    def autolayers(self, seq):
        """A sequence's v54 autolayers: 32 bytes each (asset GUID, int16 pose parameter,
        int16 always 0 in S3, int32 flags, start/peak/tail/end)."""
        p=seq['offset']; result=[]
        for q in self.array(self.get('i',p+0x94),p+self.get('i',p+0x98),32):
            guid=self.get('Q',q); pose,unused,flags=self.get('2hi',q+8)
            result.append(dict(guid=guid,pose=pose,unused=unused,flags=flags,ramp=self.get('4f',q+16)))
        return result

    def node_names(self):
        """Transition node names (v54 stores no transition table: index 0x100 is 0)."""
        count=self.get('i',0xFC); base=self.get('i',0x104)
        return [self.string(self.get('i',base+4*k)) for k in range(count)]

    def node_transitions(self):
        """A rig's transitions per node: (exit node, sequence index in the rig's list)
        pairs. Header 0x10C holds one absolute offset per node; each record is an int32
        count and int16 pairs (all 62 S3 rigs with nodes)."""
        count=self.get('i',0xFC); table=self.get('i',0x10C)
        if not count or not table or self.get('i',0x100): return []
        result=[]
        for k in range(count):
            r=self.get('i',table+4*k); n=self.get('i',r)
            result.append([self.get('2h',r+4+4*j) for j in range(n)])
        return result

    def ik_rules(self, descriptor):
        """An animation's IK rules (0x88 bytes each: v53's mstudioikrule_t with 0x1C bytes
        inserted at +0x3C, whose meaning is unknown, and the trailing unused block dropped).
        The rule-relative error index is reported as its distance past the rule array."""
        self.span(descriptor,0x34)
        count=self.get('i',descriptor+0x24); base=descriptor+self.get('i',descriptor+0x28)
        result=[]
        for k,p in enumerate(self.array(count,base,0x88)):
            index,kind,chain,bone,slot=self.get('5i',p)
            values=self.get('3f3f4f',p+0x14)
            error,start_frame,unknown_60=self.get('3i',p+0x58)
            timing=self.get('8f',p+0x64)
            attachment=self.get('i',p+0x80)
            result.append(dict(index=index,type=kind,chain=chain,bone=bone,slot=slot,
                               height=values[0],radius=values[1],floor=values[2],pos=tuple(values[3:6]),q=tuple(values[6:10]),
                               unknown_3c=self.data[p+0x3C:p+0x58].hex(),
                               error_past_rules=error-(count-k)*0x88 if error else None,i_start=start_frame,unknown_60=unknown_60,
                               start=timing[0],peak=timing[1],tail=timing[2],end=timing[3],contact=timing[4],drop=timing[5],top=timing[6],
                               attachment=self.string(p+attachment) if attachment else '',end_height=timing[7]))
        return result

    def movements(self, descriptor):
        """Native piecewise root-motion records; separate from frame-movement streams."""
        self.span(descriptor,0x34); frames=self.get('i',descriptor+16)
        result=[]; last=-1
        for p in self.array(self.get('i',descriptor+0x14),descriptor+self.get('i',descriptor+0x18),44):
            end,flags,*values=self.get('2i9f',p)
            if end<=last or end<0 or end>=frames: raise ValueError('invalid movement end frame')
            if not all(math.isfinite(x) for x in values): raise ValueError('non-finite movement record')
            result.append(dict(end_frame=end,flags=flags,v0=values[0],v1=values[1],angle=values[2],
                               vector=tuple(values[3:6]),position=tuple(values[6:9])))
            last=end
        return result

    def ik_chains(self):
        chains=[]
        for p in self.array(self.get('i',0x124),self.get('i',0x128),20):
            links=[]; unknown=self.get('f',p+16)
            if not math.isfinite(unknown): raise ValueError('non-finite IK chain value')
            for q in self.array(self.get('i',p+8),p+self.get('i',p+12),16):
                bone=self.get('i',q); knee=self.get('3f',q+4)
                if not 0<=bone<len(self.bones): raise ValueError('IK link bone outside skeleton')
                if not all(math.isfinite(x) for x in knee): raise ValueError('non-finite IK knee direction')
                links.append(dict(bone=bone,knee=knee))
            chains.append(dict(name=self.string(p+self.get('i',p)),type=self.get('i',p+4),unknown=unknown,links=links))
        return chains

    def _many(self,fmt,offset,count):
        # get() returns a bare value for one item
        if not count: return []
        v=self.get(fmt,offset); return list(v) if isinstance(v,tuple) else [v]

    JIGGLE_FIELDS = ['length', 'tipMass', 'tipFriction', 'yawStiffness', 'yawDamping', 'pitchStiffness', 'pitchDamping', 'alongStiffness', 'alongDamping', 'angleLimit', 'minYaw', 'maxYaw', 'yawFriction', 'yawBounce', 'minPitch', 'maxPitch', 'pitchFriction', 'pitchBounce', 'baseMass', 'baseStiffness', 'baseDamping', 'baseMinLeft', 'baseMaxLeft', 'baseLeftFriction', 'baseMinUp', 'baseMaxUp', 'baseUpFriction', 'baseMinForward', 'baseMaxForward', 'baseForwardFriction']

    def jiggle_bones(self):
        """v54 jiggle bones in procedural order (studiohdr 0x198 count, 0x19C byte table of
        bone indices). Each 0x7C record (at bone+0x9C): u8 flags, u8 bone byte, i16 pad,
        then v53's mstudiojigglebone_t floats with tipFriction after tipMass."""
        out=[]
        count,table=self.get('i',0x198),self.get('i',0x19C)
        for s in range(count):
            bone=self.data[table+s]
            if bone>=len(self.bones): raise ValueError('procedural bone table outside skeleton')
            p=self.get('i',0xA4)+0xB8*bone
            if self.get('i',p+0x98)!=5: raise ValueError('procedural table lists a non-jiggle bone')
            r=p+self.get('i',p+0x9C)
            flags,byte,pad=self.get('2Bh',r)
            out.append(dict(bone=bone,flags=flags,bone_byte=byte,pad=pad,
                            **dict(zip(self.JIGGLE_FIELDS,self.get('30f',r+4))),raw=self.data[r:r+0x7C]))
        return out

    def skins(self):
        """Skin families (studiohdr 0xE0 slots, 0xE4 families, 0xE8 table): each family
        lists a texture index per slot; families after the first have a name (int32 string
        offsets after the table)."""
        slots,count,index=self.get('3i',0xE0)
        if not 0<=slots<=4096 or not 0<=count<=4096: raise ValueError('unreasonable skin table')
        families=[[self.get('h',index+2*(slots*f+j)) for j in range(slots)] for f in range(count)]
        end=index+2*slots*count; end=(end+3)&~3
        names=[self.string(self.get('i',end+4*k)) for k in range(count-1)] if count>1 else []
        if any(not 0<=t<len(self.materials) for f in families for t in f): raise ValueError('skin texture out of range')
        return dict(families=families,names=names)

    @staticmethod
    def ui_face_mask(bounds):
        """A v54 RUI face's mask: bit 4*row+column for each cell of a 4x4 grid over the
        panel's unit square whose interior the convex hull of the face's four bounds points
        overlaps (separating axes: the grid axes and the hull's edge normals)."""
        pts=sorted(set(zip(bounds[:4],bounds[4:])))
        hull=pts
        if len(pts)>2:
            cross=lambda o,a,b:(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
            lower=[];upper=[]
            for p in pts:
                while len(lower)>=2 and cross(lower[-2],lower[-1],p)<=0: lower.pop()
                lower.append(p)
            for p in reversed(pts):
                while len(upper)>=2 and cross(upper[-2],upper[-1],p)<=0: upper.pop()
                upper.append(p)
            hull=lower[:-1]+upper[:-1]
        axes=[(1,0),(0,1)]+[(-(hull[(i+1)%len(hull)][1]-hull[i][1]),hull[(i+1)%len(hull)][0]-hull[i][0])
                            for i in range(len(hull))]
        mask=0
        for row in range(4):
            for col in range(4):
                box=[(col/4,row/4),((col+1)/4,row/4),(col/4,(row+1)/4),((col+1)/4,(row+1)/4)]
                for ax in axes:
                    if ax==(0,0): continue
                    p=[ax[0]*q[0]+ax[1]*q[1] for q in hull]; c=[ax[0]*q[0]+ax[1]*q[1] for q in box]
                    if max(p)<=min(c) or max(c)<=min(p): break
                else: mask|=1<<(4*row+col)
        return mask

    def ui_panels(self):
        """RUI panel meshes (studiohdr 0x12C count, 0x130 offset). v54 mesh: uint16 parent,
        vertex, face and mask counts; int32 parent, vertex, mask, face and bounds offsets
        (relative to the mesh); the name at +28. Faces from mask_count on are drawn with
        reversed winding (TF2's ccw faces)."""
        out=[]
        count,offset=self.get('i',0x12C),self.get('i',0x130)
        for i in range(count):
            ho=offset+8*i; hsh,rel=self.get('I',ho),self.get('i',ho+4); o=ho+rel
            pc,vc,fc,mc=self.get('4H',o); po,vo,xo,io,bo=self.get('5i',o+8)
            out.append(dict(hash=hsh,name=self.string(o+28),
                            parents=self._many('%dh'%pc,o+po,pc),
                            vertices=[self.get('i3f',o+vo+16*k) for k in range(vc)],
                            faces=[self.get('3h',o+io+6*k) for k in range(fc)],
                            masks=self._many('%dH'%fc,o+xo,fc),mask_count=mc,
                            bounds=[self.get('8f',o+bo+32*k) for k in range(fc)]))
        return out

    def pose_parameters(self):
        result=[]
        for p in self.array(self.get('i',0x134),self.get('i',0x138),20):
            values=self.get('3f',p+8)
            if not all(math.isfinite(x) for x in values): raise ValueError('non-finite pose parameter')
            result.append(dict(name=self.string(p+self.get('i',p)),flags=self.get('i',p+4),
                               start=values[0],end=values[1],loop=values[2]))
        return result

    def sequence_metadata(self, seq):
        """Decode studio metadata independently of QC/export support."""
        p=seq['offset']; dimensions=self.get('2i',p+0x44)
        # Installed common models include a 1x1 "ref" descriptor with no embedded
        # blends, both with and without STUDIO_SINGLEFRAME. It is not a clip.
        reference_pose=not seq['animations'] and dimensions==(1,1)
        if min(dimensions)<1 or (dimensions[0]*dimensions[1]!=len(seq['animations']) and not reference_pose):
            raise ValueError('invalid sequence blend grid')
        params=self.get('2i',p+0x4C); poses=self.pose_parameters()
        if any(i < -1 or i >= len(poses) for i in params): raise ValueError('invalid sequence pose index')
        events=[]
        for q in self.array(self.get('i',p+0x18),p+self.get('i',p+0x1C),0x110):
            options=self.data[q+12:q+0x10C]
            if b'\0' not in options: raise ValueError('unterminated event options')
            cycle=self.get('f',q); kind=self.get('i',q+8)
            # The native compiler's frame-zero event in a one-frame clip is NaN.
            single=all(self.get('i',a+16)==1 for a in seq['animations'])
            if not (math.isfinite(cycle) and 0<=cycle<=1) and not (single and math.isnan(cycle)):
                raise ValueError('invalid event cycle')
            events.append(dict(cycle=None if math.isnan(cycle) else cycle,event=self.get('i',q+4),type=kind,
                               name=self.string(q+self.get('i',q+0x10C)) if kind else '',
                               options=options.split(b'\0')[0].decode('utf-8',errors='strict')))
        keycount=sum(dimensions) if self.get('i',p+0xA0) else 0
        keys=[self.get('f',q) for q in self.array(keycount,p+self.get('i',p+0xA0),4)]
        weights=[self.get('f',q) for q in self.array(len(self.bones),p+self.get('i',p+0x9C),4)]
        modifiers=[]
        for q in self.array(self.get('i',p+0xBC),p+self.get('i',p+0xB8),8):
            modifiers.append(dict(name=self.string(q+self.get('i',q)),negate=bool(self.get('B',q+4))))
        result=dict(name=seq['name'],flags=seq['flags'],activity=self.string(p+self.get('i',p+8)),
                    activity_weight=self.get('i',p+0x14),grid=dimensions,params=params,
                    start=self.get('2f',p+0x54),end=self.get('2f',p+0x5C),
                    fade=self.get('2f',p+0x68),bounds=self.get('6f',p+0x20),
                    posekeys=keys,weights=weights,events=events,modifiers=modifiers,
                    cycle_pose=self.get('i',p+0xB4),ik_reset=self.get('i',p+0xC0),unknown_c4=self.get('i',p+0xC4))
        numbers=(*keys,*weights,*result['start'],*result['end'],*result['fade'],*result['bounds'])
        if not all(math.isfinite(x) for x in numbers): raise ValueError('non-finite sequence metadata')
        return result

    def render(self):
        if PROFILES[self.target][1] == 'vg1':
            return self._vg()
        return self._components()

    def _components(self):
        complex_weights=bool(self.get('i',0x9C)&0x4000)
        d=Reader(self.path.with_suffix('.vvd').read_bytes())
        if d.get('4s',0)!=b'IDSV' or d.get('i',4)!=4:
            raise ValueError('expected VVD4')
        if d.get('i',8)!=self.get('i',8):
            raise ValueError('VVD checksum mismatch')
        count=d.get('i',16); start=d.get('i',56)
        d.span(start,count*48)
        extra_weights=None
        if complex_weights:
            extra_weights=Reader(self.path.with_suffix('.vvw').read_bytes())
            if extra_weights.get('i',0)!=self.get('i',8) or extra_weights.get('i',4)!=1:
                raise ValueError('VVW checksum/version mismatch')
            extra_start=extra_weights.get('i',40)
            if extra_start<44: raise ValueError('VVW data overlaps header')
            extra_weights.span(extra_start,0)
        colors=None
        if self.get('i',0x1D8):
            colors=Reader(self.path.with_suffix('.vvc').read_bytes())
            if colors.get('4s',0)!=b'IDCV' or colors.get('i',8)!=self.get('i',8):
                raise ValueError('VVC magic/checksum mismatch')
        verts=[]
        for p in d.array(count,start,48):
            weights=d.get('3f',p); bones=d.get('3B',p+12); n=d.get('B',p+15)
            if not 1<=n<=16: raise ValueError('VVD influence count outside 1..16')
            if complex_weights:
                quantized=d.get('3h',p)
                influences=list(zip(bones[:min(n,3)],((q+1)/32768 for q in quantized[:min(n,3)])))
                base=d.get('i',p+8)
                if base<0: raise ValueError('negative VVD extra-weight index')
                for j in range(max(0,n-3)):
                    q,bone=extra_weights.get('2h',extra_start+(base+j)*4)
                    influences.append((bone,(q+1)/32768))
            else:
                if n>3: raise ValueError('VVD has extra influences without a VVW layout flag')
                influences=list(zip(bones[:n],weights[:n]))
            self._check_weights(influences)
            vertex=dict(pos=d.get('3f',p+16),normal=d.get('3f',p+28),uv=d.get('2f',p+40),
                        weights=influences)
            if colors:
                index=(p-start)//48
                if self.get('i',0x9C)&0x1000000:
                    vertex['color']=colors.get('4B',colors.get('i',48)+index*4)
                if self.get('i',0x9C)&0x2000000:
                    vertex['uv2']=colors.get('2f',colors.get('i',52)+index*8)
            verts.append(vertex)
        vd=self.path.with_suffix('.dx11.vtx').read_bytes()
        if Reader(vd).get('i',16)!=self.get('i',8):
            raise ValueError('VTX checksum mismatch')
        # VTX hierarchy is unchanged from r2; use the independent shared decoder.
        vtx=common.parse_vtx(vd,0)
        lods=[]
        for lod in range(vtx['hdr']['numLODs']):
            meshes=[]
            for bi,bp in enumerate(self.bodyparts):
                for mi,model in enumerate(bp['models']):
                    vm=vtx['bodyparts'][bi]['models'][mi]['lods'][lod]
                    for mesh,stripmesh in zip(model['meshes'],vm['meshes']):
                        faces=[]
                        for group in stripmesh['stripgroups']:
                            gr=Reader(vd); g=group['_off']
                            gr.span(g+group['indexOffset'],group['numIndices']*2)
                            gr.span(g+group['vertOffset'],group['numVerts']*9)
                            raw_indices=gr.get(str(group['numIndices'])+'H',g+group['indexOffset']) if group['numIndices'] else ()
                            for strip in group['strips']:
                                ids=raw_indices[strip['indexOffset']:strip['indexOffset']+strip['numIndices']]
                                if not strip['flags']&1:
                                    raise ValueError('triangle strips not implemented')
                                for k in range(0,len(ids),3):
                                    tri=[]
                                    for i in ids[k:k+3]:
                                        if i>=group['numVerts']: raise ValueError('VTX index outside strip group')
                                        original=gr.get('H',g+group['vertOffset']+i*9+4)
                                        index=model['vertex_start']+mesh['vertex_offset']+original
                                        if not 0<=index<len(verts): raise ValueError('VTX vertex outside VVD')
                                        tri.append(verts[index])
                                    faces.append(tri)
                        meshes.append(dict(material=mesh['material'],triangles=faces))
            lods.append(meshes)
        return lods

    def _vg(self):
        complex_weights=bool(self.get('i',0x9C)&0x4000)
        d=Reader(self.path.with_suffix('.vg').read_bytes())
        if d.get('I',0)!=0x47567430 or d.get('i',4)!=1:
            raise ValueError('expected VG revision 1')
        if d.get('i',12)>len(d.data): raise ValueError('VG length outside file')
        mo,mc=d.get('2Q',0x20); io,ic=d.get('2Q',0x30); vo,vs=d.get('2Q',0x40)
        lo,lc=d.get('2Q',0x70); bo,bc=d.get('2Q',0x10)
        eo,es=d.get('2Q',0x50)
        d.span(mo,mc*72); d.span(io,ic*2); d.span(vo,vs); d.span(lo,lc*8)
        d.span(eo,es); d.span(bo,bc)
        lods=[]
        for lp in d.array(lc,lo,8):
            first,count=d.get('2H',lp); meshes=[]
            for native in self.meshes:
                mid=first+native['id']
                if mid>=first+count or mid>=mc: raise ValueError('VG mesh outside LOD')
                p=mo+mid*72
                flags=d.get('Q',p); off,stride,n=d.get('3I',p+8)
                mesh_extra,mesh_extra_size=d.get('2i',p+24)
                if mesh_extra<0 or mesh_extra_size<0 or mesh_extra+mesh_extra_size>es:
                    raise ValueError('VG mesh extra-weight span outside buffer')
                if not flags:
                    meshes.append(dict(material=native['material'],triangles=[])); continue
                vertices=[]
                for q in d.array(n,vo+off,stride):
                    cursor=q
                    if flags&3==1: pos=d.get('3f',cursor); cursor+=12
                    elif flags&3==2:
                        packed=d.get('Q',cursor); cursor+=8
                        pos=(((packed&0x1FFFFF)/1024)-1024,
                             (((packed>>21)&0x1FFFFF)/1024)-1024,
                             (((packed>>42)&0x3FFFFF)/1024)-2048)
                    else: raise ValueError('unsupported VG position representation')
                    weights=[(0,1.)]
                    if flags&0x5000:
                        a=d.get('h',cursor); b=d.get('H',cursor+2)
                        bones=d.get('3B',cursor+4); extra=d.get('B',cursor+7); cursor+=8
                        if extra>15: raise ValueError('VG influence count exceeds 16')
                        if not complex_weights and extra>2: raise ValueError('VG has extra influences without layout flag')
                        weights=[]
                        if extra:
                            weights.append((bones[0],(a+1)/32768))
                            if complex_weights:
                                needed=max(0,extra-1)
                                if needed and (b+needed)*4>mesh_extra_size:
                                    raise ValueError('VG extra-weight index outside mesh span')
                                for index in range(needed):
                                    packed,bone=d.get('2h',eo+mesh_extra+(b+index)*4)
                                    weights.append((bone,(packed+1)/32768))
                                last=bones[1]
                            else:
                                if extra==2: weights.append((bones[1],(b+1)/32768))
                                last=bones[extra]
                            weights.append((last,1-sum(w for _,w in weights)))
                        else: weights=[(bones[0],1.)]
                        if bc:
                            if any(i<0 or i>=bc for i,_ in weights): raise ValueError('VG bone-map index outside table')
                            weights=[(d.get('B',bo+i),w) for i,w in weights]
                    self._check_weights(weights)
                    normal=unpack_normal(d.get('I',cursor)); cursor+=4
                    color=d.get('4B',cursor) if flags&16 else (255,255,255,255)
                    if flags&16: cursor+=4
                    uv=d.get('2f',cursor) if flags&(15<<24) else (0.,0.)
                    if flags&(15<<24): cursor+=8
                    uv2=d.get('2f',cursor) if flags&(15<<32) else (0.,0.)
                    vertex=dict(pos=pos,normal=normal,uv=uv,weights=weights)
                    if flags&16: vertex['color']=color
                    if flags&(15<<32): vertex['uv2']=uv2
                    vertices.append(vertex)
                start,num=d.get('2i',p+32)
                d.span(io+start*2,num*2)
                ids=d.get(str(num)+'H',io+start*2) if num else ()
                if num%3 or any(i>=n for i in ids): raise ValueError('invalid VG triangle indices')
                faces=[[vertices[i] for i in ids[k:k+3]] for k in range(0,num,3)]
                meshes.append(dict(material=native['material'],triangles=faces))
            lods.append(meshes)
        return lods

    def _check_weights(self,weights):
        if not 1<=len(weights)<=16: raise ValueError('invalid influence count')
        if any(b<0 or b>=len(self.bones) or not math.isfinite(w) or w<0 for b,w in weights):
            raise ValueError('invalid bone index or weight')
        if abs(sum(w for _,w in weights)-1)>1e-5: raise ValueError('unnormalized skin weights')

    def animation(self, descriptor):
        p=descriptor; self.span(p,52)
        frames=self.get('i',p+16); flags=self.get('i',p+12)
        if not flags&0x20000:
            # no tracks: the base pose (zeros for a delta clip; all-zeros clips set 0x20)
            if frames<=0 or frames>1000000: raise ValueError('invalid frame count')
            base=[((0.,0.,0.),(0.,0.,0.),(0.,0.,0.)) if flags&4 else (tuple(b['pos']),tuple(b['rot']),tuple(b['scale'])) for b in self.bones]
            return [list(base) for _ in range(frames)]
        table,sf=self.get('2i',p+44)
        if frames<=0 or frames>1000000: raise ValueError('invalid frame count')
        output=[]
        for frame in range(frames):
            local=frame
            if sf:
                section=frame//sf
                if frames>sf and frame==frames-1: section=(frames-1)//sf+1; local=0
                else: local=frame%sf
                data=p+self.get('i',p+table+section*4)
            else: data=p+self.get('i',p+32)
            size=((len(self.bones)+1)//2+1)&~1
            self.span(data,size); record=data+size; pose=[]
            for j,bone in enumerate(self.bones):
                mask=(self.get('B',data+j//2)>>(4*(j%2)))&15
                delta=bool(flags&4)
                pos=[0.,0.,0.] if delta else list(bone['pos'])
                rot=[0.,0.,0.] if delta else list(bone['rot'])
                scale=[0.,0.,0.] if delta else list(bone['scale'])
                if mask&7:
                    header=self.get('H',record); length=header&8191; modes=header>>13
                    if length<2: raise ValueError('zero-sized animation record')
                    self.span(record,length); cur=record+2
                    for bit,mode,values,step in ((1,4,pos,None),(2,2,rot,ROT_STEP),(4,1,scale,SCALE_STEP)):
                        if not mask&bit: continue
                        if modes&mode:
                            if bit==1: step=self.get('f',cur); cur+=4
                            ptr=cur; cur+=4
                            field=self.get('H',ptr); axes=field>>13; start=ptr+(field&8191)
                            # each axis has its own word-offset slot (x at 0, y +2, z +3),
                            # also when an earlier axis is absent: drone_EMP's def_c_base
                            # stores y at slot 0 and z at slot 25 with x absent
                            offsets=(0,self.get('B',ptr+2),self.get('B',ptr+3))
                            for axis in range(3):
                                if axes&(4>>axis):
                                    value=self._track(start+offsets[axis]*2,local)*step
                                    values[axis]=value if bit==2 else values[axis]+value
                        elif bit==2:
                            from decompile53 import unpack_q64, matrix_angles, quat_matrix
                            values[:]=matrix_angles(quat_matrix(unpack_q64(self.get('Q',cur)))); cur+=8
                        else:
                            values[:]=self.get('3e',cur); cur+=6
                    record+=length
                pose.append((tuple(pos),tuple(rot),tuple(scale)))
            output.append(pose)
        return output

    def native_sections(self, descriptor):
        """The clip's native sections as stored: (frames per section or 0, [bytes]). Each
        section's length is its bone mask plus its bone records, padded to 4 bytes."""
        p=descriptor; self.span(p,52)
        frames=self.get('i',p+16); table,sf=self.get('2i',p+44)
        starts=[p+self.get('i',p+table+4*k) for k in range((frames-1)//sf+2)] if sf else [p+self.get('i',p+32)]
        size=((len(self.bones)+1)//2+1)&~1; sections=[]
        for data in starts:
            self.span(data,size); end=data+size
            for j in range(len(self.bones)):
                if (self.data[data+j//2]>>(4*(j%2)))&7:
                    length=self.get('H',end)&8191
                    if length<2: raise ValueError('zero-sized animation record')
                    end+=length
            self.span(data,end-data)
            sections.append(self.data[data:end]+b'\0'*(-(end-data)%4))
        return sf,sections

    def _track(self,p,frame):
        # General native mode-0 raw, mode-1 byte deltas and polynomial modes.
        while True:
            mode,total,words=self._packet(p)
            extra=(mode-2)%6 if mode>=2 else 0
            bits=0 if mode<8 else (2 if mode<14 else 4)
            words=(1+total if mode==0 else 2+(total//2) if mode==1 else 2+extra+(bits*total+15)//16)
            if frame<total: break
            frame-=total; p+=words*2
        if mode==0: return self.get('h',p+2+frame*2)
        base=self.get('h',p+2)
        if mode==1:
            value=base+(self.get('b',p+4+frame-1) if frame else 0)
            if not -32768<=value<=32767: raise ValueError('native byte-delta overflow')
            return value
        t=self._f32(frame/(total-1)) if total>1 else 0.
        value=float(base); power=t
        for i in range(extra):
            value=self._f32(value+self._f32(self.get('h',p+4+i*2)*power))
            power=self._f32(power*t)
        if bits:
            packed=self.get('H',p+4+extra*2+(frame*bits//16)*2)
            value=self._f32(value+2*((packed>>(frame*bits%16))&((1<<bits)-1))-((1<<bits)-1))
        return value


class SequenceAsset(Model):
    """Standalone native sequence data interpreted with its owning rig."""
    def __init__(self,path,rig):
        self.path=Path(path); self.target=rig.target; self.rig=rig
        Reader.__init__(self,self.path.read_bytes()); self.span(0,0xD0)
        if self.get('i',0): raise ValueError('unsupported standalone sequence base selector')
        self.bones=rig.bones; self.meshes=[]; self.materials=[]
        indices=[self.get('i',p) for p in self.array(self.get('i',0x38),self.get('i',0x3C),4)]
        for p in indices: self.span(p,0x34)
        self.sequences=[dict(name=self.string(self.get('i',4)),flags=self.get('i',12),animations=indices,offset=0,
                             reference_clip=self._reference_clip(0,indices))]
        self.name=self.sequences[0]['name']
        self.sequence_metadata(self.sequences[0])
        for p in indices:
            self.frame_movement(p); self.movements(p)
            # a clip without tracks (flag 0x20000 clear: a bind-pose reference clip) has no data
            if self.get('i',p+12)&0x20000: self.animation(p)
        if self.sequences[0]['reference_clip'] is not None:
            self.reference_frames(self.sequences[0])

    def pose_parameters(self): return self.rig.pose_parameters()
    def ik_chains(self): return self.rig.ik_chains()
    def node_names(self): return self.rig.node_names()


def asset_guid(path):
    """RTech asset GUID of an asset path: letters fold to upper case and backslashes to
    '/', four bytes at a time (resolves 208 of the 292 S3 autolayer GUIDs to extracted
    sequences; the others name assets that were not extracted)."""
    M64=(1<<64)-1; M32=(1<<32)-1
    data=path.encode()+bytes(8)
    def word(p):
        nonlocal data
        if p+4>len(data): data+=bytes(4)
        return int.from_bytes(data[p:p+4],'little')
    def fold(w):
        x=w^0x5C5C5C5C
        backslash=((~x&M32)>>7)&(((x-0x01010101)&M32)>>7)&0x01010101
        return ((w-45*backslash)&M32)&0xDFDFDFDF
    pos=length=h=0
    w=word(0); folded=fold(w); zero=(~w&M32)&((w-0x01010101)&M32)&0x80808080
    while not zero:
        h=((((0xFB8C4D96501*folded)&M64)>>24)+0x633D5F1*h)&M64
        h=(h>>61)^h
        pos+=4; length+=4
        w=word(pos); folded=fold(w); zero=(~w&M32)&((w-0x01010101)&M32)&0x80808080
    below=((zero&-zero)-1)&M32
    top=below.bit_length()-1 if below else -1
    tail=((0xFB8C4D96501*(folded&below))&M64)>>24
    return (0x633D5F1*h+tail-0xAE502812AA7333*((length+int(top/8))&M32))&M64


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model'); parser.add_argument('--target',choices=PROFILES,required=True)
    args=parser.parse_args(); model=Model(args.model,args.target)
    render=model.render() if model.meshes else []
    print(json.dumps(dict(name=model.name,bones=len(model.bones),materials=len(model.materials),
                          sequences=len(model.sequences),lods=len(render),
                          triangles=[sum(len(m['triangles']) for m in lod) for lod in render]),indent=2))

if __name__=='__main__': main()
