"""Independent boundary/protocol and result checks for the R5R harness."""
from pathlib import Path
import json
import socket
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from ingame54 import fields, NetConsole, summarize, summarize_visual, write_probe


class Runtime54(unittest.TestCase):
    def test_sdk_wire_format(self):
        class Capture:
            def sendall(self,data): self.data=data
        console=NetConsole.__new__(NetConsole); console.sock=Capture()
        with patch('ingame54.time.time_ns',return_value=1): console.command('echo x')
        # Unencrypted envelope, requestType=EXECCOMMAND, requestMsg, empty value.
        self.assertEqual(console.sock.data,bytes.fromhex('6e6f4352000000180a04080110012210180022046563686f2a066563686f2078'))
        self.assertEqual(fields(bytes.fromhex('18002202786f2a0131')),{3:0,4:b'xo',5:b'1'})
        for bad in (b'\x80',b'\x1a\x05x',b'\x0f'):
            with self.assertRaises(ValueError): fields(bad)

    def test_receive_keeps_partial_frame_on_timeout(self):
        envelope=bytes.fromhex('0a0408011001220b1801220568656c6c6f2a00')
        wire=struct.pack('!II',0x6e6f4352,len(envelope))+envelope
        class Partial:
            def __init__(self): self.chunks=iter([wire[:2],socket.timeout(),wire[2:7],wire[7:]])
            def recv(self,count):
                value=next(self.chunks)
                if isinstance(value,Exception): raise value
                return value
        console=NetConsole.__new__(NetConsole); console.sock=Partial(); console.buffer=bytearray()
        with self.assertRaises(socket.timeout): console.receive()
        self.assertEqual(console.receive(),{3:1,4:b'hello',5:b''})

    def test_runtime_summary_requires_every_spawn_sequence_and_sample(self):
        models=[{'path':'mdl/test.rmdl','labels':['walk']}]
        self.assertFalse(summarize('R5C_DONE\n',models)['passed'])
        log='R5C_SPAWN 0\nR5C_SEQUENCE 0 0 3 2.0\n'
        for i in range(5): log+=f'R5C_SAMPLE 0 0 {i*.4} {i*.2} {i} 0 0 0\n'
        log+='R5C_DONE\n'
        report=summarize(log,models)
        self.assertTrue(report['passed']); self.assertEqual(len(report['samples']),5)
        self.assertFalse(summarize(log.replace(' 3 2.0',' -1 2.0'),models)['passed'])
        self.assertFalse(summarize(log.replace('0.4 0.2 1','nan 0.2 1'),models)['passed'])

    def test_probe_contains_literal_assets_and_all_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_probe(tmp,[{'path':'mdl/test.rmdl','labels':['idle','walk'],'sequences':['animseq/test/idle.rseq','animseq/test/walk.rseq']}])
            script=(Path(tmp)/'mods/r5c_compiler_test/scripts/vscripts/r5c_probe.nut').read_text()
            self.assertIn('asset model = $"mdl/test.rmdl"',script)
            # one helper call per sequence (Squirrel limits a function's locals)
            self.assertIn('R5C_ProbeSequence( prop, 0, 1, "walk", origin, false )',script)
            self.assertEqual(script.count('R5C_ProbeSequence( prop,'),2)
            self.assertEqual(script.count('prop.LookupSequence'),1)
            self.assertNotIn('continue',script)
            self.assertIn('R5C_DONE\\n',script)
            with self.assertRaises(ValueError):
                write_probe(tmp,[{'path':'mdl/"escape.rmdl','labels':[]}])

    def test_animated_sequence_requires_duration_and_cycle_advance(self):
        models=[dict(path='mdl/test.rmdl',labels=['walk'],animated_sequences=[0])]
        def log(duration,cycles):
            return ('R5C_SPAWN 0\nR5C_SEQUENCE 0 0 1 '+str(duration)+'\n'+
                    ''.join(f'R5C_SAMPLE 0 0 {i*.25} {cycle} 0 0 0 0\n'
                            for i,cycle in enumerate(cycles))+'R5C_DONE\n')
        self.assertFalse(summarize(log(0,[0]*5),models)['passed'])
        self.assertFalse(summarize(log(1,[0]*5),models)['passed'])
        result=summarize(log(1,[0,.25,.5,.75,.95]),models)
        self.assertTrue(result['passed'])
        self.assertEqual(result['sequence_results'][0]['duration'],1)

    def test_client_probe_completion_and_script_errors(self):
        log='R5C_VIS_SPAWN 0\nR5C_VIS_DONE\nR5C_VIS_SELECTED\n'
        self.assertEqual(summarize_visual(log,1)['failures'],[])
        self.assertTrue(summarize_visual(log,2)['failures'])
        self.assertTrue(summarize_visual(log+'SCRIPT ERROR: bad call',1)['failures'])

    def test_visual_pose_sampling_is_explicit_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=dict(path='mdl/test.rmdl',labels=['walk'],animated_sequences=[0],visual_cycle=.5)
            write_probe(tmp,[model])
            script=(Path(tmp)/'mods/r5c_compiler_test/scripts/vscripts/r5c_visual.nut').read_text()
            self.assertIn('SetCycle( 0.500000 )',script)
            self.assertIn('Anim_SetPaused( true )',script)
            model['visual_cycle']=float('nan')
            with self.assertRaisesRegex(ValueError,'visual cycle'): write_probe(tmp,[model])

    def test_pose_probe_rejects_advancing_cycles_with_static_bones(self):
        models=[dict(path='mdl/test.rmdl',labels=['bend'],animated_sequences=[0],probe_motion_sequences=[0])]
        log='R5C_SPAWN 0\nR5C_SEQUENCE 0 0 1 1.0\n'
        log+=''.join(f'R5C_SAMPLE 0 0 {i*.2} {i*.2} 0 0 0 0\n' for i in range(5))
        static=''.join('R5C_ATTACHMENT 0 0 0 0 0\n' for i in range(5))
        self.assertFalse(summarize(log+static+'R5C_DONE\n',models)['passed'])
        moving=''.join(f'R5C_ATTACHMENT 0 0 {i} 0 0\n' for i in range(5))
        self.assertTrue(summarize(log+moving+'R5C_DONE\n',models)['passed'])
        self.assertFalse(summarize(log+moving.replace('2 0 0','nan 0 0')+'R5C_DONE\n',models)['passed'])

    def test_pose_comparison_against_installed_reference(self):
        from ingame54 import summarize_pose, rotation_difference
        spec=dict(group='g',sequences=['walk'],attachments=['tip'],cycles=[0,1])
        models=[{'path':'mdl/rebuilt.rmdl','pose_compare':dict(spec)},
                {'path':'mdl/retail.rmdl','pose_compare':dict(spec,reference=True)}]
        log=('R5C_POSE 1 walk 0.0000 tip 0 0 0 0 0 0\nR5C_POSE 1 walk 1.0000 tip 5 0 0 89.9 10 0\n'
             'R5C_POSE 0 walk 0.0000 tip 0 0 0.004 0 0 0\nR5C_POSE 0 walk 1.0000 tip 5 0 0 89.9 12 2\nR5C_POSE_DONE\n')
        report=summarize_pose(log,models)
        # near a 90-degree pitch, yaw and roll trade off: the orientations nearly agree
        self.assertLess(rotation_difference((89.9,10,0),(89.9,12,2)),.01)
        self.assertEqual(report['failures'],[])
        self.assertEqual(report['pairs']['mdl/rebuilt.rmdl']['compared'],2)
        self.assertAlmostEqual(report['pairs']['mdl/rebuilt.rmdl']['reference_motion'],5)
        # a moved origin, a turned attachment, a missing sample and an unfinished probe fail
        self.assertTrue(summarize_pose(log.replace('0 walk 1.0000 tip 5 0 0','0 walk 1.0000 tip 5.1 0 0'),models)['failures'])
        self.assertTrue(summarize_pose(log.replace('89.9 12 2','80 12 2'),models)['failures'])
        self.assertTrue(summarize_pose(log.replace('R5C_POSE 0 walk 0.0000 tip 0 0 0.004 0 0 0\n',''),models)['failures'])
        self.assertTrue(summarize_pose(log.replace('R5C_POSE_DONE\n',''),models)['failures'])
        # a reference that does not move cannot show a difference
        still=log.replace('1 walk 1.0000 tip 5 0 0','1 walk 1.0000 tip 0 0 0').replace('0 walk 1.0000 tip 5 0 0','0 walk 1.0000 tip 0 0 0')
        self.assertIn('not sensitive',' '.join(summarize_pose(still,models)['failures']))

if __name__=='__main__': unittest.main()
