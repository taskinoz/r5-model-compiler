"""Native v54 authored-input regressions; historical TF2 tests are separate."""
from pathlib import Path
import math
import os
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from mdl54 import Model, Reader, PROFILES
from decompile53 import write_smd
from decompile54 import decompile


class Compiler54(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler=Path(os.environ.get('R5C_COMPILER',ROOT/'build/r5studiomdl.exe')).resolve()
        if not cls.compiler.exists(): raise unittest.SkipTest('build r5studiomdl first')

    def setUp(self):
        (ROOT/'test-output').mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'test-output'); self.addCleanup(self.tmp.cleanup)
        self.work=Path(self.tmp.name)
        self.bones=[dict(name='root',parent=-1),dict(name='arm',parent=0)]
        self.frames=[[( (0,0,0),(0,0,0),(1,1,1)),((0,0,2),(0,0,0),(1,1,1))]]
        self.tris=[('test/material',[(p,(0,0,1),uv,[(0,.25),(1,.75)]) for p,uv in
                   [((0,0,2),(0,0)),((2,0,2),(1,0)),((0,3,2),(0,1))]])]
        write_smd(self.work/'mesh.smd',self.bones,self.frames,self.tris)
        self.qc='$modelname "test/model.rmdl"\n$origin 0 0 0 -90\n$body body "mesh.smd"\n$sequence idle "mesh.smd"\n'

    def run_compiler(self,qc=None,target='s0',extra=(),name='out',ok=True):
        q=self.work/(name+'.qc'); q.write_text(self.qc if qc is None else qc)
        out=self.work/(name+'.rmdl')
        command=[str(self.compiler)]
        if target is not None: command+=['--target',target]
        run=subprocess.run(command+list(extra)+['-quiet','-o',str(out),str(q)],capture_output=True,text=True,timeout=40)
        if ok: self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        else: self.assertNotEqual(run.returncode,0); self.assertFalse(out.exists())
        return out,run

    def test_explicit_profiles_and_retail_rejection(self):
        for target in (None,'retail','s4','53'):
            with self.subTest(target=target):
                _,run=self.run_compiler(target=target,ok=False)
                self.assertIn('choose --target',run.stderr)
        run=subprocess.run([str(self.compiler),'--list-targets'],capture_output=True,text=True)
        self.assertEqual(run.returncode,0); self.assertIn('VG rev1',run.stdout)

    def test_native_headers_and_geometry_all_seasons(self):
        for target in PROFILES:
            with self.subTest(target=target):
                out,_=self.run_compiler(target=target,name=target)
                m=Model(out,target); render=m.render()
                self.assertEqual(m.name,'test/model.rmdl')
                self.assertEqual(len(m.data),m.get('i',0x50))
                self.assertEqual(m.get('i',4),54); self.assertEqual(len(m.bones),2)
                self.assertEqual(m.bones[1]['parent'],0)
                self.assertEqual(m.bones[1]['pos'],(0,0,2))
                self.assertEqual(len(render[0][0]['triangles']),1)
                points={tuple(v['pos']) for v in render[0][0]['triangles'][0]}
                self.assertEqual(points,{(0,0,2),(2,0,2),(0,3,2)})
                for v in render[0][0]['triangles'][0]:
                    self.assertLess(abs(sum(w for _,w in v['weights'])-1),1e-6)
                    self.assertEqual(set(b for b,_ in v['weights']),{0,1})
                    self.assertAlmostEqual(dict(v['weights'])[0],.25,delta=1/32767)
                self.assertEqual(out.with_suffix('.vg').exists(),target in ('s2','s3'))
                self.assertEqual(out.with_suffix('.vvd').exists(),target in ('s0','s1'))

    def test_material_guid_binding(self):
        out,_=self.run_compiler(extra=['--material-guid','test/material=123456789abcdef0'])
        self.assertEqual(Model(out,'s0').materials[0]['guid'],0x123456789abcdef0)
        _,run=self.run_compiler(extra=['--material-guid','test/material=xyz'],name='bad',ok=False)
        self.assertIn('invalid material GUID',run.stderr)

    def test_animation_sections_and_native_tracks(self):
        frames=[]
        for i in range(95):
            frames.append([((i*.125,0,0),(0,0,i*.01),(1,1,1)),
                           ((0,i*.05,2),(i*.002,0,0),(1+i*.003,1,1))])
        write_smd(self.work/'anim.smd',self.bones,frames)
        for target in ('s0','s3'):
            out,_=self.run_compiler(self.qc.replace('$sequence idle "mesh.smd"','$sequence move "anim.smd" fps 20'),target=target,name=target)
            m=Model(out,target); decoded=m.animation(m.sequences[0]['animations'][0])
            self.assertEqual(len(decoded),95)
            for i,(expected,actual) in enumerate(zip(frames,decoded)):
                for eb,ab in zip(expected,actual):
                    for x,y in zip(eb[0],ab[0]): self.assertAlmostEqual(x,y,delta=.001,msg=str(i))
                    for x,y in zip(eb[1],ab[1]): self.assertAlmostEqual(x,y,delta=.0002,msg=str(i))
                    for x,y in zip(eb[2],ab[2]): self.assertAlmostEqual(x,y,delta=.0016,msg=str(i))

    def test_geometry_decompile_recompile(self):
        for target in PROFILES:
            out,_=self.run_compiler(target=target,name=target)
            export=decompile(out,self.work/(target+'-export'),target)
            rebuilt=self.work/(target+'-rebuilt.rmdl')
            run=subprocess.run([str(self.compiler),'--target',target,'-quiet','-o',str(rebuilt),str(export)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            def positions(path):
                return sorted(tuple(v['pos']) for tri in Model(path,target).render()[0][0]['triangles'] for v in tri)
            self.assertEqual(positions(out),positions(rebuilt))

    def test_unsupported_native_physics_rejected(self):
        _,run=self.run_compiler(self.qc+'\n$collisionmodel "mesh.smd" { $mass 5 }\n',ok=False)
        self.assertIn('native physics',run.stdout)

    def test_attachments_native_stride(self):
        qc=self.qc+'\n$attachment "a" "arm" 1 2 3 rotate 0 20 0\n$attachment "b" "root" 3 2 1\n'
        out,_=self.run_compiler(qc)
        m=Model(out,'s0'); self.assertEqual([a['name'] for a in m.attachments],['a','b'])
        self.assertEqual(m.attachments[0]['bone'],1)
        self.assertEqual([m.attachments[0]['matrix'][i] for i in (3,7,11)],[1,2,3])
        export=decompile(out,self.work/'attachments','s0')
        rebuilt=self.work/'attachment-rebuilt.rmdl'
        run=subprocess.run([str(self.compiler),'--target','s0','-quiet','-o',str(rebuilt),str(export)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        reread=Model(rebuilt,'s0')
        for a,b in zip(m.attachments,reread.attachments): self.assertEqual(a['matrix'],b['matrix'])

    def test_multiple_models_native_stride(self):
        qc=self.qc.replace('$body body "mesh.smd"','$bodygroup body {\n studio "mesh.smd"\n blank\n studio "mesh.smd"\n }')
        out,_=self.run_compiler(qc)
        m=Model(out,'s0'); self.assertEqual(len(m.bodyparts[0]['models']),3)
        self.assertEqual([len(x['meshes']) for x in m.bodyparts[0]['models']],[1,0,1])
        self.assertEqual(sum(len(x['triangles']) for x in m.render()[0]),2)

    def test_lod_buffers_all_profiles(self):
        qc=self.qc+'\n$lod 200 { replacemodel "mesh.smd" "mesh.smd" }\n$lod 50 { replacemodel "mesh.smd" "mesh.smd" }\n'
        for target in PROFILES:
            out,_=self.run_compiler(qc,target=target,name=target)
            self.assertEqual([sum(len(x['triangles']) for x in lod) for lod in Model(out,target).render()],[1,1,1])

    def test_native_hitbox_stride(self):
        out,_=self.run_compiler(self.qc+'\n$hboxset "main"\n$hbox 1 "root" -1 -2 -3 1 2 3\n$hbox 2 "arm" -2 -3 -4 2 3 4\n')
        m=Model(out,'s0'); sets=m.get('i',0xB4)
        self.assertEqual(m.get('i',sets+4),2)
        box=sets+m.get('i',sets+8)
        self.assertEqual(m.get('2i',box),(0,1)); self.assertEqual(m.get('2i',box+44),(1,2))

    def test_native_blend_offsets(self):
        write_smd(self.work/'second.smd',self.bones,self.frames)
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence blend { "mesh.smd" "second.smd" blend move_x 0 1 }')
        out,_=self.run_compiler(qc); m=Model(out,'s0')
        self.assertEqual(len(m.sequences[0]['animations']),2)
        for desc in m.sequences[0]['animations']:
            self.assertEqual(len(m.animation(desc)),1)

    def test_native_event_options_256(self):
        options='x'*140
        qc=self.qc.replace('$sequence idle "mesh.smd"',f'$sequence idle {{ "mesh.smd" event 1004 0 "{options}" }}')
        out,_=self.run_compiler(qc); m=Model(out,'s0'); seq=m.sequences[0]['offset']
        self.assertEqual(m.get('i',seq+0x18),1)
        event=seq+m.get('i',seq+0x1C)
        self.assertEqual(m.string(event+12),options)

    def test_delta_animation_uses_zero_base(self):
        delta=[[((.5,0,0),(0,0,.2),(0,0,0)),((0,.2,0),(.1,0,0),(0,0,0))]]
        write_smd(self.work/'delta.smd',self.bones,delta)
        qc=self.qc+'\n$sequence delta "delta.smd" delta\n'
        out,_=self.run_compiler(qc); m=Model(out,'s0'); seq=m.sequences[1]
        self.assertTrue(seq['flags']&4)
        frame=m.animation(seq['animations'][0])[0]
        self.assertAlmostEqual(frame[1][0][1],.2,delta=.001)
        self.assertAlmostEqual(frame[1][1][0],.1,delta=.0002)

    def test_complex_weights_are_not_truncated(self):
        bones=[dict(name=f'b{i}',parent=i-1) for i in range(4)]
        frame=[((0,0,i),(0,0,0),(1,1,1)) for i in range(4)]
        tris=[('test/material',[(v[0],v[1],v[2],[(i,.25) for i in range(4)]) for v in self.tris[0][1]])]
        write_smd(self.work/'mesh.smd',bones,[frame],tris)
        _,run=self.run_compiler(ok=False)
        self.assertIn('complex skinning',run.stdout)

    def test_dmx_vertex_colors_and_second_uv(self):
        from decompile53 import write_dmx
        corners=[]
        for i,v in enumerate(self.tris[0][1]):
            corners.append((v[0],v[1],v[3],dict(uv=v[2],uv2=(.125,.875),color=(1,.5,0,1),id=i)))
        write_dmx(self.work/'mesh.dmx',self.bones,self.frames[0],[('test/material',0,corners)],model_space=True)
        for target in PROFILES:
            out,_=self.run_compiler(self.qc.replace('mesh.smd','mesh.dmx'),target=target,name=target)
            vertex=Model(out,target).render()[0][0]['triangles'][0][0]
            self.assertEqual(vertex['color'],(255,128,0,255))
            self.assertEqual(vertex['uv2'],(.125,.875))

    def test_truncated_or_wrong_format_rejected(self):
        out,_=self.run_compiler(); data=out.read_bytes()
        out.write_bytes(data[:100])
        with self.assertRaises(ValueError): Model(out,'s0')
        data=bytearray(data); struct.pack_into('<i',data,4,53); out.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'v54'): Model(out,'s0')


if __name__=='__main__': unittest.main()
