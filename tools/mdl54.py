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
                                       animations=indices,offset=p))

    def render(self):
        if PROFILES[self.target][1] == 'vg1':
            return self._vg()
        return self._components()

    def _components(self):
        if self.get('i',0x9C)&0x4000:
            raise ValueError('complex VVD/VVW weights not implemented')
        d=Reader(self.path.with_suffix('.vvd').read_bytes())
        if d.get('4s',0)!=b'IDSV' or d.get('i',4)!=4:
            raise ValueError('expected VVD4')
        if d.get('i',8)!=self.get('i',8):
            raise ValueError('VVD checksum mismatch')
        count=d.get('i',16); start=d.get('i',56)
        d.span(start,count*48)
        colors=None
        if self.get('i',0x1D8):
            colors=Reader(self.path.with_suffix('.vvc').read_bytes())
            if colors.get('4s',0)!=b'IDCV' or colors.get('i',8)!=self.get('i',8):
                raise ValueError('VVC magic/checksum mismatch')
        verts=[]
        for p in d.array(count,start,48):
            weights=d.get('3f',p); bones=d.get('3B',p+12); n=d.get('B',p+15)
            vertex=dict(pos=d.get('3f',p+16),normal=d.get('3f',p+28),uv=d.get('2f',p+40),
                        weights=list(zip(bones[:n],weights[:n])))
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
        if self.get('i',0x9C)&0x4000:
            raise ValueError('complex VG weights not implemented')
        d=Reader(self.path.with_suffix('.vg').read_bytes())
        if d.get('I',0)!=0x47567430 or d.get('i',4)!=1:
            raise ValueError('expected VG revision 1')
        if d.get('i',12)>len(d.data): raise ValueError('VG length outside file')
        mo,mc=d.get('2Q',0x20); io,ic=d.get('2Q',0x30); vo,vs=d.get('2Q',0x40)
        lo,lc=d.get('2Q',0x70); bo,bc=d.get('2Q',0x10)
        d.span(mo,mc*72); d.span(io,ic*2); d.span(vo,vs); d.span(lo,lc*8)
        lods=[]
        for lp in d.array(lc,lo,8):
            first,count=d.get('2H',lp); meshes=[]
            for native in self.meshes:
                mid=first+native['id']
                if mid>=first+count or mid>=mc: raise ValueError('VG mesh outside LOD')
                p=mo+mid*72
                flags=d.get('Q',p); off,stride,n=d.get('3I',p+8)
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
                        a,b=d.get('2H',cursor); bones=d.get('3B',cursor+4); extra=d.get('B',cursor+7); cursor+=8
                        if extra>2: raise ValueError('complex VG weights not implemented')
                        values=(a,b,32767-a-b) if extra==2 else ((a,32767-a) if extra else (32767,))
                        weights=[(d.get('B',bo+i) if bc else i,w/32767) for i,w in zip(bones,values)]
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

    def animation(self, descriptor):
        p=descriptor; self.span(p,52)
        frames=self.get('i',p+16); flags=self.get('i',p+12)
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
                            offsets=(0,self.get('B',ptr+2),self.get('B',ptr+3))
                            active=0
                            for axis in range(3):
                                if axes&(4>>axis):
                                    value=self._track(start+offsets[active]*2,local)*step; active+=1
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

    def _track(self,p,frame):
        # General native mode-0 raw, mode-1 byte deltas and polynomial modes.
        while True:
            mode,total=self.get('2B',p)
            if not total: raise ValueError('zero-length animation track')
            extra=(mode-2)%6 if mode>=2 else 0
            bits=0 if mode<8 else (2 if mode<14 else 4)
            words=(1+total if mode==0 else 2+(total//2) if mode==1 else 2+extra+(bits*total+15)//16)
            if frame<total: break
            frame-=total; p+=words*2
        if mode==0: return self.get('h',p+2+frame*2)
        base=self.get('h',p+2)
        if mode==1: return base+(self.get('b',p+4+frame-1) if frame else 0)
        t=frame/(total-1) if total>1 else 0.
        value=base+sum(self.get('h',p+4+i*2)*t**(i+1) for i in range(extra))
        if bits:
            packed=self.get('H',p+4+extra*2+(frame*bits//16)*2)
            value+=2*((packed>>(frame*bits%16))&((1<<bits)-1))-((1<<bits)-1)
        return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model'); parser.add_argument('--target',choices=PROFILES,required=True)
    args=parser.parse_args(); model=Model(args.model,args.target)
    render=model.render() if model.meshes else []
    print(json.dumps(dict(name=model.name,bones=len(model.bones),materials=len(model.materials),
                          sequences=len(model.sequences),lods=len(render),
                          triangles=[sum(len(m['triangles']) for m in lod) for lod in render]),indent=2))

if __name__=='__main__': main()
