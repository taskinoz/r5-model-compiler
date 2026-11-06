"""Offline R5R test support: isolated game copy and loopback SDK netconsole.

Large immutable game assets use junctions/hard links on the same volume. Configs,
scripts and mods are copied. Never point --runtime at an installed game directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import struct
import subprocess
import time


def varint(n):
    out=bytearray()
    while n>127:
        out.append((n&127)|128); n>>=7
    out.append(n)
    return bytes(out)


def field(n,value):
    if isinstance(value,int): return varint(n<<3)+varint(value)
    if isinstance(value,str): value=value.encode()
    return varint((n<<3)|2)+varint(len(value))+value


def fields(data):
    pos=0; result={}
    def read():
        nonlocal pos
        value=0
        for shift in range(0,70,7):
            if pos>=len(data): raise ValueError('truncated protobuf varint')
            b=data[pos]; pos+=1; value|=(b&127)<<shift
            if b<128: return value
        raise ValueError('oversized protobuf varint')
    while pos<len(data):
        key=read(); wire=key&7
        if wire==0: value=read()
        elif wire==2:
            count=read()
            if count>len(data)-pos: raise ValueError('truncated protobuf field')
            value=data[pos:pos+count]; pos+=count
        else: raise ValueError('unsupported protobuf wire type')
        result[key>>3]=value
    return result


class NetConsole:
    def __init__(self,port,password,timeout=2):
        self.sock=socket.create_connection(('::1',port),timeout)
        self.buffer=bytearray(); self.send(1,password)
        response=self.receive()
        if response.get(3)!=0 or not response.get(5):
            self.close(); raise ValueError('SDK netconsole authentication failed')
        self.send(2,value='1')
    def send(self,kind,message='',value=''):
        request=field(3,kind)+field(4,message)+field(5,value)
        envelope=field(1,0)+field(3,request)
        self.sock.sendall(struct.pack('!I',len(envelope))+envelope)
    def command(self,text): self.send(0,text)
    def receive(self):
        while len(self.buffer)<4: self.buffer.extend(self.sock.recv(65536) or self._closed())
        count=struct.unpack_from('!I',self.buffer)[0]
        if count>4*1024*1024: raise ValueError('oversized SDK message')
        while len(self.buffer)<count+4: self.buffer.extend(self.sock.recv(65536) or self._closed())
        envelope=fields(bytes(self.buffer[4:4+count])); del self.buffer[:4+count]
        if envelope.get(1,0): raise ValueError('set rcon_encryptframes 0 in the isolated runtime')
        return fields(envelope.get(3,b''))
    def _closed(self): raise ConnectionError('SDK netconsole closed')
    def close(self): self.sock.close()


def prepare(game,runtime):
    game=Path(game).resolve(); runtime=Path(runtime).resolve()
    if game==runtime or game in runtime.parents or runtime in game.parents:
        raise ValueError('runtime must be separate from the installed game')
    if not (game/'r5apex.exe').is_file(): raise ValueError('R5R r5apex.exe missing')
    if game.drive.casefold()!=runtime.drive.casefold():
        raise ValueError('runtime must be on the same volume as R5R for asset hard links')
    marker=runtime/'.r5c-isolated-runtime'
    if marker.exists() and marker.read_text().strip()!=str(game):
        raise ValueError('runtime was prepared from a different game directory')
    if runtime.exists() and not marker.exists(): raise ValueError('existing directory is not an R5C runtime')
    runtime.mkdir(parents=True,exist_ok=True); marker.write_text(str(game))
    for source in game.iterdir():
        dest=runtime/source.name
        if dest.exists(): continue
        if source.is_file(): shutil.copy2(source,dest)
        elif source.name in ('platform','cfg','mods'): shutil.copytree(source,dest)
        elif source.name=='paks':
            for f in source.rglob('*'):
                target=dest/f.relative_to(source)
                if f.is_dir(): target.mkdir(parents=True,exist_ok=True)
                else:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    os.link(f,target)
        else:
            subprocess.run(['cmd','/c','mklink','/J',str(dest),str(source)],check=True,capture_output=True)
    return runtime


def write_probe(runtime,models):
    """Generate an isolated server probe with literal, validated asset names."""
    import re
    def literal(text):
        if not re.fullmatch(r'[A-Za-z0-9_./ -]+',text):
            raise ValueError('unsupported character in runtime probe asset/sequence name')
        return json.dumps(text)
    lines=['global function R5C_Run',
           'void function R5C_Run() { thread R5C_Probe() }',
           'void function R5C_Probe()', '{',
           '  while ( GetPlayerArray().len() == 0 ) wait 0.5',
           '  entity player = GetPlayerArray()[0]',
           '  vector forward = AnglesToForward( <0, player.EyeAngles().y, 0> )',
           '  vector right = AnglesToRight( <0, player.EyeAngles().y, 0> )',
           '  vector center = player.GetOrigin() + forward * 180 + <0,0,48>',
           '  wait 3.0']
    for i,model in enumerate(models):
        lines += ['  {',f'    asset model = ${literal(model["path"])}',
                  '    PrecacheModel( model )',
                  f'    vector origin = center + right * {(i-(len(models)-1)/2)*60:.3f}',
                  '    entity prop = CreatePropDynamic( model, origin, <0,0,0> )',
                  f'    print( "R5C_SPAWN {i}\\n" )']
        for j,label in enumerate(model['labels']):
            lines += ['    {',f'      string label = {literal(label)}',
                      '      int id = prop.LookupSequence( label )',
                      '      float duration = prop.GetSequenceDuration( label )',
                      f'      print( format( "R5C_SEQUENCE {i} {j} %d %.6f\\n", id, duration ) )',
                      '      if ( id < 0 ) { print( "R5C_FAIL missing sequence\\n" ); return }',
                      '      prop.Anim_PlayWithRefPoint( label, origin, <0,0,0>, 0.0 )',
                      '      float started = Time()',
                      '      for ( int sample = 0; sample < 5; sample++ )',
                      '      {',
                      '        if ( sample > 0 ) wait max( 0.01, duration * (sample == 4 ? 0.20 : 0.25) )',
                      '        vector p = prop.GetOrigin()',
                      f'        print( format( "R5C_SAMPLE {i} {j} %.6f %.6f %.6f %.6f %.6f %.6f\\n", Time()-started, prop.GetCycle(), p.x, p.y, p.z, prop.GetAngles().y ) )',
                      '        int probe = prop.LookupAttachment( "probe" )',
                      '        if ( probe > 0 )',
                      '        {',
                      '          vector a = prop.GetAttachmentOrigin( probe )',
                      f'          print( format( "R5C_ATTACHMENT {i} {j} %.6f %.6f %.6f\\n", a.x, a.y, a.z ) )',
                      '        }','      }','    }']
        lines += ['  }']
    lines += ['  player.ClientCommand( "screenshot" )','  print( "R5C_DONE\\n" )','}']
    mod=Path(runtime)/'mods'/'r5c_compiler_test'
    scripts=mod/'scripts'/'vscripts'; scripts.mkdir(parents=True,exist_ok=True)
    (mod/'mod.vdf').write_text('"mod" { "name" "R5C compiler test" "id" "R5C.Test" "description" "Isolated authored models" "version" "1.0" "author" "R5C" }\n')
    (scripts/'scripts.rson').write_text('When: "SERVER"\nScripts:\n[\n r5c_probe.nut\n]\n')
    (scripts/'r5c_probe.nut').write_text('\n'.join(lines)+'\n')


def summarize(log,models):
    import re
    spawned={int(i) for i in re.findall(r'R5C_SPAWN (\d+)',log)}
    sequences={}
    for i,j,index,duration in re.findall(r'R5C_SEQUENCE (\d+) (\d+) (-?\d+) ([\d.eE+-]+)',log):
        sequences[(int(i),int(j))]={'index':int(index),'duration':float(duration)}
    failures=[]
    for i,model in enumerate(models):
        if i not in spawned: failures.append(model['path']+': missing spawn')
        for j,label in enumerate(model['labels']):
            value=sequences.get((i,j))
            if value is None or value['index']<0: failures.append(model['path']+': missing sequence '+label)
            if len(re.findall(rf'R5C_SAMPLE {i} {j} ',log))!=5:
                failures.append(model['path']+': incomplete samples for '+label)
    samples=[]
    for match in re.finditer(r'R5C_SAMPLE (\d+) (\d+) ([^\r\n]+)',log):
        try:
            values=[float(x) for x in match[3].split()]
            if len(values)!=6 or not all(__import__('math').isfinite(v) for v in values): raise ValueError()
            samples.append(dict(model=int(match[1]),sequence=int(match[2]),time=values[0],cycle=values[1],origin=values[2:5],yaw=values[5]))
        except ValueError: failures.append('invalid movement sample')
    if 'R5C_DONE' not in log: failures.append('runtime probe did not finish')
    if 'R5C_FAIL' in log: failures.append('runtime probe reported a failure')
    return dict(spawned=len(spawned),sequences=len(sequences),samples=samples,failures=failures,
                passed=not failures,scope='spawn, sequence lookup/playback and movement samples; inspect screenshots and samples for geometry/motion equivalence')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game',required=True); p.add_argument('--runtime',required=True)
    p.add_argument('--pak',required=True); p.add_argument('--port',type=int,default=37025)
    p.add_argument('--timeout',type=int,default=180); p.add_argument('--map',default='mp_rr_canyonlands_staging')
    p.add_argument('--keep-open',action='store_true',help='leave the isolated game open for manual inspection')
    a=p.parse_args()
    pak=Path(a.pak).resolve()
    package=json.loads(pak.with_suffix('.report.json').read_text())
    if package.get('target')!='s3': p.error('R5R test requires an s3 package report')
    for filename,digest in package['outputs'].items():
        artifact=pak.parent/Path(filename).name
        if hashlib.sha256(artifact.read_bytes()).hexdigest()!=digest:
            p.error('package hash mismatch: '+str(artifact))
    if os.name!='nt': p.error('R5R runtime preparation requires Windows')
    # Do not compete with another game session on this shared machine.
    for image in ('r5apex.exe','r5apex_ds.exe'):
        running=subprocess.run(['tasklist','/FI','IMAGENAME eq '+image,'/FO','CSV','/NH'],capture_output=True,text=True,check=True)
        if ('"'+image+'"') in running.stdout.lower(): p.error('an R5R game process is already running')
    if not (Path(a.game)/'build.txt').read_text().startswith('R5R-'):
        p.error('expected an explicitly installed R5R runtime')
    runtime=prepare(a.game,a.runtime)
    write_probe(runtime,package['models'])
    for suffix in ('.rpak','.starpak'):
        source=pak.with_suffix(suffix); dest=runtime/'paks'/'Win64'/source.name
        if dest.exists() and os.path.samefile(source,dest): continue
        if dest.exists(): dest.unlink()
        shutil.copy2(source,dest)
    password=secrets.token_hex(24)
    config=runtime/'platform'/'cfg'/'r5c_test.cfg'
    config.write_text('\n'.join(['sv_cheats 1','rcon_encryptframes 0','sv_rcon_useloopbacksocket 1',
        'sv_rcon_password '+password,'sv_rcon_sendlogs 1','cl_onlineAuthEnable 0',
        'sv_onlineAuthEnable 0','pylon_matchmaking_enabled 0','backtrace_enabled 0'])+'\n')
    args=[str(runtime/'r5apex.exe'),'-launcher','-offline','-dev','-devsdk','-fnf','-multiple',
        '-novid','-windowed','-w','1280','-h','720','-console','-playlistfile','playlists_r5_patch.txt',
        '+hostport',str(a.port),'+exec','r5c_test.cfg','+map',a.map,'+launchplaylist','dev_default']
    process=None; connection=None; log=''
    report={'runtime':str(runtime),'game':str(Path(a.game).resolve()),'state':'starting',
            'runtime_sha256':hashlib.sha256((runtime/'r5apex.exe').read_bytes()).hexdigest(),
            'package_outputs':package['outputs'],'models':package['models']}
    previous_screenshots={str(p) for p in runtime.rglob('*.tga')}
    started=time.monotonic()
    try:
        process=subprocess.Popen(args,cwd=runtime); report['pid']=process.pid
        deadline=time.monotonic()+a.timeout
        while time.monotonic()<deadline:
            if process.poll() is not None: raise RuntimeError('R5R exited before netconsole was ready')
            try: connection=NetConsole(a.port,password); break
            except (OSError,ConnectionError): time.sleep(1)
        else: raise TimeoutError('R5R netconsole startup timed out; inspect the game window for startup prompts')
        report['state']='netconsole-ready'
        connection.command('echo R5C_NETCON_READY')
        connection.command('pak_requestload '+pak.name)
        deadline=time.monotonic()+a.timeout; next_probe=0.; probe_started=False
        with (runtime/'r5c-netconsole.log').open('w',encoding='utf-8') as f:
            while time.monotonic()<deadline and process.poll() is None:
                if not probe_started and time.monotonic()>next_probe:
                    connection.command('script print( "R5C_VM_READY\\n" )')
                    next_probe=time.monotonic()+5
                try:
                    message=connection.receive()
                    text=message.get(4,b'').decode('utf-8',errors='replace')
                    f.write(text); f.flush(); log+=text
                    if not probe_started and 'R5C_VM_READY' in text:
                        connection.command('script R5C_Run()'); probe_started=True
                    if 'R5C_DONE' in text: break
                except socket.timeout: continue
                except ConnectionError: break
        report.update(summarize(log,package['models'])); report['state']='finished'
    except (OSError,ValueError,RuntimeError,TimeoutError) as error:
        report.update(state='failed',passed=False,error=str(error))
    finally:
        if connection:
            if not a.keep_open:
                try: connection.command('quit')
                except OSError: pass
            connection.close()
        if process and not a.keep_open:
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=10)
        config.unlink(missing_ok=True)
        report['elapsed_seconds']=time.monotonic()-started
        report['exit_code']=process.poll() if process else None
        report['screenshots']=[str(p) for p in runtime.rglob('*.tga') if str(p) not in previous_screenshots]
        (runtime/'r5c-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report.get('passed') else 1


if __name__=='__main__': raise SystemExit(main())
