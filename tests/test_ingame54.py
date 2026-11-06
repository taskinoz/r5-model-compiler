"""Independent boundary/protocol and result checks for the R5R harness."""
from pathlib import Path
import json
import socket
import struct
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from ingame54 import fields, NetConsole, summarize, write_probe


class Runtime54(unittest.TestCase):
    def test_sdk_wire_format(self):
        class Capture:
            def sendall(self,data): self.data=data
        console=NetConsole.__new__(NetConsole); console.sock=Capture()
        console.command('echo x')
        # Unencrypted envelope, requestType=EXECCOMMAND, requestMsg, empty value.
        self.assertEqual(console.sock.data,bytes.fromhex('0000001008001a0c180022066563686f20782a00'))
        self.assertEqual(fields(bytes.fromhex('18002202786f2a0131')),{3:0,4:b'xo',5:b'1'})
        for bad in (b'\x80',b'\x1a\x05x',b'\x0f'):
            with self.assertRaises(ValueError): fields(bad)

    def test_receive_keeps_partial_frame_on_timeout(self):
        envelope=bytes.fromhex('08001a0b1801220568656c6c6f2a00')
        wire=struct.pack('!I',len(envelope))+envelope
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
            write_probe(tmp,[{'path':'mdl/test.rmdl','labels':['idle','walk']}])
            script=(Path(tmp)/'mods/r5c_compiler_test/scripts/vscripts/r5c_probe.nut').read_text()
            self.assertIn('asset model = $"mdl/test.rmdl"',script)
            self.assertIn('string label = "walk"',script)
            self.assertEqual(script.count('prop.LookupSequence'),2)
            self.assertNotIn('continue',script)
            self.assertIn('R5C_DONE\\n',script)
            with self.assertRaises(ValueError):
                write_probe(tmp,[{'path':'mdl/"escape.rmdl','labels':[]}])

if __name__=='__main__': unittest.main()
