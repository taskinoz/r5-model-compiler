"""Native v54 authored-input regressions; historical TF2 tests are separate."""
from pathlib import Path
import math
import json
from unittest.mock import patch
import os
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from mdl54 import Model, Reader, PROFILES, SequenceAsset
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

    def test_external_rig_and_sequence_assets(self):
        frames=[[((f*.1,0,0),(0,0,0),(1,1,1)),self.frames[0][1]] for f in range(65)]
        write_smd(self.work/'move.smd',self.bones,frames)
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "mesh.smd"\n$sequence walk { "move.smd" rm\neventcycle "AE_MARKER" .375 "mark"\n}')
        for target in PROFILES:
            with self.subTest(target=target):
                original,_=self.run_compiler(qc,target=target,name=target+'embedded')
                out,_=self.run_compiler(qc,target=target,name=target+'external',extra=['--external-assets'])
                model,ref=Model(out,target),Model(original,target)
                rig=Model(out.with_suffix('.rrig'),target)
                self.assertEqual(model.sequences[0]['name'],'ref')
                self.assertFalse(model.sequences[0]['animations'])
                self.assertEqual([s['name'] for s in model.sequences[1:]],[s['name'] for s in ref.sequences])
                self.assertEqual(rig.bones,ref.bones);self.assertEqual(rig.sequences,[])
                self.assertEqual(model.get('i',0x158),-1)
                self.assertEqual(rig.get('i',0x158),0)
                self.assertTrue(all(model.get('i',s['offset'])==0 for s in model.sequences))
                self.assertTrue(all(s['animations'] for s in model.sequences[1:]))
                self.assertTrue(all(model.get('i',a)==0 for s in model.sequences for a in s['animations']))
                self.assertTrue(all(ref.get('i',a)==0 for s in ref.sequences for a in s['animations']))
                self.assertTrue(all(model.get('i',a+12)&0x20000 for s in model.sequences for a in s['animations']))
                self.assertEqual(validate(out,target,original)['differences'],[])
                for i,seq in enumerate(ref.sequences):
                    asset=SequenceAsset(out.with_suffix(f'.seq{i+1}.rseq'),rig)
                    expected=ref.sequences; ref.sequences=[seq]
                    # a standalone sequence whose clips have frame movement also carries
                    # 0x40000 (retail assets); the model's own copy does not
                    moving=all(asset.get('i',d+12)&0x40000 for d in asset.sequences[0]['animations'])
                    self.assertEqual(asset.sequences[0]['flags'],seq['flags']|(0x40000 if moving else 0))
                    # ...and stores end 1 on its unused blend axes (retail assets); the model 0
                    self.assertEqual(asset.sequence_metadata(asset.sequences[0])['end'],(1.0,1.0))
                    self.assertEqual(compare_animation_metadata(asset,ref),(['sequence 0 flags'] if moving else [])+['sequence 0 end'])
                    ref.sequences=expected
                    self.assertTrue(all(asset.get('i',d)==0 for d in asset.sequences[0]['animations']))

    def test_standalone_animation_import_all_profiles(self):
        from import_anim54 import import_animations
        frames=[[((f*.125,0,0),(0,0,0),(1,1,1)),((0,0,2),(0,f*.002,0),(1,1,1))] for f in range(41)]
        write_smd(self.work/'move.smd',self.bones,frames)
        qc=self.qc+'$sequence walk { "move.smd" rm\neventcycle "AE_MARKER" .375 "mark"\n}\n'
        for target in PROFILES:
            with self.subTest(target=target):
                original,_=self.run_compiler(qc,target=target,name=target+'imports',extra=['--external-assets'])
                model=Model(original,target)
                sequences=[original.with_suffix(f'.seq{i}.rseq') for i in range(len(model.sequences))]
                qci=import_animations(original.with_suffix('.rrig'),sequences,self.work/(target+'includes'),target)
                host=self.qc[:self.qc.index('$sequence')]+'$include "'+str(qci).replace(chr(92),'/')+'"\n'
                rebuilt,_=self.run_compiler(host,target=target,name=target+'imported',extra=['-path',str(qci.parent)])
                self.assertEqual(validate(rebuilt,target,original,animation_metadata=True)['differences'],[])
                self.assertEqual([s['name'] for s in Model(rebuilt,target).sequences],['ref','idle','walk'])
                report=json.loads(qci.with_name('import54.report.json').read_text())
                self.assertEqual(report['labels'],['ref','idle','walk'])
                self.assertEqual(len(report['inputs']),4)
                self.assertEqual(len(report['outputs']),4)  # include, two poses, frame movement; ref uses bind pose

    def test_standalone_import_rejects_unsupported_and_preserves_existing_output(self):
        from import_anim54 import import_animations
        out,_=self.run_compiler(target='s3',extra=['--external-assets'])
        rig=out.with_suffix('.rrig');seq=out.with_suffix('.seq1.rseq')
        qci=import_animations(rig,[seq],self.work/'import','s3')
        before={p.name:p.read_bytes() for p in qci.parent.iterdir()}
        data=bytearray(seq.read_bytes());struct.pack_into('<i',data,0x88,1);seq.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'nodes/layers/IK/keyvalues'):
            import_animations(rig,[seq],qci.parent,'s3')
        self.assertEqual({p.name:p.read_bytes() for p in qci.parent.iterdir()},before)
        struct.pack_into('<i',data,0x88,0);seq.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'duplicate sequence'):
            import_animations(rig,[seq,seq],self.work/'duplicates','s3')
        with self.assertRaisesRegex(ValueError,'namespace'):
            import_animations(rig,[seq],self.work/'badnamespace','s3',namespace='../bad')
        struct.pack_into('<i',data,0,1);seq.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'base selector'):
            import_animations(rig,[seq],self.work/'badbase','s3')

    def test_release_ik_rules_match_retail_layout_and_import(self):
        # Retail sequence assets store only studiomdl's automatic releases: 0x88-byte rules
        # (index k, type 4, slot = chain, range 0-0-1-1, error index past the rule array).
        from import_anim54 import import_animations
        from decompile54 import release_rules
        bones=[dict(name='root',parent=-1),dict(name='hip',parent=0),dict(name='knee',parent=1),dict(name='foot',parent=2),
               dict(name='arm',parent=0),dict(name='hand',parent=4),dict(name='palm',parent=5)]
        frames=[[((0,0,i),(0,f*.01*i,0),(1,1,1)) for i in range(7)] for f in range(6)]
        write_smd(self.work/'ikmesh.smd',bones,frames[:1],self.tris)
        write_smd(self.work/'ikmove.smd',bones,frames)
        qc=('$modelname "test/ikrel.rmdl"\n$body body "ikmesh.smd"\n$sequence idle "ikmesh.smd"\n'
            '$sequence wave "ikmove.smd"\n$ikchain leg foot links hip knee foot\n$ikchain arm palm links arm hand palm\n')
        out,_=self.run_compiler(qc,target='s3',name='ikrel',extra=['--external-assets'])
        rig=Model(out.with_suffix('.rrig'),'s3')
        asset=SequenceAsset(out.with_suffix('.seq2.rseq'),rig)
        desc=asset.sequences[0]['animations'][0]
        self.assertEqual(release_rules(asset,desc),[0,1])
        self.assertEqual(asset.get('i',asset.sequences[0]['offset']+0x90),2)
        base=desc+asset.get('i',desc+0x28)
        for k in range(2):
            words=struct.unpack_from('<34I',asset.data,base+k*0x88)
            self.assertEqual(words[:5],(k,4,k,0,k))
            self.assertEqual((words[0x58//4],words[0x6C//4],words[0x70//4]),((2-k)*0x88,0x3F800000,0x3F800000))
        sequences=[out.with_suffix(f'.seq{i}.rseq') for i in range(3)]
        qci=import_animations(out.with_suffix('.rrig'),sequences,self.work/'ikrel-import','s3')
        self.assertIn('ikrule "leg" release ikrule "arm" release',qci.read_text())
        host=qc[:qc.index('$sequence')]+'$include "'+str(qci).replace(chr(92),'/')+'"\n'
        rebuilt,_=self.run_compiler(host,target='s3',name='ikrel-rebuilt',extra=['--external-assets','-path',str(qci.parent)])
        again=SequenceAsset(rebuilt.with_suffix('.seq2.rseq'),Model(rebuilt.with_suffix('.rrig'),'s3'))
        d2=again.sequences[0]['animations'][0]
        self.assertEqual(asset.data[base:base+2*0x88],again.data[d2+again.get('i',d2+0x28):][:2*0x88])
        # other rule types have no retail layout evidence: refused for Apex
        self.run_compiler(qc.replace('$sequence wave "ikmove.smd"','$sequence wave "ikmove.smd" ikrule leg touch root'),
                          target='s3',name='ikrel-touch',ok=False)

    def test_package_embedded_ik_requires_linkage_and_matching_rig(self):
        from pack54 import package
        bones=[dict(name='root',parent=-1),dict(name='knee',parent=0),dict(name='foot',parent=1)]
        frames=[[((0,0,i),(0,0,0),(1,1,1)) for i in range(3)]]
        write_smd(self.work/'mesh.smd',bones,frames,self.tris)
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "mesh.smd" noautoik')
        out,_=self.run_compiler(qc+'\n$ikchain leg foot links root knee foot\n',target='s3',
                                extra=['--external-assets','--material-guid','test/material=123456789abcdef0'])
        def repak(command,**kwargs):
            build=json.loads(Path(command[1]).read_text())
            for suffix in ('.rpak','.starpak'):
                (Path(build['outputDir'])/(build['name']+suffix)).write_bytes(b'new artifact')
            return subprocess.CompletedProcess(command,0,'packed','')
        with patch('pack54.subprocess.run',side_effect=repak):
            report=package([out],self.work/'good-pak','r5c_test',self.compiler,'s3')
        self.assertEqual(report['models'][0]['ik_chains'],1)
        self.assertTrue(report['models'][0]['external_rig'])
        data=bytearray(out.read_bytes());struct.pack_into('<i',data,0x158,0);out.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'external-rig sentinel'):
            package([out],self.work/'pak','r5c_test',self.compiler,'s3')
        struct.pack_into('<i',data,0x158,-1);out.write_bytes(data)
        rig=out.with_suffix('.rrig');data=bytearray(rig.read_bytes())
        struct.pack_into('<i',data,0x124,0);rig.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'IK chain layout mismatch'):
            package([out],self.work/'stale-pak','r5c_test',self.compiler,'s3')

    def test_package_native_asset_dependencies_and_stale_sequences(self):
        from pack54 import package
        out,_=self.run_compiler(target='s3',extra=['--external-assets','--material-guid','test/material=123456789abcdef0'])
        # A stale second file is deliberately present after recompiling one sequence.
        out.with_suffix('.seq2.rseq').write_bytes(out.with_suffix('.seq0.rseq').read_bytes())
        calls=[]
        def repak(command,**kwargs):
            build=json.loads(Path(command[1]).read_text()); calls.append(build)
            self.assertEqual([f['_type'] for f in build['files']],['arig','mdl_'])
            rig,model=build['files']
            self.assertEqual(model['$animrigs'],[rig['_path']])
            self.assertEqual(model['$sequences'],rig['$sequences'])
            self.assertEqual(len(rig['$sequences']),2)
            source=Path(build['assetsDir'])
            asset=SequenceAsset(source/rig['$sequences'][0],Model(source/rig['_path'],'s3'))
            self.assertEqual(asset.name,rig['$sequences'][0])
            for suffix in ('.rpak','.starpak'):
                (Path(build['outputDir'])/(build['name']+suffix)).write_bytes(b'new artifact')
            return subprocess.CompletedProcess(command,0,'packed','')
        with patch('pack54.subprocess.run',side_effect=repak):
            report=package([out],self.work/'pak','r5c_test',self.compiler,'s3')
        self.assertEqual(report['models'][0]['labels'],['ref','idle'])
        # retail's form, animseq/<model path>/<label>.rseq: R5R resolves short labels
        # (Anim_PlayOnly( "idle" )) by the asset's file name
        self.assertEqual(report['models'][0]['sequences'],['animseq/test/model/ref.rseq','animseq/test/model/idle.rseq'])
        self.assertEqual(report['models'][0]['reference_sequences'],[0])
        self.assertEqual(len(calls),1)
        alias,_=self.run_compiler(self.qc.replace('test/model.rmdl','TEST/model.rmdl'),target='s3',name='alias',extra=['--external-assets','--material-guid','test/material=123456789abcdef0'])
        with self.assertRaisesRegex(ValueError,'duplicate model asset path'):
            package([out,alias],self.work/'duplicate','r5c_test',self.compiler,'s3')
        # A process that exits zero but writes nothing must not reuse old artifacts.
        with patch('pack54.subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')):
            with self.assertRaisesRegex(ValueError,'did not produce'):
                package([out],self.work/'pak','r5c_test',self.compiler,'s3')
        self.assertEqual((self.work/'pak/r5c_test.rpak').read_bytes(),b'new artifact')
        out.with_suffix('.assetset').write_text('R5AS1\ns2\n1\n')
        with self.assertRaisesRegex(ValueError,'target/magic'):
            package([out],self.work/'bad','r5c_test',self.compiler,'s3')

    def test_package_installed_weapon_rig_dependency(self):
        from pack54 import package, installed_animrig_path
        out,_=self.run_compiler(target='s3',extra=['--external-assets','--material-guid','test/material=123456789abcdef0'])
        dependency='animrig/weapons/vinson/ptpov_vinson.rrig'
        def repak(command,**kwargs):
            build=json.loads(Path(command[1]).read_text())
            rig,model=build['files']
            self.assertEqual(model['$animrigs'],[rig['_path'],dependency])
            self.assertFalse((Path(build['assetsDir'])/dependency).exists())
            self.assertEqual(rig['$sequences'],model['$sequences'])
            for suffix in ('.rpak','.starpak'):
                (Path(build['outputDir'])/(build['name']+suffix)).write_bytes(b'new artifact')
            return subprocess.CompletedProcess(command,0,'packed','')
        with patch('pack54.subprocess.run',side_effect=repak):
            report=package([out],self.work/'weapon-pak','r5c_test',self.compiler,'s3',
                           installed_animrigs=[dependency,dependency])
        self.assertEqual(report['models'][0]['installed_animrigs'],[dependency])
        for path in ('animrig/../escape.rrig','animrig//test.rrig','/animrig/test.rrig',
                     'mdl/test.rmdl','animrig/test.rmdl','animrig/C:/test.rrig'):
            with self.subTest(path=path),self.assertRaises(ValueError): installed_animrig_path(path)

    def test_package_rejects_unbound_materials_and_unsafe_paths(self):
        from pack54 import package, asset_path
        help_run=subprocess.run([sys.executable,'-I',str(ROOT/'tools/pack54.py'),'--help'],capture_output=True,text=True)
        self.assertEqual(help_run.returncode,0,help_run.stderr)
        out,_=self.run_compiler(target='s3',extra=['--external-assets'])
        with self.assertRaisesRegex(ValueError,'nonzero GUID'):
            package([out],self.work/'pak','r5c_test',self.compiler,'s3')
        for path in ('../escape.rmdl','a/../b.rmdl','a/./b.rmdl','a//b.rmdl','/a.rmdl','C:/a.rmdl','a\x00.rmdl'):
            with self.subTest(path=path),self.assertRaises(ValueError): asset_path(path)

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

    def test_native_material_shader_types(self):
        for target in PROFILES:
            out,_=self.run_compiler(target=target,name=target+'typed',extra=['--material-type','test/material=sknp'])
            model=Model(out,target); table=model.get('i',0xCC)
            self.assertGreater(table,0); self.assertEqual(model.get('B',table),4)
        self.run_compiler(name='unknownshader',extra=['--material-type','test/material=invalid'],ok=False)
        self.run_compiler(name='unknownslot',extra=['--material-type','missing=rgdp'],ok=False)

    def test_exact_material_names_round_trip(self):
        from roundtrip54 import compare_extras
        names=['models/test/shared.vmt','models/test/shared',
               'Models\\Test/Mixed.VMT','r5c_material_0']
        triangles=[]
        for i,name in enumerate(names):
            corners=[((p[0]+i*8,p[1],p[2]),n,uv,w) for p,n,uv,w in self.tris[0][1]]
            triangles.append((f'source_{i}',corners))
        write_smd(self.work/'materials.smd',self.bones,self.frames,triangles)
        qc=self.qc.replace('$body body "mesh.smd"','$body body "materials.smd"')
        qc+=''.join(f'$renamematerial "source_{i}.bmp" "{name}"\n' for i,name in enumerate(names))
        for target in PROFILES:
            with self.subTest(target=target):
                out,_=self.run_compiler(qc,target=target,name=target+'materials',extra=[
                    '--material-guid',names[0]+'=123456789abcdef0',
                    '--material-type',names[0]+'=sknp'])
                original=Model(out,target)
                self.assertEqual([m['name'] for m in original.materials],names)
                self.assertEqual(original.materials[0]['guid'],0x123456789abcdef0)
                q=decompile(out,self.work/(target+'materials_src'),target)
                rebuilt=q.with_name('rebuilt.rmdl')
                run=subprocess.run([str(self.compiler),'--target',target,'-quiet','-o',str(rebuilt),str(q)],
                                   capture_output=True,text=True,timeout=40)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                self.assertEqual([m['name'] for m in Model(rebuilt,target).materials],names)
                self.assertEqual(compare_extras(out,rebuilt,target)['issues'],[])
                self.assertEqual(validate(rebuilt,target,out)['differences'],[])
        # A later rename (the viewmodel fixture's installed-skin override) must
        # match the restored suffixed name without also renaming the bare name.
        qc+='$renamematerial "models/test/shared.vmt" "models/test/rebound.vmt"\n'
        out,_=self.run_compiler(qc,name='materials_rebound')
        self.assertEqual([m['name'] for m in Model(out,'s0').materials],
                         ['models/test/rebound.vmt',*names[1:]])

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

    def box_tris(self,lo,hi,bone=0):
        """Twelve triangles of an axis-aligned box weighted to one bone."""
        corners=[(x,y,z) for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])]
        quads=[(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)]
        tris=[]
        for q in quads:
            for a,b,c in ((q[0],q[1],q[2]),(q[0],q[2],q[3])):
                tris.append(('phys',[(corners[i],(0,0,1),(0,0),[(bone,1.0)]) for i in (a,b,c)]))
        return tris

    def test_native_phy_all_profiles(self):
        import phy54
        lo,hi=(-1,2,0),(3,5,4)
        write_smd(self.work/'box.smd',self.bones,self.frames,self.box_tris(lo,hi))
        qc=self.qc+'$surfaceprop "metal"\n$collisionmodel "box.smd" { $mass 5 }\n'
        for target in PROFILES:
            with self.subTest(target=target):
                out,_=self.run_compiler(qc,target=target,name=target+'phy')
                data=out.with_suffix('.phy').read_bytes(); rmdl=out.read_bytes()
                self.assertEqual(struct.unpack_from('<2i',rmdl,0x1CC)[0],-123456)
                self.assertEqual(struct.unpack_from('<i',rmdl,0x1DC)[0],len(data))
                self.assertAlmostEqual(struct.unpack_from('<f',rmdl,0x150)[0],5,places=5)
                parsed=phy54.parse(data,target)
                self.assertEqual(parsed['checksum'],struct.unpack_from('<i',rmdl,8)[0])
                (solid,)=parsed['solids']; (hull,)=solid['hulls']
                self.assertEqual(phy54.check_hull(hull,target=='s3'),[])
                self.assertEqual((len(hull['verts']),len(hull['faces']),len(hull['edges'])),(8,6,12))
                self.assertEqual(len(hull['edges'][0]),4 if target=='s3' else 2)
                centre=[(a+b)/2 for a,b in zip(lo,hi)]; half=[(b-a)/2 for a,b in zip(lo,hi)]
                for got in (hull['centroid'],solid['centre'],solid['centre2']):
                    for g,c in zip(got,centre): self.assertAlmostEqual(g,c,places=5)
                self.assertAlmostEqual(hull['radius'],min(half),places=5)
                # per unit mass, about the solid origin: box term plus the parallel-axis shift
                e=[(2*h)**2 for h in half]
                expected=[[(e[1]+e[2])/12+centre[1]**2+centre[2]**2,-centre[0]*centre[1],-centre[0]*centre[2]],
                          [-centre[0]*centre[1],(e[0]+e[2])/12+centre[0]**2+centre[2]**2,-centre[1]*centre[2]],
                          [-centre[0]*centre[2],-centre[1]*centre[2],(e[0]+e[1])/12+centre[0]**2+centre[1]**2]]
                for r in range(3):
                    for c in range(3): self.assertAlmostEqual(solid['inertia'][r][c],expected[r][c],places=4)
                self.assertEqual(solid['mins'],tuple(float(x) for x in lo))
                self.assertEqual(solid['maxs'],tuple(float(x) for x in hi))
                self.assertIn('"mass" "5.000000"',parsed['text'])
                self.assertIn('"surfaceprop" "metal"',parsed['text'])

    def test_stored_hull_radius_and_loose_points_round_trip(self):
        # Retail quirks kept verbatim: six S3 hulls store a radius no stored-geometry
        # rule gives, and w_bloodhound_axe keeps three vertices no face uses.
        import phy54
        from decompile54 import decompile
        from compare_phy54 import compare
        write_smd(self.work/'box.smd',self.bones,self.frames,self.box_tris((-1,2,0),(3,5,4)))
        base=self.qc+'$collisionmodel "box.smd" { $mass 5 %s}\n'
        out,_=self.run_compiler(base%'$hullradius 0 0 1.25 $hullpoint 0 0 1 3.5 4.01 ',target='s3',name='quirks')
        (solid,)=phy54.parse(out.with_suffix('.phy').read_bytes(),'s3')['solids']; (hull,)=solid['hulls']
        self.assertAlmostEqual(hull['radius'],1.25,places=6)
        self.assertEqual(len(hull['verts']),9)
        self.assertIn((1.0,3.5,4.010000228881836),hull['verts'])
        self.assertEqual(phy54.check_hull(hull,True),[])  # the loose point is not surface
        text=decompile(out,self.work/'quirks_src','s3').read_text()
        self.assertIn('$hullradius 0 0 1.25',text)
        self.assertIn('$hullpoint 0 0 1 3.5 4.01000023',text)
        q=self.work/'quirks_src'/'rebuilt.qc'; q.write_text(text); rebuilt=q.with_suffix('.rmdl')
        run=subprocess.run([str(self.compiler),'--target','s3','-quiet','-o',str(rebuilt),str(q)],capture_output=True,text=True,timeout=40)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(compare(out.with_suffix('.phy'),rebuilt.with_suffix('.phy'),'s3')['issues'],[])
        # a plain hull derives its radius and is exported without either option
        plain,_=self.run_compiler(base%'',target='s3',name='plain')
        text=decompile(plain,self.work/'plain_src','s3').read_text()
        self.assertNotIn('$hullradius',text); self.assertNotIn('$hullpoint',text)
        self.run_compiler(base%'$hullradius 0 3 1 ',target='s3',name='badhull',ok=False)

    def test_phy_negative_maximum_stored_as_flt_min(self):
        import phy54
        write_smd(self.work/'box.smd',self.bones,self.frames,self.box_tris((-4,-6,1),(-1,-2,3)))
        out,_=self.run_compiler(self.qc+'$collisionmodel "box.smd" { $mass 5 }\n',target='s3')
        (solid,)=phy54.parse(out.with_suffix('.phy').read_bytes(),'s3')['solids']
        flt_min=struct.unpack('<f',struct.pack('<I',0x00800000))[0]
        self.assertEqual(solid['maxs'],(flt_min,flt_min,3.0))
        self.assertEqual(solid['mins'],(-4.0,-6.0,1.0))

    def test_jointed_phy_decompile_roundtrip(self):
        from compare_phy54 import compare
        tris=self.box_tris((-1,-1,0),(1,1,1.5),0)+self.box_tris((-.5,-.5,2),(.5,.5,4),1)
        write_smd(self.work/'ragdoll.smd',self.bones,self.frames,tris)
        qc=(self.qc+'$surfaceprop "flesh"\n$collisionjoints "ragdoll.smd"\n{\n $mass 20\n'
            ' $jointconstrain "arm" x limit -30 30 0\n $jointconstrain "arm" y limit -10 10 0\n'
            ' $jointconstrain "arm" z limit 0 0 0\n}\n')
        for target in ('s0','s3'):
            with self.subTest(target=target):
                out,_=self.run_compiler(qc,target=target,name=target+'joints')
                export=decompile(out,self.work/(target+'-phy-export'),target,render_only=True,with_physics=True)
                self.assertIn('$collisionjoints',export.read_text())
                rebuilt=self.work/(target+'-phy-rebuilt.rmdl')
                run=subprocess.run([str(self.compiler),'--target',target,'-quiet','-o',str(rebuilt),str(export)],capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                result=compare(out.with_suffix('.phy'),rebuilt.with_suffix('.phy'),target)
                self.assertEqual(result['issues'],[])
                self.assertIn('ragdollconstraint',rebuilt.with_suffix('.phy').read_bytes().decode('latin-1'))

    def test_bvh_bent_hull_face_uses_shortest_diagonal(self):
        import bvh54, phy54
        from decompile53 import write_dmx
        from compare_bvh54 import _volume, compare as compare_bvh
        from compare_phy54 import compare as compare_phy
        verts=[(0,0,0),(6,0,0),(4,2,0),(0,2,0),
               (0,0,2),(6,0,2),(4,2,3),(0,2,2)]
        loops=[(0,3,2,1),(5,6,7,4),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
        faces=[('phys',0,[(verts[i],(0,0,1),[(0,1.)],{}) for i in loop]) for loop in loops]
        write_dmx(self.work/'bent.dmx',self.bones,self.frames[0],faces,model_space=True)
        qc=self.qc+'$collisionmodel "bent.dmx" { $mass 5 }\n'
        for target in PROFILES:
            with self.subTest(target=target):
                out,_=self.run_compiler(qc,target=target,name=target+'bent')
                (hull,)=phy54.parse(out.with_suffix('.phy').read_bytes(),target)['solids'][0]['hulls']
                self.assertEqual(phy54.check_hull(hull,target=='s3'),[])
                # PHY retains its source polygon and first-vertex-fan mass rule.
                self.assertEqual(sorted(map(len,hull['faces'])),[4]*6)
                self.assertAlmostEqual(phy54.hull_mass(hull)[0],64/3,places=4)
                (entry,)=bvh54.from_model(out,strict=True)['entries']
                self.assertEqual(entry['problems'],[])
                top=[frozenset(tuple(round(c,4) for c in p) for p in tri)
                     for tri in entry['triangles'] if all(p[2]>=2-1e-4 for p in tri)]
                self.assertEqual(set(top),{frozenset(verts[i] for i in tri) for tri in [(4,5,6),(4,6,7)]})
                self.assertAlmostEqual(_volume(entry['triangles']),-70/3,places=4)
                export=decompile(out,self.work/(target+'bent_export'),target,render_only=True,with_physics=True)
                rebuilt,_=self.run_compiler(export.read_text(),target=target,name=target+'bent_rebuilt',
                                             extra=['-path',str(export.parent)])
                self.assertEqual(compare_bvh(out,rebuilt)['issues'],[])
                self.assertEqual(compare_phy(out.with_suffix('.phy'),rebuilt.with_suffix('.phy'),target)['issues'],[])

    def test_bvh_roles_and_header(self):
        import bvh54
        write_smd(self.work/'box.smd',self.bones,self.frames,self.box_tris((-1,2,0),(3,5,4)))
        base='$body body "box.smd"\n'
        cases={'static':('$staticprop\n',(-1,0),['trace']),
               'static_phy':('$staticprop\n$collisionmodel "box.smd" { $mass 5 }\n',(1,0),['trace','hull']),
               'rigid':('$collisionmodel "box.smd" { $mass 5 }\n',(0,-1),['hull']),
               'none':('',None,[])}
        for name,(extra,roles,kinds) in cases.items():
            with self.subTest(name=name):
                # no base mesh.smd body: the trace mesh is exactly the box
                out,_=self.run_compiler('$modelname "test/model.rmdl"\n$sequence idle "box.smd"\n'+base+extra,target='s3',name='bvh_'+name)
                data=out.read_bytes(); block=struct.unpack_from('<i',data,0x214)[0]
                hull=struct.unpack_from('<6f',data,0x6C)
                if roles is None:
                    self.assertEqual(block,0); self.assertEqual(struct.unpack_from('<2h',data,0x218),(0,0))
                    self.assertEqual(struct.unpack_from('<6f',data,0x1F0),hull)
                    continue
                self.assertEqual(block%64,0)
                parsed=bvh54.from_model(out,strict=True)
                self.assertEqual((parsed['hull'],parsed['trace']),roles)
                self.assertEqual([e['role'] for e in parsed['entries']],kinds)
                self.assertEqual(parsed['bounds'],tuple([min(x,0.0) for x in hull[:3]]+[max(x,0.0) for x in hull[3:]]))
                for e in parsed['entries']:
                    self.assertEqual(e['problems'],[]); self.assertEqual(len(e['triangles']),12)
                    volume=sum((a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6 for a,b,c in e['triangles'])
                    # 4 x 3 x 4; as retail, hulls wind clockwise from outside, trace meshes
                    # counter-clockwise (matched triangle by triangle in the S3 round trips)
                    self.assertAlmostEqual(volume,48 if e['role']=='trace' else -48,places=2)

    def test_bvh_pages_and_float_vertices(self):
        import bvh54
        from compare_bvh54 import compare
        # a 40 x 40 grid of separate quads: 6,400 render vertices, so later leaves start
        # on 1024-vertex pages (the in-game step test found a plain vertex number there wrong)
        tris=[]
        for i in range(40):
            for j in range(40):
                x,y=i*2.0,j*2.0
                quad=[(x,y,0),(x+1.5,y,0),(x+1.5,y+1.5,(i+j)%3),(x,y+1.5,0)]
                for a,b,c in ((0,1,2),(0,2,3)):
                    tris.append(('mat',[(quad[k],(0,0,1),(0,0),[(0,1.0)]) for k in (a,b,c)]))
        write_smd(self.work/'grid.smd',self.bones,self.frames,tris)
        out,_=self.run_compiler('$modelname "test/grid.rmdl"\n$staticprop\n$body body "grid.smd"\n$sequence idle "grid.smd"\n',target='s3',name='grid')
        parsed=bvh54.from_model(out,strict=True)
        (entry,)=parsed['entries']
        self.assertTrue(entry['packed']); self.assertEqual(entry['problems'],[])
        self.assertEqual(len(entry['triangles']),3200)
        data=out.read_bytes(); block=struct.unpack_from('<i',data,0x214)[0]
        packed,nodes,verts,leaves=struct.unpack_from('<4i',data,block+16)
        pages={struct.unpack_from('<I',data,block+leaves+4*k)[0]>>16 for k in range((nodes-leaves)//4)}
        self.assertTrue(max(pages)>0)
        self.assertEqual(compare(out,out)['issues'],[])  # the rule check: trace = render triangles
        # a model too large for packed vertices uses float vertices (type 4)
        write_smd(self.work/'big.smd',self.bones,self.frames,self.box_tris((-600,-600,0),(600,600,1200)))
        big,_=self.run_compiler('$modelname "test/big.rmdl"\n$staticprop\n$body body "big.smd"\n$sequence idle "big.smd"\n',target='s3',name='big')
        (entry,)=bvh54.from_model(big,strict=True)['entries']
        self.assertFalse(entry['packed']); self.assertEqual(entry['problems'],[])
        self.assertEqual({bvh54.FLOAT_TRIS}&set(entry['types']),{bvh54.FLOAT_TRIS})
        corners={p for t in entry['triangles'] for p in t}
        self.assertEqual(corners,{(x,y,z) for x in (-600.,600.) for y in (-600.,600.) for z in (0.,1200.)})

    def test_bvh_quads_and_lists(self):
        import bvh54
        from compare_bvh54 import compare
        # a box: six exact parallelograms -> one quad leaf, one stored vertex per corner
        write_smd(self.work/'box.smd',self.bones,self.frames,self.box_tris((-1,2,0),(3,5,4)))
        out,_=self.run_compiler('$modelname "test/q.rmdl"\n$staticprop\n$body body "box.smd"\n$sequence idle "box.smd"\n',target='s3',name='quads')
        (entry,)=bvh54.from_model(out,strict=True)['entries']
        self.assertEqual(entry['problems'],[])
        self.assertEqual(entry['types'].get(bvh54.PACKED_QUADS),1)
        self.assertEqual((len(entry['quads']),len(entry['plain']),len(entry['vertices'])),(6,0,8))
        # a flat square and a bent one: the bent pair is no parallelogram and stays two
        # triangles, so the leaf is a list of a quad leaf and a triangle leaf
        tris=[]
        for quad in ([(0,0,0),(2,0,0),(2,2,0),(0,2,0)],[(4,0,0),(6,0,0),(6,2,1),(4,2,0)]):
            for a,b,c in ((0,1,2),(0,2,3)):
                tris.append(('mat',[(quad[k],(0,0,1),(0,0),[(0,1.0)]) for k in (a,b,c)]))
        write_smd(self.work/'mixed.smd',self.bones,self.frames,tris)
        out,_=self.run_compiler('$modelname "test/m.rmdl"\n$staticprop\n$body body "mixed.smd"\n$sequence idle "mixed.smd"\n',target='s3',name='mixed')
        (entry,)=bvh54.from_model(out,strict=True)['entries']
        self.assertEqual(entry['problems'],[])
        self.assertEqual(entry['types'].get(bvh54.LIST),1)
        self.assertEqual((len(entry['quads']),len(entry['plain'])),(1,2))
        self.assertEqual(compare(out,out)['issues'],[])  # the trace still equals the render triangles

    def test_keyvalues_retail_form(self):
        import bvh54
        def kv(path):
            data=path.read_bytes(); i,n=struct.unpack_from('<2i',data,0x140); return data[i:i+n]
        # every surveyed S0-S3 model: compact text, a prop_data base, two trailing NULs
        out,_=self.run_compiler(name='kv_default')
        self.assertEqual(kv(out),b'mdlkeyvalue{prop_data{base ""}}\n\0\0')
        out,_=self.run_compiler(self.qc+'$keyvalues { prop_data { "base" "Metal.Small" } }\n',name='kv_base')
        self.assertEqual(kv(out),b'mdlkeyvalue{prop_data{base "Metal.Small"}}\n\0\0')
        # other keys keep the compact form, and allowstatic still gives the trace mesh
        out,_=self.run_compiler(self.qc+'$keyvalues { prop_data { "base" "Wooden.Small" "allowstatic" "1" } }\n',
                                target='s3',name='kv_allow')
        self.assertEqual(kv(out),b'mdlkeyvalue{prop_data{base "Wooden.Small" allowstatic "1"}}\n\0\0')
        self.assertEqual(bvh54.from_model(out)['trace'],0)

    def test_reference_pose_sequences(self):
        from pack54 import SequenceAsset
        qc=self.qc+'$sequence "ragdoll" {\n  referencepose\n  activity "ACT_DIERAGDOLL" 1\n}\n'
        plain,_=self.run_compiler(qc,target='s3',name='refpose')
        model=Model(plain,'s3')
        ragdoll=next(s for s in model.sequences if s['name']=='ragdoll')
        # retail's form: no counted blends, a 1x1 grid, and one sequence-relative entry
        # pointing at its clip right after it ('@' + label, 30 fps, one frame)
        self.assertEqual(ragdoll['animations'],[])
        self.assertEqual(model.get('2i',ragdoll['offset']+0x44),(1,1))
        clip=ragdoll['reference_clip']; p=ragdoll['offset']
        self.assertEqual(clip,p+model.get('i',p+0x3C)+4)
        self.assertEqual((model.string(clip+model.get('i',clip+4)),model.get('f',clip+8),model.get('i',clip+16)),('@ragdoll',30.0,1))
        # the bind pose has no tracks (flag 0x20000 clear), its data offset 16-aligned
        self.assertEqual(model.get('i',clip+12)&0x20000,0)
        self.assertEqual((clip+model.get('i',clip+32))%16,0)
        self.assertEqual(model.reference_frames(ragdoll)[0][1][0],tuple(model.bones[1]['pos']))
        self.assertEqual(model.sequence_metadata(ragdoll)['activity'],'ACT_DIERAGDOLL')
        # a descriptor keeps the flags it is given (retail has both forms)
        self.assertEqual(ragdoll['flags']&0x80000,0)
        single,_=self.run_compiler(qc.replace('  referencepose\n','  referencepose\n  seqflags 524288\n'),target='s3',name='refpose_single')
        self.assertEqual(next(x for x in Model(single,'s3').sequences if x['name']=='ragdoll')['flags']&0x80000,0x80000)
        # a posed clip: given as the sequence's file, it has tracks and keeps its pose
        write_smd(self.work/'pose.smd',self.bones,[[((0,0,0),(0,0,0),(1,1,1)),((0,2,0),(0,0,1.5),(1,1,1))]]*2)
        posed,_=self.run_compiler(self.qc+'$sequence "ragdoll" {\n  referencepose\n  "pose.smd"\n}\n',target='s3',name='refpose_posed')
        m2=Model(posed,'s3'); seq=next(s for s in m2.sequences if s['name']=='ragdoll')
        self.assertTrue(m2.get('i',seq['reference_clip']+12)&0x20000)
        frames=m2.reference_frames(seq)
        self.assertEqual(len(frames),2)
        self.assertAlmostEqual(frames[1][1][1][2],1.5,places=3)
        self.assertAlmostEqual(frames[0][1][0][1],2.0,places=3)
        # runtime builds: the same inline clip; the inserted `ref` gets a bind-pose clip
        # too; the sequence asset carries the clip as a counted blend
        out,_=self.run_compiler(qc,target='s3',name='refpose_ext',extra=['--external-assets'])
        model=Model(out,'s3'); rig=Model(out.with_suffix('.rrig'),'s3')
        names=[s['name'] for s in model.sequences]
        self.assertEqual(names[0],'ref'); self.assertEqual(model.sequences[0]['animations'],[])
        ref=model.sequences[0]
        self.assertEqual(model.string(ref['reference_clip']+model.get('i',ref['reference_clip']+4)),'@ref')
        index=names.index('ragdoll')
        self.assertEqual(model.sequences[index]['animations'],[])
        self.assertIsNotNone(model.sequences[index]['reference_clip'])
        asset=SequenceAsset(out.with_suffix('.seq%d.rseq'%index),rig)
        (seq,)=asset.sequences
        self.assertEqual([asset.get('i',d+16) for d in seq['animations']],[1])
        self.assertEqual(asset.sequence_metadata(seq)['activity'],'ACT_DIERAGDOLL')
        with self.assertRaises(AssertionError):  # one clip file at most
            self.run_compiler(self.qc+'$sequence "bad" {\n  referencepose\n  "mesh.smd" "pose.smd"\n}\n',name='refpose_bad',ok=True)

    def test_bodygroups_round_trip(self):
        from decompile54 import decompile
        from roundtrip54 import compare_extras
        tris=[('test/sight',[(p,(0,0,1),uv,[(1,1.0)]) for p,uv in [((0,0,4),(0,0)),((1,0,4),(1,0)),((0,1,4),(0,1))]])]
        write_smd(self.work/'sight.smd',self.bones,self.frames,tris)
        qc=self.qc.replace('$sequence idle','$bodygroup "sight"\n{\n  blank\n  studio "sight.smd"\n}\n$sequence idle')
        out,_=self.run_compiler(qc,target='s3',name='bg')
        m=Model(out,'s3')
        self.assertEqual([(bp['name'],[len(md['meshes']) for md in bp['models']]) for bp in m.bodyparts],[('body',[1]),('sight',[0,1])])
        source=decompile(out,self.work/'bg_src','s3'); text=source.read_text()
        self.assertIn('$bodygroup "sight"\n{\n  blank\n  studio "part1_model1_lod0.dmx"\n}',text)
        self.assertIn('$body "body" "part0_model0_lod0.dmx"',text)
        q=source.with_name('rebuilt.qc'); q.write_text(text); rebuilt=source.with_name('rebuilt.rmdl')
        run=subprocess.run([str(self.compiler),'--target','s3','-quiet','-o',str(rebuilt),str(q)],capture_output=True,text=True,timeout=40)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(compare_extras(out,rebuilt,'s3')['issues'],[])
        # a flattened rebuild (every model its own always-on part) is caught
        flat=text.replace('$bodygroup "sight"\n{\n  blank\n  studio "part1_model1_lod0.dmx"\n}','$body "sight" "part1_model1_lod0.dmx"')
        q.write_text(flat)
        run=subprocess.run([str(self.compiler),'--target','s3','-quiet','-o',str(rebuilt),str(q)],capture_output=True,text=True,timeout=40)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(compare_extras(out,rebuilt,'s3')['issues'],['body parts differ'])

    def test_track_axes_use_their_own_offset_slots(self):
        # A position track whose x axis is absent still keeps y at slot +2 and z at +3
        # (retail drone_EMP's def_c_base); reading them as consecutive streams swapped z
        # for y and posed the imported drone 6.8 inches off in R5R.
        frames=[[((0,0,0),(0,0,0),(1,1,1)),((f*.25,2+f*.125,f*-.5),(0,0,0),(1,1,1))] for f in range(5)]
        write_smd(self.work/'move.smd',self.bones,frames)
        out,_=self.run_compiler(self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "move.smd"'),target='s3',name='axes')
        m=Model(out,'s3'); desc=m.sequences[0]['animations'][0]
        before=m.animation(desc)
        data=desc+m.get('i',desc+32); size=((len(m.bones)+1)//2+1)&~1; record=data+size
        record+=m.get('H',record)&8191  # the root's record; the arm's follows
        self.assertEqual(m.get('H',record)>>13,7)
        ptr=record+2+4; field=m.get('H',ptr)
        raw=bytearray(m.data); struct.pack_into('<H',raw,ptr,(field&8191)|(3<<13))  # y and z only
        out.write_bytes(raw); after=Model(out,'s3').animation(desc)
        bind=m.bones[1]['pos']
        for f,(a,b) in enumerate(zip(before,after)):
            self.assertAlmostEqual(b[1][0][0],bind[0],places=5)
            self.assertAlmostEqual(b[1][0][1],a[1][0][1],places=5)
            self.assertAlmostEqual(b[1][0][2],a[1][0][2],places=5)
        self.assertNotAlmostEqual(after[4][1][0][1],after[4][1][0][2],places=2)

    def test_section_frames_and_standalone_frame_movement_flag(self):
        from decompile54 import decompile
        frames=[[((f*.1,0,0),(0,0,0),(1,1,1)),((0,0,2),(0,f*.001,0),(1,1,1))] for f in range(100)]
        write_smd(self.work/'long.smd',self.bones,frames)
        base=self.qc+'$animation long "long.smd" %s\n$sequence walk long\n'
        def sections(option,name):
            out,_=self.run_compiler(base%option,target='s3',name=name,extra=['--external-assets'])
            m=Model(out,'s3'); return out,m,m.get('i',m.sequences[-1]['animations'][0]+0x30)
        # retail's rule: (frames + 32) // 64 equal sections, whole up to 96 frames
        self.assertEqual(sections('','sf_default')[2],50)
        for count,expected,movement in ((96,0,48),(97,49,49),(160,54,54)):
            clip=[[((f*.1,0,0),(0,0,0),(1,1,1)),((0,0,2),(0,f*.001,0),(1,1,1))] for f in range(count)]
            write_smd(self.work/f'clip{count}.smd',self.bones,clip)
            out,_=self.run_compiler(self.qc+f'$animation c{count} "clip{count}.smd" rm\n$sequence s{count} c{count}\n',target='s3',name=f'sf{count}')
            m=Model(out,'s3'); desc=m.sequences[-1]['animations'][0]
            self.assertEqual((m.get('i',desc+0x30),m.frame_movement(desc)['section_frames']),(expected,movement))
        self.assertEqual(sections('sectionframes 0','sf_none')[2],0)
        self.assertEqual(sections('sectionframes 50','sf_fifty')[2],50)
        out,m,_=sections('sectionframes 50 rm','sf_moving')
        frames_back=m.animation(m.sequences[-1]['animations'][0])
        self.assertAlmostEqual(frames_back[99][1][1][1],.099,places=3)
        # the exported clip keeps its sections; a standalone sequence whose clips have
        # frame movement carries 0x40000 (all 4,249 retail assets), the model's does not
        text=decompile(out,self.work/'sf_src','s3').read_text()
        self.assertIn('sectionframes 50',text)
        index=len(m.sequences)-1
        self.assertEqual(m.sequences[index]['flags']&0x40000,0)
        rseq=out.with_suffix('.seq%d.rseq'%index).read_bytes()
        self.assertEqual(struct.unpack_from('<i',rseq,12)[0]&0x40000,0x40000)
        rseq=out.with_suffix('.seq1.rseq').read_bytes()  # idle: no frame movement
        self.assertEqual(struct.unpack_from('<i',rseq,12)[0]&0x40000,0)
        self.run_compiler(base%'sectionframes -1',target='s3',name='sf_bad',ok=False)

    def test_illumination_attachment_index(self):
        from decompile54 import decompile
        qc=self.qc+'$attachment "tip" "arm" 0 0 1\n$attachment "__illumPosition" "root" 0 0 2\n'
        out,_=self.run_compiler(qc,target='s3',name='illum')
        self.assertEqual(Model(out,'s3').get('i',0x190),2)  # its index + 1
        none,_=self.run_compiler(target='s3',name='illum_none')
        self.assertEqual(Model(none,'s3').get('i',0x190),0)
        # retail's stale values (ten R-301 models) are kept verbatim through export
        stale,_=self.run_compiler(qc+'$illumpositionattachment 10\n',target='s3',name='illum_stale')
        self.assertEqual(Model(stale,'s3').get('i',0x190),10)
        text=decompile(stale,self.work/'illum_src','s3').read_text()
        self.assertIn('$illumpositionattachment 10',text)
        self.assertNotIn('$illumpositionattachment',decompile(out,self.work/'illum_src2','s3').read_text())

    def test_retail_compatibility_fields_round_trip(self):
        # Fields measured on all 581 S3 models, written by rule or kept verbatim by the
        # decompiler; each survives decompile and rebuild exactly.
        from decompile54 import decompile
        from roundtrip54 import compare_extras
        tris=[('test/other',[(p,(0,0,1),uv,[(0,.5),(1,.5)]) for p,uv in [((0,0,4),(0,0)),((1,0,4),(1,0)),((0,1,4),(0,1))]])]
        write_smd(self.work/'second.smd',self.bones,self.frames,tris)
        table=self.work/'surfaceproperties.rson'
        table.write_text('// comment\ndefault:\n{\n\tid: 0\n}\nmetal:\n{\n\tid: 7\n\tdensity: 2\n}\n')
        qc=('$modelname "test/compat.rmdl"\n$origin 0 0 0 -90\n'
            '$skinfamilies\n{\n  { "test/material" "test/other" "test/alt" }\n  "re\\color" { "test/alt" "test/other" "test/alt" }\n}\n'
            '$body body "mesh.smd"\n$body second "second.smd"\n$sequence idle "mesh.smd"\n'
            '$surfaceprop "metal"\n$headerflags 0x8a\n$complexweights\n$materialtype "test/other" sknc\n'
            '$materialguid "test/material" 0x1122334455667788\n$boneflags "arm" 0x100520\n')
        out,_=self.run_compiler(qc,target='s3',name='compat',extra=['--surface-properties',str(table)])
        m=Model(out,'s3')
        self.assertEqual([x['name'] for x in m.materials],['test/material','test/other','test/alt'])
        self.assertEqual(m.skins(),dict(families=[[0,1,2],[2,1,2]],names=['re\\color']))
        self.assertEqual(m.get('i',0x9C)&0x408a,0x408a)                     # material bits + complex layout
        self.assertEqual(m.materials[0]['guid'],0x1122334455667788)
        self.assertEqual(m.data[m.get('i',0xCC)+1],5)                       # sknc
        self.assertEqual((m.string(m.get('i',0x13C)),m.get('i',0x180)),('metal',7))
        base=m.get('i',0xA4)
        self.assertEqual([m.get('i',base+0xB8*k+0xAC) for k in range(2)],[7,7])   # bone surface ids
        self.assertEqual(m.bones[1]['flags'],0x100520)                      # verbatim
        self.assertEqual([m.get('i',base+0xB8*k+0xB4) for k in range(2)],[0,0])  # no BVH: 0
        self.assertEqual(m.get('i',0x100),0)                                # an empty node table at 0
        self.assertEqual(m.get('i',0x10C),m.get('i',0xF0))                  # flex descriptors at body parts
        self.assertEqual(m.get('i',0x1EC),len(m.data))                      # follower table at the end
        text=decompile(out,self.work/'compat_src','s3').read_text()
        for line in ('$surfaceprop "metal"','$surfacepropid "metal" 7','$headerflags 0x8a','$complexweights',
                     '$materialtype "test/other" sknc','$materialguid "test/material" 0x1122334455667788',
                     '$boneflags "arm" 0x100520','"re\\color" {'):
            self.assertIn(line,text)
        q=self.work/'compat_src'/'rebuilt.qc'; q.write_text(text); rebuilt=q.with_suffix('.rmdl')
        run=subprocess.run([str(self.compiler),'--target','s3','-quiet','-o',str(rebuilt),str(q)],capture_output=True,text=True,timeout=40)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(compare_extras(out,rebuilt,'s3')['issues'],[])
        self.assertEqual(Model(rebuilt,'s3').get('i',0x158),0)
        self.assertNotIn('$externalassets',text)
        # $externalassets: the external-rig sentinel and the rig/sequence assets, from the QC
        ext,_=self.run_compiler(qc+'$externalassets\n',target='s3',name='compat_ext')
        self.assertEqual(Model(ext,'s3').get('i',0x158),-1)
        self.assertTrue(ext.with_suffix('.rrig').exists() and ext.with_suffix('.seq0.rseq').exists())
        text=decompile(ext,self.work/'compat_ext_src','s3').read_text()
        self.assertIn('$externalassets',text)
        q=self.work/'compat_ext_src'/'rebuilt.qc'; q.write_text(text); rebuilt=q.with_suffix('.rmdl')
        run=subprocess.run([str(self.compiler),'--target','s3','-quiet','-o',str(rebuilt),str(q)],capture_output=True,text=True,timeout=40)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(Model(rebuilt,'s3').get('i',0x158),-1)
        self.assertEqual(compare_extras(ext,rebuilt,'s3')['issues'],[])
        # a static prop's bone has every usage bit through 0x800000
        prop,_=self.run_compiler(self.qc+'$staticprop\n',target='s3',name='compat_prop')
        self.assertEqual(Model(prop,'s3').bones[0]['flags']&0xFFFF00,0xFFFF00)
        # the first family lists every texture slot: a mesh material missing from it fails
        self.run_compiler(qc.replace('{ "test/material" "test/other" "test/alt" }','{ "test/material" "test/alt" "test/alt" }')
                          .replace('"re\\color" { "test/alt" "test/other" "test/alt" }','"re\\color" { "test/alt" "test/alt" "test/alt" }'),
                          target='s3',name='compat_bad',ok=False)

    def test_hitboxes_and_keyvalues_round_trip(self):
        from decompile54 import decompile
        from roundtrip54 import compare_extras
        qc=self.qc+('$hboxset "default"\n$hbox 3 "root" -1 -2 -3 4 5 6 "body" 1 "hitdata"\n'
                    '$hbox 0 "arm" 0 0 0 1 1 1\n$keyvalues { prop_data { "base" "Glass.Window" } }\n')
        out,_=self.run_compiler(qc,target='s3',name='hb')
        source=decompile(out,self.work/'hb_src','s3')
        text=source.read_text()
        self.assertIn('$hbox 3 "root" -1 -2 -3 4 5 6 "body" 1 "hitdata"',text)
        self.assertIn('"base" "Glass.Window"',text)
        def build(qc_text,name):  # beside the exported meshes it refers to
            q=source.with_name(name+'.qc'); q.write_text(qc_text); target=source.with_name(name+'.rmdl')
            run=subprocess.run([str(self.compiler),'--target','s3','-quiet','-o',str(target),str(q)],capture_output=True,text=True,timeout=40)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr); return target
        self.assertEqual(compare_extras(out,build(text,'hb_rebuilt'),'s3')['issues'],[])
        # the comparison notices a changed keyvalue and a changed box
        changed=build(text.replace('Glass.Window','Glass.Pane').replace('-1 -2 -3 4 5 6','-1 -2 -3 4 5 7'),'hb_changed')
        self.assertEqual(len(compare_extras(out,changed,'s3')['issues']),2)

    def test_rui_panels(self):
        from decompile53 import ui_panel_hash
        from decompile54 import decompile
        from roundtrip54 import compare_extras
        panel=('$uipanel "models/test/screen_rui"\n{\n\tparent "arm"\n'
               '\tvertex 0 0 0 0\n\tvertex 0 2 0 0\n\tvertex 0 2 1 0\n\tvertex 0 0 1 0\n'
               '\tface 0 1 2\n\tface 0 2 3\n'
               '\tbounds 0 2 2 0 0 0 1 1\n\tbounds 0 2 0 0 0 1 1 1\n%s}\n')
        # derived masks (the 4x4 grid cells each face's bounds polygon overlaps: the
        # second face misses two) and, with no ccw face, a count equal to the face count
        out,_=self.run_compiler(self.qc+panel%'',target='s3',name='rui')
        (p,)=Model(out,'s3').ui_panels()
        self.assertEqual(p['hash'],ui_panel_hash('models/test/screen_rui'))
        self.assertEqual([Model(out,'s3').bones[k]['name'] for k in p['parents']],['arm'])
        self.assertEqual((len(p['vertices']),p['faces'],p['masks'],p['mask_count']),(4,[(0,1,2),(0,2,3)],[0xFFFF,0xFFF3],2))
        self.assertEqual(p['bounds'][1],(0,2,0,0,0,1,1,1))
        # retail mask shapes: a quadrant, an edge-touching cell and a triangle's cells
        self.assertEqual(Model.ui_face_mask((1,.5,.5,1,0,0,.5,.5)),0x00cc)
        self.assertEqual(Model.ui_face_mask((.25,.25,0,0,.5,.25,.25,.5)),0x0010)
        self.assertEqual(Model.ui_face_mask((.748,.8262,.818,.818,.0539,.4958,.001,.001)),0x008c)
        # TF2's ccw faces: written after the others, the count is the number of others,
        # and each face keeps its own bounds and derived mask
        tri=('$uipanel "models/test/tri_rui"\n{\n\tparent "arm"\n'
             '\tvertex 0 0 0 0\n\tvertex 0 1 0 0\n\tvertex 0 1 1 0\n'
             '\tface 0 1 2 ccw\n\tface 2 1 0\n\tface 1 2 0 ccw\n\tface 0 2 1\n'
             '\tbounds 0 .5 .5 .5 0 0 .5 .5\n\tbounds .5 1 1 1 .5 .5 1 1\n'
             '\tbounds .5 1 1 1 0 0 .5 .5\n\tbounds 0 .5 .5 .5 .5 .5 1 1\n}\n')
        out,_=self.run_compiler(self.qc+tri,target='s3',name='rui_ccw')
        (p,)=Model(out,'s3').ui_panels()
        self.assertEqual((p['faces'],p['mask_count']),([(2,1,0),(0,2,1),(0,1,2),(1,2,0)],2))
        self.assertEqual(p['masks'],[0x8c00,0x2300,0x0023,0x008c])
        self.assertEqual([Model.ui_face_mask(b) for b in p['bounds']],p['masks'])
        source=decompile(out,self.work/'rui_ccw_src','s3'); text=source.read_text()
        self.assertEqual((text.count(' ccw\n'),'facemask' in text,'maskcount' in text),(2,False,False))
        q=source.with_name('rebuilt.qc'); q.write_text(text); rebuilt=source.with_name('rebuilt.rmdl')
        run=subprocess.run([str(self.compiler),'--target','s3','-quiet','-o',str(rebuilt),str(q)],capture_output=True,text=True,timeout=40)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(compare_extras(out,rebuilt,'s3')['issues'],[])
        self.assertEqual(Model(rebuilt,'s3').ui_panels(),Model(out,'s3').ui_panels())
        # the include-model index points at the panel table, as in every retail model
        data=out.read_bytes(); self.assertEqual(struct.unpack_from('<i',data,0x15C)[0],struct.unpack_from('<i',data,0x130)[0])
        # explicit masks and count, stored verbatim; exact decompile/rebuild
        out,_=self.run_compiler(self.qc+panel%'\tfacemask 0x00ff\n\tfacemask 0xff00\n\tmaskcount 1\n',target='s3',name='rui_masks')
        (p,)=Model(out,'s3').ui_panels()
        self.assertEqual((p['masks'],p['mask_count']),([0x00ff,0xff00],1))
        source=decompile(out,self.work/'rui_src','s3')
        q=source.with_name('rebuilt.qc'); q.write_text(source.read_text()); rebuilt=source.with_name('rebuilt.rmdl')
        run=subprocess.run([str(self.compiler),'--target','s3','-quiet','-o',str(rebuilt),str(q)],capture_output=True,text=True,timeout=40)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(compare_extras(out,rebuilt,'s3')['issues'],[])
        # explicit masks are written as given and kept by the decompiler
        self.assertIn('facemask 0x00ff',source.read_text())
        # ccw and an explicit count conflict; masks need one line per face
        self.run_compiler(self.qc+panel.replace('face 0 1 2','face 0 1 2 ccw')%'\tmaskcount 1\n',target='s3',name='rui_ccwcount',ok=False)
        self.run_compiler(self.qc+panel%'\tfacemask 0xffff\n',target='s3',name='rui_onemask',ok=False)

    def test_jiggle_bones(self):
        from decompile54 import decompile
        from roundtrip54 import compare_extras
        # procedural order (arm, root) differs from bone order; both rigid and flexible
        # bits, the v54 tip friction, a limit stored without its flag and a bone byte
        jiggle=('$jigglebone "arm"\n{\n\tis_rigid\n\t{\n\t}\n\tis_flexible\n\t{\n\t\tlength 12\n\t\ttip_mass 2\n'
                '\t\ttip_friction 0.3\n\t\tyaw_constraint -30 30\n\t\tstored_angle_limit 71.6197243913529\n\t}\n}\n'
                '$jigglebone "root"\n{\n\tis_rigid\n\t{\n\t\tlength 5\n\t}\n\thas_base_spring\n\t{\n\t\tstiffness 50\n'
                '\t\tleft_constraint -2 3\n\t}\n\tbone_byte 7\n}\n')
        for target in ('s0','s3'):
            out,_=self.run_compiler(self.qc+jiggle,target=target,name='jiggle_'+target)
            m=Model(out,target); data=out.read_bytes()
            nb,bi=struct.unpack_from('<2i',data,0xA0); end=bi+0xB8*nb
            self.assertEqual(struct.unpack_from('<3i',data,0x198),(2,end+2*0x7C,end+2*0x7C+2))
            self.assertEqual(data[end+2*0x7C:end+2*0x7C+4],bytes([1,0,1,0]))  # bone order, then slot per bone
            self.assertEqual(struct.unpack_from('<i',data,0xAC)[0],end+2*0x7C+2+nb)  # bone controllers: unpadded table end
            for bone,slot in ((1,0),(0,1)):
                self.assertEqual(struct.unpack_from('<2i',data,bi+0xB8*bone+0x98),(5,end+0x7C*slot-(bi+0xB8*bone)))
            arm,root=m.jiggle_bones()
            self.assertEqual((arm['bone'],arm['flags'],arm['bone_byte']),(1,0x07,1))
            self.assertAlmostEqual(arm['tipFriction'],.3,places=6); self.assertEqual(arm['length'],12)
            self.assertAlmostEqual(arm['angleLimit'],1.25,places=6); self.assertAlmostEqual(arm['maxYaw'],math.radians(30),places=6)
            self.assertEqual((root['bone'],root['flags'],root['bone_byte'],root['baseStiffness'],root['baseMaxLeft']),(0,0x42,7,50,3))
            source=decompile(out,self.work/('jiggle_src_'+target),target)
            rebuilt,_=self.run_compiler(source.read_text(),target=target,name='jiggle_rebuilt_'+target,extra=['-path',str(source.parent)])
            self.assertEqual(compare_extras(out,rebuilt,target)['issues'],[])
            # the linear bone table copies the bone records (a missing one crashed R5R)
            lb=struct.unpack_from('<i',data,0x194)[0]; h=struct.unpack_from('<7i',data,lb)
            self.assertEqual((h[0],h[1]),(nb,0x1C))
            self.assertEqual(struct.unpack_from('<2i',data,lb+h[1]),tuple(struct.unpack_from('<i',data,bi+0xB8*k+0x94)[0] for k in range(nb)))
        # an external rig keeps no procedures and no linear table, as retail rigs: the
        # jiggle bones' rig flags keep only 0x20 (a rig-side jiggle left R5R unposed)
        out,_=self.run_compiler(self.qc+jiggle,target='s3',name='jiggle_rig',extra=['--external-assets','--material-guid','test/material=123456789abcdef0'])
        rig=Model(out.with_suffix('.rrig'),'s3')
        self.assertEqual((rig.get('3i',0x198),rig.get('i',0x194)),((0,0,0),0))
        self.assertEqual([b['proctype'] for b in rig.bones],[0,0])
        self.assertTrue(all(b['flags']&~0x20==0 for b in rig.bones))
        self.assertEqual(len(Model(out,'s3').jiggle_bones()),2)
        # models without procedural bones keep zeros; byte-sized fields are checked
        out,_=self.run_compiler(name='no_jiggle')
        self.assertEqual(struct.unpack_from('<3i',out.read_bytes(),0x198),(0,0,0))
        self.run_compiler(self.qc+jiggle.replace('bone_byte 7','bone_byte 300'),name='jiggle_byte',ok=False)

    def test_phy_face_limit_fails_explicitly(self):
        # a 40-sided prism: its caps exceed the 32 vertices a native face can hold
        ring=[(math.cos(2*math.pi*k/40)*4,math.sin(2*math.pi*k/40)*4) for k in range(40)]
        tris=[]
        for k in range(40):
            a,b=ring[k],ring[(k+1)%40]
            for z0,z1 in ((0,0),(3,3)):
                tris.append(('phys',[((0,0,z0),(0,0,1),(0,0),[(0,1.0)]),((*a,z0),(0,0,1),(0,0),[(0,1.0)]),((*b,z1),(0,0,1),(0,0),[(0,1.0)])]))
            tris.append(('phys',[((*a,0),(0,0,1),(0,0),[(0,1.0)]),((*b,0),(0,0,1),(0,0),[(0,1.0)]),((*b,3),(0,0,1),(0,0),[(0,1.0)])]))
        write_smd(self.work/'prism.smd',self.bones,self.frames,tris)
        _,run=self.run_compiler(self.qc+'$collisionmodel "prism.smd" { $mass 5 }\n',ok=False)
        self.assertIn('Apex PHY allows 32',run.stdout)

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

    def test_native_frame_movement_extraction_roundtrip(self):
        frames=[[((f*.125,0,0),(0,0,0),(1,1,1)),self.frames[0][1]] for f in range(65)]
        write_smd(self.work/'move.smd',self.bones,frames)
        for target in PROFILES:
            for option in ('rm','rootmotion','framemovement','LX'):
                with self.subTest(target=target,option=option):
                    qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "move.smd" '+option)
                    out,_=self.run_compiler(qc,target=target,name=target+option)
                    m=Model(out,target); desc=m.sequences[0]['animations'][0]; fm=m.frame_movement(desc)
                    self.assertEqual(len(fm['samples']),65)
                    for f in (0,29,30,31,59,60,64):
                        self.assertAlmostEqual(fm['samples'][f][0],f*.125,delta=.001)
                        self.assertAlmostEqual(m.animation(desc)[f][0][0][0],0,delta=.001)
                    export=decompile(out,self.work/(target+option+'export'),target)
                    rebuilt,_=self.run_compiler(export.read_text(),target=target,name=target+option+'rebuilt',extra=['-path',str(export.parent)])
                    self.assertEqual(validate(rebuilt,target,out,animation_metadata=True)['differences'],[])

    def test_native_frame_yaw_delta_and_boundary_guards(self):
        frames=[[((0,0,0),(0,math.pi/2,f*.01),(1,1,1)),self.frames[0][1]] for f in range(32)]
        write_smd(self.work/'turn.smd',self.bones,frames)
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "turn.smd" rm')
        out,_=self.run_compiler(qc)
        m=Model(out,'s0');desc=m.sequences[0]['animations'][0];fm=m.frame_movement(desc)
        self.assertAlmostEqual(fm['samples'][-1][3],math.degrees(.31),delta=.005)
        p=desc+m.get('i',desc+0x1C);section=p+m.get('i',p+20);channel=m.get('H',section+6)
        guard=m._track(section+channel,30)*fm['scales'][3]
        self.assertAlmostEqual(guard,fm['samples'][30][3],delta=.00001)
        # Raw delta clips retain local deltas and carry a zero movement stream.
        out,_=self.run_compiler(qc.replace('$sequence idle "turn.smd" rm','$animation turn "turn.smd" rm delta\n$sequence idle turn'),name='delta')
        m=Model(out,'s0');fm=m.frame_movement(m.sequences[0]['animations'][0])
        self.assertTrue(all(all(x==0 for x in frame) for frame in fm['samples']))
        out,_=self.run_compiler(self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "mesh.smd" rm'),name='single')
        m=Model(out,'s0'); self.assertEqual(m.frame_movement(m.sequences[0]['animations'][0])['samples'],[(0.,0.,0.,0.)])

    def test_native_frame_text_track(self):
        (self.work/'track.txt').write_text('.01 .01 .01 .01\n1 2 3 4\n')
        out,_=self.run_compiler(self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "mesh.smd" fmtrack "track.txt"'))
        m=Model(out,'s0'); fm=m.frame_movement(m.sequences[0]['animations'][0])
        for x,y in zip(fm['samples'][0],(1,2,3,4)): self.assertAlmostEqual(x,y,delta=.001)

    def test_native_frame_stream_modes_and_malformed_input(self):
        # Three samples exercise polynomial t=0, .5, 1 and packed residuals.
        write_smd(self.work/'three.smd',self.bones,self.frames*3)
        for mode in range(20):
            extra=(mode-2)%6 if mode>=2 else 0; bits=0 if mode<8 else 2 if mode<14 else 4
            packet=bytes((mode,3))
            if mode==0: packet+=struct.pack('<3h',10,11,12)
            elif mode==1: packet+=struct.pack('<h2b',10,1,-1)
            else:
                packet+=struct.pack('<h'+'h'*extra,10,*([2]*extra))
                if bits: packet+=struct.pack('<H',(1<<bits) | (((1<<bits)-1)<<(2*bits)))
            payload=struct.pack('<4fi i4H',.001,.001,.001,.001,3,24,8,0,0,0)+packet
            (self.work/'track.fm54').write_bytes(b'FM54'+struct.pack('<I',3)+payload)
            qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "three.smd" fmstream "track.fm54"')
            out,_=self.run_compiler(qc,name=f'mode{mode}')
            m=Model(out,'s0'); fm=m.frame_movement(m.sequences[0]['animations'][0])
            if mode==0: expected=[.010,.011,.012]
            elif mode==1: expected=[.010,.011,.009]
            else:
                residual=[-((1<<bits)-1),2-((1<<bits)-1),(1<<bits)-1] if bits else [0,0,0]
                expected=[(10+sum(2*t**(i+1) for i in range(extra))+r)*.001 for t,r in zip((0,.5,1),residual)]
            for sample,value in zip(fm['samples'],expected): self.assertAlmostEqual(sample[0],value,delta=1e-6)
        for i,bad in enumerate((payload[:-1],payload[:32]+bytes((20,1))+payload[34:],payload[:32]+bytes((0,0))+payload[34:])):
            (self.work/'track.fm54').write_bytes(b'FM54'+struct.pack('<I',3)+bad)
            self.run_compiler(qc,name=f'badstream{i}',ok=False)
            fake=Model.__new__(Model); Reader.__init__(fake,struct.pack('<3ifi2i i',0,0,0,0x40000,3,0,0,52)+bytes(20)+bad)
            with self.assertRaises(ValueError): fake.frame_movement(0)

    def test_native_frame_delta_overflow_rejected(self):
        write_smd(self.work/'two.smd',self.bones,self.frames*2)
        payload=struct.pack('<4fii4H',.001,.001,.001,.001,2,24,8,0,0,0)+bytes((1,2))+struct.pack('<hbB',32767,1,0)
        (self.work/'overflow.fm54').write_bytes(b'FM54'+struct.pack('<I',2)+payload)
        self.run_compiler(self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "two.smd" fmstream "overflow.fm54"'),ok=False)
        m=Model.__new__(Model);Reader.__init__(m,payload)
        with self.assertRaisesRegex(ValueError,'overflow'):m._track(32,1)

    def test_native_frame_metadata_and_bounds(self):
        (self.work/'track.txt').write_text('.001 .001 .001 .001\n1 0 0 0\n')
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "mesh.smd" fmtrack "track.txt"')
        out,_=self.run_compiler(qc)
        (self.work/'track.txt').write_text('.001 .001 .001 .001\n1.1 0 0 0\n')
        changed,_=self.run_compiler(qc,name='changed')
        result=validate(changed,'s0',out,animation_metadata=True)
        self.assertIn('sequence 0 blend 0 frame movement',result['differences'])
        self.assertAlmostEqual(result['frame_movement_max_error']['position'],.1,delta=.001)
        m=Model(out,'s0');d=m.sequences[0]['animations'][0];p=d+m.get('i',d+0x1C)
        original=out.read_bytes()
        for offset,fmt,value in ((d+12,'i',0),(p,'f',float('nan')),(p,'f',-1.),(p+16,'i',0),(p+20,'i',-1),(p+24,'H',4)):
            data=bytearray(original);struct.pack_into('<'+fmt,data,offset,value);out.write_bytes(data)
            with self.assertRaises(ValueError): validate(out,'s0')
        out.write_bytes(original)

    def test_native_frame_quantization_and_conflicts_rejected(self):
        (self.work/'track.txt').write_text('1 1 1 1\n.1 0 0 0\n')
        qc=self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "mesh.smd" fmtrack "track.txt"')
        self.run_compiler(qc,ok=False)
        (self.work/'track.txt').write_text('.001 .001 .001 .001\n1 0 0 0\n')
        for i,changed in enumerate(('$legacymovement\n'+qc,qc.replace('fmtrack','rm fmtrack'),qc.replace('fmtrack','LX fmtrack'),qc.replace('fmtrack','fmtrack "track.txt" fmtrack'))):
            self.run_compiler(changed,name=f'conflict{i}',ok=False)
        self.run_compiler('$legacymovement\n'+self.qc.replace('$sequence idle "mesh.smd"','$sequence idle "mesh.smd" rm'),name='legacyrm',ok=False)

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
                external,_=self.run_compiler(qc,target=target,name=target+'assets',extra=['--external-assets'])
                rig=Model(external.with_suffix('.rrig'),target)
                asset=SequenceAsset(external.with_suffix('.seq1.rseq'),rig)
                self.assertEqual(compare_animation_metadata(asset,m),[])
                self.assertEqual(rig.pose_parameters(),m.pose_parameters())
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

    def test_reference_descriptor_exports_as_reference_pose(self):
        out,_=self.run_compiler(); m=Model(out,'s0'); data=bytearray(out.read_bytes())
        p=m.sequences[0]['offset']; struct.pack_into('<i',data,p+0x38,0); out.write_bytes(data)
        reference=m; m=Model(out,'s0'); self.assertEqual(m.sequence_metadata(m.sequences[0])['grid'],(1,1))
        self.assertIn('sequence 0 blend count',compare_animation_metadata(m,reference))
        # it exports as a referencepose sequence and rebuilds as a descriptor without a clip
        source=decompile(out,self.work/'refexport','s0')
        self.assertIn('  referencepose',source.read_text())
        rebuilt,_=self.run_compiler(source.read_text(),target='s0',name='refrebuilt',extra=['-path',str(source.parent)])
        r=Model(rebuilt,'s0'); self.assertEqual(r.sequences[0]['animations'],[])
        self.assertEqual(r.sequence_metadata(r.sequences[0])['grid'],(1,1))

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

    def test_native_vg_shader_flags_palette_and_allocation_sizes(self):
        for target in ('s2','s3'):
            out,_=self.run_compiler(target=target,name=target,extra=['--packed-positions'])
            model=Model(out,target); vg=Reader(out.with_suffix('.vg').read_bytes())
            mesh=vg.get('Q',0x20)
            self.assertEqual(vg.get('Q',mesh)&0xFFF,0xA42)
            auxiliary=vg.get('Q',0x60); auxiliary_count=vg.get('Q',0x68)
            self.assertEqual(auxiliary_count,len(model.meshes))
            self.assertEqual(vg.data[auxiliary:auxiliary+48*auxiliary_count],bytes(48*auxiliary_count))
            palette=vg.get('Q',0x10); count=vg.get('Q',0x18)
            self.assertEqual(vg.data[palette:palette+count],bytes(range(len(model.bones))))
            self.assertTrue(all(model.get('i',o)>0 for o in (0x1D0,0x1D4)))
            # retail's component offsets for VG models: VTX -1, VVD after VTX, VVC after
            # both (0 without vertex colour), from the allocation sizes at 0x1D0
            vtx,vvd,vvc=model.get('3i',0x1D0)
            self.assertEqual(model.get('3i',0x1C0),(-1,vtx,vtx+vvd if vvc else 0))
            self.assertFalse(out.with_suffix('.vvd').exists())
            self.assertFalse(out.with_suffix('.dx11.vtx').exists())
            expected=Model(self.run_compiler(target=target,name=target+'float')[0],target)
            self.assertEqual(validate(out,target,expected.path)['differences'],[])
        _,run=self.run_compiler(extra=['--packed-positions'],ok=False)
        self.assertIn('s2',run.stdout)
        bad=[('test/material',[(tuple(x+.0003 for x in v[0]),v[1],v[2],v[3]) for v in self.tris[0][1]])]
        write_smd(self.work/'mesh.smd',self.bones,self.frames,bad)
        _,run=self.run_compiler(target='s3',extra=['--packed-positions'],ok=False,name='quantized')
        self.assertIn('error budget',run.stdout)

    def test_float_skinned_vertex_color_material_layout(self):
        # Native SKNC opaque debug VS requires float positions, packed weights
        # and COLOR. Keep non-grid coordinates to rule out position snapping.
        triangles=[('test/material',[(tuple(x+.0003 for x in v[0]),v[1],v[2],v[3])
                                    for v in self.tris[0][1]])]
        write_smd(self.work/'mesh.smd',self.bones,self.frames,triangles)
        out,_=self.run_compiler(self.qc+'\n$usevertexcolor\n',target='s3',
                                extra=['--material-type','test/material=sknc'])
        model=Model(out,'s3');vg=Reader(out.with_suffix('.vg').read_bytes())
        flags=vg.get('Q',vg.get('Q',0x20))
        self.assertEqual(flags&0x40000011,0x11)
        self.assertEqual(flags&0x7000,0x5000)
        self.assertEqual(vg.get('I',vg.get('Q',0x20)+12),36)
        self.assertEqual(model.get('B',model.get('i',0xCC)),5)
        self.assertTrue(model.get('I',0x9C)&0x1000000)
        vertices=model.render()[0][0]['triangles'][0]
        for actual in vertices:
            self.assertEqual(actual['color'],(255,255,255,255))
        for actual,expected in zip(sorted(v['pos'] for v in vertices),sorted(v[0] for v in triangles[0][1])):
            self.assertTrue(all(abs(a-b)<0.0001 for a,b in zip(actual,expected)))
        qc=decompile(out,self.work/'float-color-export','s3')
        rebuilt=self.work/'float-color-rebuilt.rmdl'
        run=subprocess.run([str(self.compiler),'--target','s3','-quiet','-o',str(rebuilt),str(qc)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertEqual(validate(rebuilt,'s3',out)['differences'],[])

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
