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
from decompile54 import decompile, write_smd
from validate54 import validate, compare_animation_metadata


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

    def test_piecewise_root_motion_roundtrip_all_profiles(self):
        frames=[[((j*.5,0,0),(0,0,0),(1,1,1)),((0,0,2),(0,0,0),(1,1,1))] for j in range(95)]
        write_smd(self.work/'walk.smd',self.bones,frames)
        qc=self.qc.replace('$sequence idle "mesh.smd"','$legacymovement\n$sequence walk "walk.smd" LX')
        for target in PROFILES:
            out,_=self.run_compiler(qc,target=target,name=target)
            m=Model(out,target); desc=m.sequences[0]['animations'][0]; moves=m.movements(desc)
            self.assertEqual(len(moves),1); self.assertEqual(moves[0]['end_frame'],94)
            self.assertAlmostEqual(moves[0]['position'][0],47,delta=.0001)
            self.assertAlmostEqual(moves[0]['v0'],47,delta=.0001)
            self.assertAlmostEqual(moves[0]['v1'],47,delta=.0001)
            self.assertEqual(moves[0]['flags']&0x40,0x40)
            self.assertFalse(m.get('i',desc+12)&0x40000); self.assertEqual(m.get('i',desc+0x1C),0)
            for pose in m.animation(desc): self.assertAlmostEqual(pose[0][0][0],0,delta=.001)
            export=decompile(out,self.work/(target+'export'),target)
            rebuilt,_=self.run_compiler(export.read_text(),target=target,name=target+'rebuilt',extra=['-path',str(export.parent)])
            self.assertEqual(validate(rebuilt,target,out,animation_metadata=True)['differences'],[])

    def test_explicit_movement_records_and_comparison(self):
        frames=[self.frames[0] for _ in range(9)]
        write_smd(self.work/'walk.smd',self.bones,frames)
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence walk { "walk.smd"\nmovementrecord 4 64 2 6 30 1 0 0 4 0 0\nmovementrecord 8 128 6 2 60 0 1 0 4 4 0\n}')
        for target in PROFILES:
            out,_=self.run_compiler(qc,target=target,name=target)
            m=Model(out,target); moves=m.movements(m.sequences[0]['animations'][0])
            self.assertEqual([r['end_frame'] for r in moves],[4,8]); self.assertEqual(moves[1]['angle'],60)
            export=decompile(out,self.work/(target+'export'),target)
            rebuilt,_=self.run_compiler(export.read_text(),target=target,name=target+'rebuilt',extra=['-path',str(export.parent)])
            self.assertEqual(validate(rebuilt,target,out,animation_metadata=True)['differences'],[])
            changed,_=self.run_compiler(qc.replace('6 2 60','6 2 65'),target=target,name=target+'changed')
            self.assertIn('sequence 0 blend 0 movements',validate(changed,target,out,animation_metadata=True)['differences'])

    def test_invalid_movement_records_rejected(self):
        for i,records in enumerate(('movementrecord 1 64 1 1 0 1 0 0 1 0 0',
                                   'movementrecord 0 64 nan 1 0 1 0 0 1 0 0',
                                   'movementrecord 0 64 1 1 0 1 0 0 1 0 0\nmovementrecord 0 64 1 1 0 1 0 0 1 0 0')):
            self.run_compiler(self.qc.replace('$sequence idle "mesh.smd"','$sequence idle { "mesh.smd"\n'+records+'\n}'),name=f'bad{i}',ok=False)

    def test_frame_movement_requests_stay_rejected(self):
        for i,options in enumerate(('rm','rootmotion','framemovement','LX')):
            qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "mesh.smd" '+options)
            # Explicit rm must not disappear when legacy extraction is selected.
            if options=='rm': qc='$legacymovement\n'+qc
            if options=='LX':
                write_smd(self.work/'move.smd',self.bones,[self.frames[0],[((1,0,0),(0,0,0),(1,1,1)),self.frames[0][1]]])
                qc=qc.replace('$sequence idle "mesh.smd"','$sequence idle "move.smd"')
            self.run_compiler(qc,name=f'reject{i}',ok=False)

    def test_ik_chain_roundtrip_all_profiles(self):
        bones=[dict(name='hip',parent=-1),dict(name='twist',parent=0),dict(name='knee',parent=1),dict(name='foot',parent=2)]
        frame=[((0,0,i),(0,0,0),(1,1,1)) for i in range(4)]
        tris=[('test/material',[(p,n,uv,[(3,1.)]) for p,n,uv,w in self.tris[0][1]])]
        write_smd(self.work/'mesh.smd',bones,[frame],tris)
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "mesh.smd" noautoik')
        qc+='\n$ikchain leg foot links hip knee foot knee .25 -.5 1 angle_unknown .8660254\n'
        for target in PROFILES:
            out,_=self.run_compiler(qc,target=target,name=target)
            m=Model(out,target); chains=m.ik_chains(); self.assertEqual(len(chains),1)
            self.assertEqual([m.bones[l['bone']]['name'] for l in chains[0]['links']],['hip','knee','foot'])
            self.assertEqual(chains[0]['links'][0]['knee'],(.25,-.5,1))
            export=decompile(out,self.work/(target+'export'),target)
            rebuilt,_=self.run_compiler(export.read_text(),target=target,name=target+'rebuilt',extra=['-path',str(export.parent)])
            self.assertEqual(validate(rebuilt,target,out,animation_metadata=True)['differences'],[])
            changed,_=self.run_compiler(qc.replace('.8660254','.5'),target=target,name=target+'changed')
            self.assertIn('IK chains',validate(changed,target,out,animation_metadata=True)['differences'])
            default,_=self.run_compiler(qc.replace(' angle_unknown .8660254',''),target=target,name=target+'default')
            self.assertAlmostEqual(Model(default,target).ik_chains()[0]['unknown'],.8660254,places=7)

    def test_malformed_motion_and_ik_bounds(self):
        frames=[self.frames[0],self.frames[0]]; write_smd(self.work/'walk.smd',self.bones,frames)
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence walk "walk.smd" movementrecord 1 64 1 1 0 1 0 0 1 0 0')
        out,_=self.run_compiler(qc); m=Model(out,'s0'); desc=m.sequences[0]['animations'][0]
        data=bytearray(out.read_bytes()); record=desc+m.get('i',desc+0x18); struct.pack_into('<i',data,record,2); out.write_bytes(data)
        m=Model(out,'s0')
        with self.assertRaisesRegex(ValueError,'movement end frame'): m.movements(desc)
        data=bytearray(out.read_bytes()); struct.pack_into('<i',data,0x124,1); struct.pack_into('<i',data,0x128,len(data)-4); out.write_bytes(data)
        m=Model(out,'s0')
        with self.assertRaisesRegex(ValueError,'span outside'): m.ik_chains()

    def test_invalid_ik_source_and_native_links_rejected(self):
        bones=[dict(name='hip',parent=-1),dict(name='knee',parent=0),dict(name='foot',parent=1)]
        frame=[((0,0,i),(0,0,0),(1,1,1)) for i in range(3)]
        write_smd(self.work/'mesh.smd',bones,[frame],self.tris)
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "mesh.smd" noautoik')
        chain='\n$ikchain leg foot knee 1 0 0 angle_unknown .8660254\n'
        self.run_compiler(qc+chain.replace('.8660254','nan'),name='nonfinite',ok=False)
        out,_=self.run_compiler(qc+chain); m=Model(out,'s0'); p=m.get('i',0x128); q=p+m.get('i',p+12)
        data=bytearray(out.read_bytes()); struct.pack_into('<i',data,q,99); out.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'outside skeleton'): Model(out,'s0').ik_chains()

    def test_animation_metadata_roundtrip_all_profiles(self):
        for i in range(6):
            frames=[[((j*.125+i,0,0),(0,0,j*.01),(1,1,1)),
                     ((0,i*.1,2),(0,j*.002,0),(1,1,1))] for j in range(35)]
            write_smd(self.work/f'blend{i}.smd',self.bones,frames)
        qc=self.qc.split('$sequence')[0]
        qc+='$poseparameter move_x -2 3\n$poseparameter move_y -1 1 loop 2\n'
        qc+='$sequence blend {\n'+' '.join(f'"blend{i}.smd"' for i in range(6))+'\n'
        qc+='blendwidth 3 blend move_x -2 3 blend move_y -1 1\nposekeys 5 -2 0 3 -1 1\n'
        qc+='fps 20 fadein .125 fadeout .375 snap hidden activity ACT_IDLE 3\n'
        qc+='activitymodifier "armed" negate\nevent 1004 17 "'+'x'*200+'"\n'
        qc+='eventcycle AE_TEST .123456789 "named event"\n}\n'
        for target in PROFILES:
            with self.subTest(target=target):
                out,_=self.run_compiler(qc,target=target,name=target)
                m=Model(out,target); meta=m.sequence_metadata(m.sequences[0])
                self.assertEqual(meta['grid'],(3,2)); self.assertEqual(meta['posekeys'],[-2,0,3,-1,1])
                self.assertEqual(meta['events'][0]['event'],1004)
                self.assertAlmostEqual(meta['events'][1]['cycle'],.123456789,places=7)
                source=decompile(out,self.work/(target+'export'),target)
                rebuilt,_=self.run_compiler(source.read_text(),target=target,name=target+'rebuilt',extra=['-path',str(source.parent)])
                self.assertEqual(validate(rebuilt,target,out,animation_metadata=True)['differences'],[])

    def test_event_cycles_reject_invalid_values(self):
        for i,value in enumerate(('-0.1','1.1','nan','inf')):
            qc=self.qc.replace('$sequence idle "mesh.smd"',f'$sequence idle {{ "mesh.smd" eventcycle AE_TEST {value} "" }}')
            self.run_compiler(qc,name=f'invalid{i}',ok=False)

    def test_animation_metadata_detects_event_changes(self):
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle { "mesh.smd" eventcycle AE_TEST .25 "hello" }')
        out,_=self.run_compiler(qc)
        changed,_=self.run_compiler(qc.replace('.25','.5'),name='changed')
        self.assertIn('sequence 0 events',validate(changed,'s0',out,animation_metadata=True)['differences'])

    def test_named_blends_keep_independent_timing_flags_and_weights(self):
        for i,count in enumerate((4,7)):
            frames=[[((j*.1,0,0),(0,0,0),(1,1,1)),((0,0,2+j*.125),(0,0,0),(1,1,1))] for j in range(count)]
            write_smd(self.work/f'track{i}.smd',self.bones,frames)
        qc=self.qc.split('$sequence')[0]
        qc+='$animation slow "track0.smd" fps 12 loop noforceloop\n$animation fast "track1.smd" fps 24\n'
        qc+='$weightlist mask { "root" .3 "arm" .7 }\n$sequence blend { slow fast blend speed 0 1 hidden seqweights mask }\n'
        for target in ('s0','s3'):
            out,_=self.run_compiler(qc,target=target,name=target)
            source=decompile(out,self.work/(target+'export'),target)
            rebuilt,_=self.run_compiler(source.read_text(),target=target,name=target+'rebuilt',extra=['-path',str(source.parent)])
            self.assertEqual(validate(rebuilt,target,out,animation_metadata=True)['differences'],[])
            # Geometry stays identical when only the animation's source changes.
            changedqc=qc.replace('slow fast','fast fast')
            changed,_=self.run_compiler(changedqc,target=target,name=target+'changed')
            differences=validate(changed,target,out,animation_metadata=True)['differences']
            self.assertIn('sequence 0 blend 0 poses',differences)
            self.assertIn('sequence 0 blend 0 fps',differences)

    def test_malformed_sequence_metadata_rejected(self):
        out,_=self.run_compiler()
        data=bytearray(out.read_bytes()); m=Model(out,'s0'); p=m.sequences[0]['offset']
        struct.pack_into('<i',data,p+0x44,2); out.write_bytes(data)
        m=Model(out,'s0')
        with self.assertRaisesRegex(ValueError,'blend grid'): m.sequence_metadata(m.sequences[0])

    def test_reference_descriptor_is_not_an_embedded_clip(self):
        out,_=self.run_compiler(); m=Model(out,'s0'); data=bytearray(out.read_bytes())
        p=m.sequences[0]['offset']; struct.pack_into('<i',data,p+0x38,0); out.write_bytes(data)
        reference=m; m=Model(out,'s0'); self.assertEqual(m.sequence_metadata(m.sequences[0])['grid'],(1,1))
        self.assertIn('sequence 0 blend count',compare_animation_metadata(m,reference))
        with self.assertRaisesRegex(ValueError,'without an embedded animation'):
            decompile(out,self.work/'refexport','s0')

    def test_single_frame_events_and_delta_roundtrip(self):
        write_smd(self.work/'delta.smd',self.bones,[[((.5,0,0),(0,0,.2),(0,0,0)),((0,.2,0),(.1,0,0),(0,0,0))]])
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle { "mesh.smd" event 1004 0 "one frame" }')
        qc+='\n$sequence delta "delta.smd" delta\n'
        for target in ('s0','s3'):
            out,_=self.run_compiler(qc,target=target,name=target)
            source=decompile(out,self.work/(target+'export'),target)
            rebuilt,_=self.run_compiler(source.read_text(),target=target,name=target+'rebuilt',extra=['-path',str(source.parent)])
            self.assertEqual(validate(rebuilt,target,out,animation_metadata=True)['differences'],[])

    def test_native_layers_fail_instead_of_emitting_source_layout(self):
        self.run_compiler(self.qc+'\n$sequence layered { "mesh.smd" addlayer idle }\n',ok=False)

    def test_malformed_events_and_unsupported_types_rejected(self):
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle { "mesh.smd" eventcycle AE_TEST .25 "hello" }')
        out,_=self.run_compiler(qc); m=Model(out,'s0'); p=m.sequences[0]['offset']
        event=p+m.get('i',p+0x1C); original=out.read_bytes()
        data=bytearray(original); struct.pack_into('<f',data,event,2); out.write_bytes(data)
        m=Model(out,'s0')
        with self.assertRaisesRegex(ValueError,'event cycle'): m.sequence_metadata(m.sequences[0])
        data=bytearray(original); struct.pack_into('<i',data,event+8,1025); out.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'event type'): decompile(out,self.work/'badtype','s0')
        data=bytearray(original); data[event+12:event+0x10C]=b'x'*256; out.write_bytes(data)
        m=Model(out,'s0')
        with self.assertRaisesRegex(ValueError,'event options'): m.sequence_metadata(m.sequences[0])

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
        bones=[dict(name=f'b{i}',parent=i-1) for i in range(16)]
        frame=[((0,0,i),(0,0,0),(1,1,1)) for i in range(16)]
        tris=[]; expected={}
        for count in (1,2,3,4,8,16):
            weights=[(i,(i+1)/(count*(count+1)/2)) for i in range(count)]
            tri=[]
            for pos,normal,uv,_ in self.tris[0][1]:
                point=(pos[0]+count*10,pos[1],pos[2]); expected[point]=dict(weights)
                tri.append((point,normal,uv,weights))
            tris.append(('test/material',tri))
        write_smd(self.work/'mesh.smd',bones,[frame],tris)
        for target in PROFILES:
            out,_=self.run_compiler(target=target,name=target)
            model=Model(out,target); self.assertTrue(model.get('i',0x9C)&0x4000)
            self.assertEqual(len(model.bones),16)
            self.assertTrue(all(bone['flags']&0x400 for bone in model.bones))
            for mesh in model.render()[0]:
                for triangle in mesh['triangles']:
                    for vertex in triangle:
                        point=tuple(round(x,4) for x in vertex['pos'])
                        wanted=expected[point]; actual=dict(vertex['weights'])
                        self.assertEqual(wanted.keys(),actual.keys())
                        self.assertEqual(sum(actual.values()),1)
                        for bone,weight in wanted.items(): self.assertAlmostEqual(actual[bone],weight,delta=2/32767)
            self.assertEqual(out.with_suffix('.vvw').exists(),target in ('s0','s1'))
            if target in ('s0','s1'):
                vvw=Reader(out.with_suffix('.vvw').read_bytes())
                self.assertEqual(vvw.get('i',0),model.get('i',8)); self.assertEqual(vvw.get('i',4),1)
                self.assertEqual(model.get('i',0x220),len(vvw.data))
                vtx=Reader(out.with_suffix('.dx11.vtx').read_bytes()); self.assertEqual(vtx.get('i',12),16)
            export=decompile(out,self.work/(target+'-export'),target)
            rebuilt=self.work/(target+'-rebuilt.rmdl')
            run=subprocess.run([str(self.compiler),'--target',target,'-quiet','-o',str(rebuilt),str(export)],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            from validate54 import validate
            self.assertEqual(validate(rebuilt,target,out)['differences'],[])

    def test_excess_influences_fail(self):
        bones=[dict(name=f'b{i}',parent=i-1) for i in range(17)]
        frame=[((0,0,0),(0,0,0),(1,1,1)) for _ in bones]
        tris=[('test/material',[(v[0],v[1],v[2],[(i,1/17) for i in range(17)]) for v in self.tris[0][1]])]
        write_smd(self.work/'mesh.smd',bones,[frame],tris)
        _,run=self.run_compiler(ok=False); self.assertIn('max 16',run.stdout)

    def test_malformed_complex_weight_companions_rejected(self):
        bones=[dict(name=f'b{i}',parent=i-1) for i in range(4)]
        frame=[((0,0,0),(0,0,0),(1,1,1)) for _ in bones]
        tris=[('test/material',[(v[0],v[1],v[2],[(i,.25) for i in range(4)]) for v in self.tris[0][1]])]
        write_smd(self.work/'mesh.smd',bones,[frame],tris)
        out,_=self.run_compiler(); extra=out.with_suffix('.vvw')
        raw=extra.read_bytes(); extra.write_bytes(raw[:44])
        with self.assertRaises(ValueError): Model(out,'s0').render()
        bad=bytearray(raw); struct.pack_into('<i',bad,0,0); extra.write_bytes(bad)
        with self.assertRaisesRegex(ValueError,'checksum'): Model(out,'s0').render()
        out,_=self.run_compiler(target='s3',name='vg')
        path=out.with_suffix('.vg'); data=bytearray(path.read_bytes())
        reader=Reader(data); vertex_start=reader.get('Q',0x40)
        struct.pack_into('<H',data,vertex_start+14,65535); path.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'extra-weight index'): Model(out,'s3').render()

    def test_repeated_weights_fit_native_vg_index_range(self):
        # A naive per-vertex table needs 67,242 entries, beyond the uint16 start
        # index limit. Identical middle influences can share one native record.
        bones=[dict(name=f'b{i}',parent=i-1) for i in range(16)]
        frame=[((0,0,0),(0,0,0),(1,1,1)) for _ in bones]
        triangles=[]
        for triangle in range(1601):
            corners=[]
            for pos,normal,uv,_ in self.tris[0][1]:
                corners.append(((pos[0]+triangle*4,pos[1],pos[2]),normal,uv,[(i,1/16) for i in range(16)]))
            triangles.append(('test/material',corners))
        write_smd(self.work/'mesh.smd',bones,[frame],triangles)
        out,_=self.run_compiler(target='s3')
        rendered=Model(out,'s3').render()[0][0]['triangles']
        self.assertEqual(len(rendered),1601)
        for triangle in (rendered[0],rendered[-1]):
            for vertex in triangle:
                self.assertEqual(dict(vertex['weights']),dict((i,1/16) for i in range(16)))

    def test_unrepresentable_weight_ratio_fails_budget(self):
        bones=[dict(name=f'b{i}',parent=i-1) for i in range(4)]
        frame=[((0,0,0),(0,0,0),(1,1,1)) for _ in bones]
        weights=[(0,1.),(1,1e-9),(2,1e-9),(3,1e-9)]
        triangles=[('test/material',[(v[0],v[1],v[2],weights) for v in self.tris[0][1]])]
        write_smd(self.work/'mesh.smd',bones,[frame],triangles)
        _,run=self.run_compiler(target='s3',ok=False)
        self.assertIn('quantization error budget',run.stdout)

    def test_small_positive_influences_survive(self):
        bones=[dict(name=f'b{i}',parent=i-1) for i in range(4)]
        frame=[((0,0,0),(0,0,0),(1,1,1)) for _ in bones]
        weights=[(0,.99994),(1,.00002),(2,.00002),(3,.00002)]
        triangles=[('test/material',[(v[0],v[1],v[2],weights) for v in self.tris[0][1]])]
        write_smd(self.work/'mesh.smd',bones,[frame],triangles)
        for target in ('s0','s3'):
            out,_=self.run_compiler(target=target,name=target)
            decoded=Model(out,target).render()[0][0]['triangles'][0][0]['weights']
            self.assertEqual(len(decoded),4)
            self.assertTrue(all(weight>0 for _,weight in decoded))

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

    def test_complex_vvw_after_vvc_with_multiple_meshes_and_lods(self):
        from decompile53 import write_dmx
        bones=[dict(name=f'b{i}',parent=i-1) for i in range(4)]
        frame=[((0,0,0),(0,0,0),(1,1,1)) for _ in bones]
        corners=[(v[0],v[1],[(i,.25) for i in range(4)],
                  dict(uv=v[2],uv2=(.125,.875),color=(1,.5,0,1),id=index))
                 for index,v in enumerate(self.tris[0][1])]
        write_dmx(self.work/'mesh.dmx',bones,frame,[('test/material',0,corners)],model_space=True)
        qc=self.qc.replace('mesh.smd','mesh.dmx')+'\n$body second "mesh.dmx"\n$lod 30 { replacemodel "mesh.dmx" "mesh.dmx" }\n'
        for target in PROFILES:
            out,_=self.run_compiler(qc,target=target,name=target)
            model=Model(out,target)
            render=model.render()
            self.assertEqual([sum(len(m['triangles']) for m in lod) for lod in render],[2,2])
            for lod in render:
                for mesh in lod:
                    for tri in mesh['triangles']:
                        for vertex in tri:
                            self.assertEqual(dict(vertex['weights']),dict((i,.25) for i in range(4)))
                            self.assertEqual(vertex['color'],(255,128,0,255))
                            self.assertEqual(vertex['uv2'],(.125,.875))
            if target in ('s0','s1'):
                self.assertEqual(model.get('i',0x21C),sum(model.get('i',o) for o in (0x1D0,0x1D4,0x1D8)))

    def test_truncated_or_wrong_format_rejected(self):
        out,_=self.run_compiler(); data=out.read_bytes()
        out.write_bytes(data[:100])
        with self.assertRaises(ValueError): Model(out,'s0')
        data=bytearray(data); struct.pack_into('<i',data,4,53); out.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'v54'): Model(out,'s0')


if __name__=='__main__': unittest.main()
