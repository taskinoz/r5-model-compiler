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
        self.buffer=bytearray()
        try:
            self.send(1,password)
            response=self.receive()
            if response.get(3)!=0 or not response.get(5):
                raise ValueError('SDK netconsole authentication failed')
            self.send(2,value='1')
        except BaseException:
            self.close()
            raise

    def send(self,kind,message='',value=''):
        request=field(3,kind)+field(4,message)+field(5,value)
        self.tx_sequence=getattr(self,'tx_sequence',0)+1
        nonce=field(1,self.tx_sequence)+field(2,time.time_ns())
        envelope=field(1,nonce)+field(4,request)
        self.sock.sendall(struct.pack('!II',0x6e6f4352,len(envelope))+envelope)
    def command(self,text):
        name,_,args=text.partition(' ')
        self.send(0,name,text)
    def receive(self):
        while len(self.buffer)<8: self.buffer.extend(self.sock.recv(65536) or self._closed())
        magic,count=struct.unpack_from('!II',self.buffer)
        if magic!=0x6e6f4352: raise ValueError('invalid R5R netconsole magic')
        if count>4*1024*1024: raise ValueError('oversized SDK message')
        while len(self.buffer)<count+8: self.buffer.extend(self.sock.recv(65536) or self._closed())
        envelope=fields(bytes(self.buffer[8:8+count])); del self.buffer[:8+count]
        if envelope.get(3,b''): raise ValueError('set rcon_encryptframes 0 in the isolated runtime')
        return fields(envelope.get(4,b''))
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


def collision_probe(models,literal):
    """Server functions for --collision.

    Models with `collision_traces` ([dx, dy, expected height or null for no hit]) are
    spawned as SOLID_VPHYSICS prop_dynamics 240 units above the ground, so a vertical
    trace can only hit the prop or nothing (no terrain or clutter); each point gets an
    ordinary trace (checked) and a high-detail one (recorded), with the surface.
    `physics_drops` ([onto model path or null, expected rest height]) spawn a
    prop_physics 160 units above one level spot found by a ground search (or above a
    placed prop), one at a time, sample it as it settles and remove it. `ragdoll`
    turns a SOLID_VPHYSICS prop_dynamic 160 units above that spot into a ragdoll and
    samples it the same way. The work is in helper functions: Squirrel limits a
    function's locals, so the probe itself only makes calls."""
    nl='\\n'
    lines=['void function R5C_TracePair( int i, entity prop, vector origin, float dx, float dy, entity player )','{',
           '  vector a = origin + <dx, dy, 150>',
           '  vector b = origin + <dx, dy, -100>',
           '  TraceResults t = TraceLine( a, b, [player], TRACE_MASK_SHOT, TRACE_COLLISION_GROUP_NONE )',
           f'  print( format( "R5C_COL_TRACE %d %.3f %.3f %.4f %d %.4f %d %d %s{nl}", i, dx, dy, t.endPos.z - origin.z, t.hitEnt == prop ? 1 : 0, t.fraction, t.surfaceProp, t.contents, t.surfaceName == "" ? "-" : t.surfaceName ) )',
           '  TraceResults s = TraceLine( a, b, [player], TRACE_MASK_SOLID, TRACE_COLLISION_GROUP_NONE )',  # no hitboxes
           f'  print( format( "R5C_COL_SOLIDTRACE %d %.3f %.3f %.4f %d %.4f %d %d %s{nl}", i, dx, dy, s.endPos.z - origin.z, s.hitEnt == prop ? 1 : 0, s.fraction, s.surfaceProp, s.contents, s.surfaceName == "" ? "-" : s.surfaceName ) )',
           '  TraceResults h = TraceLineHighDetail( a, b, player, TRACE_MASK_SHOT, TRACE_COLLISION_GROUP_NONE )',
           f'  print( format( "R5C_COL_HDTRACE %d %.3f %.3f %.4f %d %.4f %d %d %s{nl}", i, dx, dy, h.endPos.z - origin.z, h.hitEnt == prop ? 1 : 0, h.fraction, h.surfaceProp, h.contents, h.surfaceName == "" ? "-" : h.surfaceName ) )',
           '}',
           'entity function R5C_Place( asset model, vector origin )','{',
           '  entity prop = CreatePropDynamic( model, origin, <0,0,0>, SOLID_VPHYSICS )',
           # as R5R's map editor places solid props (CreateEditorProp*)
           '  prop.kv.solid = 6',
           '  prop.kv.CollisionGroup = TRACE_COLLISION_GROUP_PLAYER',
           '  file.props.append( prop )',
           '  return prop',
           '}',
           'vector function R5C_FlatSpot( entity player, vector fallback )','{',
           # level ground: the grid point whose surface is most nearly horizontal and whose
           # surroundings are at its height
           '  vector flat = fallback',
           '  float best = -1.0',
           '  array<vector> around = [ <48,0,0>, <-48,0,0>, <0,48,0>, <0,-48,0> ]',
           '  for ( int gx = -6; gx <= 6; gx++ )','  {',
           '    for ( int gy = -6; gy <= 6; gy++ )','    {',
           '      vector c = player.GetOrigin() + <gx * 96.0, gy * 96.0, 0>',
           '      TraceResults g = TraceLine( c + <0,0,400>, c - <0,0,800>, [player], TRACE_MASK_SOLID, TRACE_COLLISION_GROUP_NONE )',
           '      float level = g.fraction >= 1.0 ? -1.0 : g.surfaceNormal.z',
           '      foreach ( vector o in around )','      {',
           '        TraceResults n = TraceLine( g.endPos + o + <0,0,64>, g.endPos + o - <0,0,64>, [player], TRACE_MASK_SOLID, TRACE_COLLISION_GROUP_NONE )',
           '        if ( n.fraction >= 1.0 || fabs( n.endPos.z - g.endPos.z ) > 1.0 ) level = -1.0',
           '      }',
           '      if ( level > best && Distance2D( g.endPos, player.GetOrigin() ) > 128 ) { best = level; flat = g.endPos }',
           '    }','  }',
           f'  print( format( "R5C_COL_FLAT %.4f %.1f %.1f %.1f{nl}", best, flat.x, flat.y, flat.z ) )',
           '  return flat',
           '}',
           'void function R5C_Drop( asset model, int i, int d, vector rest, entity player )','{',
           '  entity phys = CreatePropPhysics( model, rest + <0,0,160>, <0,0,0> )',
           '  file.props.append( phys )',
           '  float started = Time()',
           '  for ( int sample = 0; sample < 16; sample++ )','  {',
           '    wait 0.5',
           f'    if ( !IsValid( phys ) ) {{ print( "R5C_COL_FAIL physics prop removed{nl}" ); return }}',
           '    vector p = phys.GetOrigin()',
           f'    print( format( "R5C_COL_DROP %d %d %.2f %.4f %.4f{nl}", i, d, Time() - started, p.z - rest.z, Length( phys.GetVelocity() ) ) )',
           '  }',
           '  vector q = phys.GetOrigin()',
           '  TraceResults t = TraceLine( q + <0,0,150>, q - <0,0,30>, [player], TRACE_MASK_SHOT, TRACE_COLLISION_GROUP_NONE )',
           f'  print( format( "R5C_COL_DROPTRACE %d %d %.4f %d{nl}", i, d, t.endPos.z - q.z, t.hitEnt == phys ? 1 : 0 ) )',
           '  phys.Destroy()',
           '  wait 0.5',  # removal completes after the frame
           '}',
           # Apex ragdolls are client-side: the server entity is replaced, so the server
           # records only that the switch happened; the result is checked on screenshots
           'void function R5C_Ragdoll( asset model, int i, vector spot )','{',
           '  entity rag = CreatePropDynamic( model, spot + <0,0,60>, <0,0,0>, SOLID_VPHYSICS )',
           '  file.props.append( rag )',
           '  wait 0.3',
           '  rag.BecomeRagdoll( <0,0,0>, false )',
           '  float started = Time()',
           '  while ( IsValid( rag ) && Time() - started < 3.0 ) wait 0.1',
           f'  print( format( "R5C_COL_RAGDOLL %d %d %.2f{nl}", i, IsValid( rag ) ? 0 : 1, Time() - started ) )',
           '  if ( IsValid( rag ) ) rag.Destroy()',
           '}',
           # its global declaration is with the others at the top of the probe
           'void function R5C_Collision() { thread R5C_CollisionProbe() }',
           'void function R5C_CollisionProbe()','{',
           '  entity player = GetPlayerArray()[0]',
           '  vector forward = AnglesToForward( <0, player.EyeAngles().y, 0> )',
           '  vector right = AnglesToRight( <0, player.EyeAngles().y, 0> )',
           '  vector base = player.GetOrigin() + forward * 360',
           '  table<string, vector> placed',
           '  entity prop',
           '  vector origin']
    solid=[(i,m) for i,m in enumerate(models) if m.get('collision_traces') or m.get('high_detail_traces')]
    for k,(i,model) in enumerate(solid):
        lines+=[f'  origin = base + right * {(k-(len(solid)-1)/2)*160:.3f} + <0,0,240>',
                f'  prop = R5C_Place( ${literal(model["path"])}, origin )',
                f'  placed[{literal(model["path"])}] <- origin',
                '  wait 0.5']
        points=list(dict.fromkeys((dx,dy) for dx,dy,_ in model.get('collision_traces',[])+model.get('high_detail_traces',[])))
        lines+=[f'  R5C_TracePair( {i}, prop, origin, {dx:.3f}, {dy:.3f}, player )' for dx,dy in points]
    drop_list=[(i,m,d,onto) for i,m in enumerate(models) for d,(onto,want) in enumerate(m.get('physics_drops',[]))]
    ragdolls=[(i,m) for i,m in enumerate(models) if m.get('ragdoll')]
    if drop_list or ragdolls:
        lines+=['  vector flat = R5C_FlatSpot( player, base )']
    for i,model,d,onto in drop_list:
        rest=f'placed[{literal(onto)}]' if onto else 'flat'
        lines+=[f'  R5C_Drop( ${literal(model["path"])}, {i}, {d}, {rest}, player )']
    # ragdolls side by side on the level spot, with earlier props removed and the player
    # 150 units back looking down at it, then left to settle for the screenshot the
    # harness takes at the end of the probe
    if ragdolls:
        lines+=['  R5C_Cleanup()','  wait 0.5']
    for k,(i,model) in enumerate(ragdolls):
        lines+=[f'  {{ vector c = player.GetOrigin() + forward * 130 + right * {(k-(len(ragdolls)-1)/2)*50:.1f}',
                '    TraceResults g = TraceLine( c + <0,0,100>, c - <0,0,200>, [player], TRACE_MASK_SOLID, TRACE_COLLISION_GROUP_NONE )',
                f'    R5C_Ragdoll( ${literal(model["path"])}, {i}, g.endPos ) }}']
    if ragdolls:
        lines+=['  wait 5.0']
    lines+=[f'  print( "R5C_COL_DONE{nl}" )','}']
    return lines


def summarize_collision(log,models,tolerance=0.5):
    """Check traces and drops against each model's declared expectations."""
    import re
    failures=[]; traces=[]; drops={}
    high_detail=[]
    for kind,i,dx,dy,height,hit,fraction,prop,contents,name in re.findall(
            r'R5C_COL_(TRACE|HDTRACE) (\d+) (\S+) (\S+) (\S+) (\d) (\S+) (-?\d+) (-?\d+) (\S+)',log):
        row=dict(model=int(i),dx=float(dx),dy=float(dy),height=float(height),hit_prop=hit=='1',fraction=float(fraction),
                 surface_prop=int(prop),contents=int(contents),surface_name=name)
        (traces if kind=='TRACE' else high_detail).append(row)
    for i,d,t,z,speed in re.findall(r'R5C_COL_DROP (\d+) (\d+) (\S+) (\S+) (\S+)',log):
        drops.setdefault(f'{i}.{d}',[]).append(dict(time=float(t),height=float(z),speed=float(speed)))
    drop_traces={f'{i}.{d}':dict(height=float(h),hit_prop=hit=='1') for i,d,h,hit in re.findall(r'R5C_COL_DROPTRACE (\d+) (\d+) (\S+) (\d)',log)}
    for i,model in enumerate(models):
        for dx,dy,expected in model.get('collision_traces',[]):
            got=[t for t in traces if t['model']==i and abs(t['dx']-dx)<1e-3 and abs(t['dy']-dy)<1e-3]
            if not got: failures.append(f'{model["path"]}: no trace at {dx},{dy}'); continue
            t=got[0]
            if expected is None:
                if t['hit_prop']: failures.append(f'{model["path"]}: trace at {dx},{dy} hit a model without collision')
            elif not t['hit_prop'] or abs(t['height']-expected)>tolerance:
                failures.append(f'{model["path"]}: trace at {dx},{dy} hit {"the prop" if t["hit_prop"] else "something else"} at {t["height"]:.3f}, expected {expected}')
        for d,(onto,want) in enumerate(model.get('physics_drops',[])):
            key=f'{i}.{d}'; samples=drops.get(key,[])
            if len(samples)<16: failures.append(f'{model["path"]} drop {d}: incomplete physics samples'); continue
            if abs(samples[-1]['height']-want)>2.0 or samples[-1]['speed']>1.0:
                failures.append(f'{model["path"]} drop {d}: rests at {samples[-1]["height"]:.3f} (speed {samples[-1]["speed"]:.3f}), expected {want}')
            dt=drop_traces.get(key)
            if dt is None or not dt['hit_prop']: failures.append(f'{model["path"]} drop {d}: the resting prop was not hit by a trace')
    # high-detail traces ([dx, dy, expected height or null]) read the trace-mesh entry
    for i,model in enumerate(models):
        for dx,dy,expected in model.get('high_detail_traces',[]):
            got=[t for t in high_detail if t['model']==i and abs(t['dx']-dx)<1e-3 and abs(t['dy']-dy)<1e-3]
            if not got: failures.append(f'{model["path"]}: no high-detail trace at {dx},{dy}'); continue
            t=got[0]
            if expected is None:
                if t['hit_prop']: failures.append(f'{model["path"]}: high-detail trace at {dx},{dy} hit the prop')
            elif not t['hit_prop'] or abs(t['height']-expected)>tolerance:
                failures.append(f'{model["path"]}: high-detail trace at {dx},{dy} at {t["height"]:.3f}, expected {expected}')
    # ragdolls: the server entity must be replaced (the switch to a client ragdoll)
    ragdolls={int(i):(gone=='1',float(t)) for i,gone,t in re.findall(r'R5C_COL_RAGDOLL (\d+) (\d) (\S+)',log)}
    for i,model in enumerate(models):
        if model.get('ragdoll'):
            if i not in ragdolls: failures.append(model['path']+': no ragdoll result')
            elif not ragdolls[i][0]: failures.append(model['path']+': did not become a ragdoll')
    if 'R5C_COL_DONE' not in log: failures.append('collision probe did not finish')
    if 'R5C_COL_FAIL' in log: failures.append('collision probe reported a failure')
    return dict(traces=traces,high_detail_traces=high_detail,ragdolls={str(k):dict(switched=v[0],seconds=v[1]) for k,v in ragdolls.items()},drops=drops,drop_traces=drop_traces,failures=failures,passed=not failures,
                scope='server traces against SOLID_VPHYSICS props and physics drops')


def write_probe(runtime,models,controls=()):
    """Generate an isolated server probe with literal, validated asset names."""
    import re
    def literal(text):
        if not re.fullmatch(r'[A-Za-z0-9_./ -]+',text):
            raise ValueError('unsupported character in runtime probe asset/sequence name')
        return json.dumps(text)
    lines=['global function CodeCallback_RFiveCompiler_Test_ModInit',
           'global function R5C_Run',
           'global function R5C_Cleanup',
           'global function R5C_Collision',
           'struct { array<entity> props } file',
           'void function CodeCallback_RFiveCompiler_Test_ModInit()', '{',
           *[f'  PrecacheModel( ${literal(model["path"])} )' for model in list(models)+list(controls)], '}',
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
                  f'    vector origin = center + right * {(i-(len(models)-1)/2)*60:.3f}',
                  '    entity prop = CreatePropDynamic( model, origin, <0,0,0> )',
                  '    file.props.append( prop )',
                  f'    prop.SetModelScale( {float(model.get("scale",1)):.6f} )',
                  f'    print( "R5C_SPAWN {i}\\n" )']
        for j,label in enumerate(model['labels']):
            if j in model.get('reference_sequences',[]): continue
            lines += ['    {',f'      string label = {literal(label)}',
                      f'      int id = prop.LookupSequence( {literal(label)} )',
                      '      float duration = id < 0 ? 0.0 : prop.GetSequenceDuration( label )',
                      f'      print( format( "R5C_SEQUENCE {i} {j} %d %.6f\\n", id, duration ) )',
                      '      if ( id < 0 ) { print( "R5C_FAIL missing sequence\\n" ); return }',
                      '      prop.Anim_PlayWithRefPoint( label, origin, <0,0,0>, 0.0 )' if model.get('has_ref') else '      prop.Anim_Play( label )',
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
    lines += ['  print( "R5C_DONE\\n" )','}',
              'void function R5C_Cleanup() { foreach ( entity prop in file.props ) { if ( IsValid(prop) ) prop.Destroy() } file.props.clear() }']
    # controls: installed game models given the same collision checks
    lines += collision_probe(list(models)+list(controls),literal)
    mod=Path(runtime)/'mods'/'r5c_compiler_test'
    scripts=mod/'scripts'/'vscripts'; scripts.mkdir(parents=True,exist_ok=True)
    (mod/'mod.vdf').write_text('"mod" { "name" "R5C compiler test" "id" "RFiveCompiler.Test" "description" "Isolated authored models" "version" "1.0" "author" "R5C" "PakLoadOnPlaylists" { "dev_default" "1" "survival_dev" "1" } }\n')
    (scripts/'scripts.rson').write_text('When: "SERVER"\nScripts:\n[\n r5c_probe.nut\n]\n')
    (scripts/'r5c_probe.nut').write_text('\n'.join(lines)+'\n')
    visual=['global function CodeCallback_RFiveCompiler_Test_ModInit',
            'global function R5C_Visual',
            'global function R5C_VisualSelect',
            'struct { array<entity> props } file',
            'void function CodeCallback_RFiveCompiler_Test_ModInit() {}',
            'void function R5C_Visual()', '{',
            '  entity player = GetLocalViewPlayer()',
            '  vector angles = <0, player.CameraAngles().y, 0>',
            '  vector center = player.CameraPosition() + AnglesToForward( angles ) * 180 - <0,0,12>',
            '  vector right = AnglesToRight( angles )']
    for i,model in enumerate(models):
        angles=model.get('visual_angles',[0,0,0])
        if len(angles)!=3 or not all(__import__('math').isfinite(float(a)) for a in angles):
            raise ValueError('invalid visual angles')
        angle_literal='<'+','.join(str(float(a)) for a in angles)+'>'
        visual+=['  {',f'    entity prop = CreateClientSidePropDynamic( center + right * {(i-(len(models)-1)/2)*60:.3f}, {angle_literal}, ${literal(model["path"])} )',
                 f'    prop.SetModelScale( {float(model.get("visual_scale",model.get("scale",1))):.6f} )',
                 '    file.props.append( prop )',f'    print( "R5C_VIS_SPAWN {i}\\n" )','  }']
    visual+=['  print( "R5C_VIS_DONE\\n" )','}']
    visual+=['void function R5C_VisualSelect( int selected )', '{',
             '  entity player = GetLocalViewPlayer()',
             '  vector angles = <0, player.CameraAngles().y, 0>',
             '  vector center = player.CameraPosition() + AnglesToForward(angles) * 180 - <0,0,12>',
             '  vector right = AnglesToRight(angles)']
    for i,model in enumerate(models):
        visual+=[f'  file.props[{i}].SetModelScale( selected == {i} ? {float(model.get("visual_scale",model.get("scale",1))):.6f} : 0.001 )',
                 f'  file.props[{i}].SetOrigin( center + right * (selected == {i} ? 0.0 : 10000.0) )']
        if model.get('animated_sequences'):
            label=model['labels'][model['animated_sequences'][0]]
            visual+=[f'  if ( selected == {i} ) file.props[{i}].Anim_Play( {literal(label)} )']
            if 'visual_cycle' in model:
                cycle=float(model['visual_cycle'])
                if not 0<=cycle<=1: raise ValueError('visual cycle must be between zero and one')
                visual+=[f'  if ( selected == {i} ) {{ file.props[{i}].SetCycle( {cycle:.6f} ); file.props[{i}].Anim_SetPaused( true ) }}']
    visual+=['  print( "R5C_VIS_SELECTED\\n" )','}']
    (scripts/'r5c_visual.nut').write_text('\n'.join(visual)+'\n')
    (scripts/'scripts.rson').write_text('When: "SERVER"\nScripts:\n[\n r5c_probe.nut\n]\nWhen: "CLIENT"\nScripts:\n[\n r5c_visual.nut\n]\n')



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
            if j in model.get('reference_sequences',[]): continue
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
    for i,model in enumerate(models):
        for j in model.get('animated_sequences',[]):
            value=sequences.get((i,j))
            if value is not None and (not __import__('math').isfinite(value['duration']) or value['duration']<=0):
                failures.append(model['path']+': animated sequence has no duration')
            cycles=[s['cycle'] for s in samples if s['model']==i and s['sequence']==j]
            if cycles and max(cycles)-min(cycles)<0.01:
                failures.append(model['path']+': animated sequence cycle did not advance')
    attachments=[]
    for match in re.finditer(r'R5C_ATTACHMENT (\d+) (\d+) ([^\r\n]+)',log):
        try:
            point=[float(x) for x in match[3].split()]
            if len(point)!=3 or not all(__import__('math').isfinite(v) for v in point): raise ValueError()
            attachments.append(dict(model=int(match[1]),sequence=int(match[2]),origin=point))
        except ValueError: failures.append('invalid attachment sample')
    for i,model in enumerate(models):
        for j in model.get('probe_motion_sequences',[]):
            points=[a['origin'] for a in attachments if a['model']==i and a['sequence']==j]
            if len(points)!=5 or max((sum((a-b)**2 for a,b in zip(p,points[0])) for p in points),default=0)<0.0001:
                failures.append(model['path']+': probe attachment did not move')
    return dict(spawned=len(spawned),sequences=len(sequences),
                sequence_results=[dict(model=i,sequence=j,**value) for (i,j),value in sorted(sequences.items())],
                samples=samples,attachment_samples=attachments,failures=failures,
                passed=not failures,scope='spawn, sequence lookup/playback and movement samples; inspect screenshots and samples for geometry/motion equivalence')


def summarize_visual(log,count):
    import re
    spawned={int(i) for i in re.findall(r'R5C_VIS_SPAWN (\d+)',log)}
    failures=[]
    if spawned!=set(range(count)) or 'R5C_VIS_DONE' not in log:
        failures.append('client visual probe did not create every model')
    if log.count('R5C_VIS_SELECTED')!=count:
        failures.append('client visual selection did not finish')
    if 'SCRIPT ERROR' in log.upper(): failures.append('client/server script error')
    return dict(spawned=len(spawned),failures=failures,
                scope='client script execution only; screenshots require visual review')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game',required=True); p.add_argument('--runtime',required=True)
    p.add_argument('--pak',required=True); p.add_argument('--port',type=int,default=37025)
    p.add_argument('--timeout',type=int,default=180); p.add_argument('--map',default='mp_rr_canyonlands_staging')
    p.add_argument('--keep-open',action='store_true',help='leave the isolated game open for manual inspection')
    p.add_argument('--collision',action='store_true',help='also run traces and physics drops declared in the package report')
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
    write_probe(runtime,package['models'],package.get('collision_controls',[]))
    for suffix in ('.rpak','.starpak'):
        source=pak.with_suffix(suffix); dest=runtime/'paks'/'Win64'/source.name
        if dest.exists() and os.path.samefile(source,dest): continue
        if dest.exists(): dest.unlink()
        shutil.copy2(source,dest)
    mod_paks=runtime/'mods/r5c_compiler_test/paks/Win64'
    mod_paks.mkdir(parents=True,exist_ok=True)
    shutil.copy2(pak,mod_paks/pak.name)
    (mod_paks/'preload.rson').write_text('Paks:\n[\n '+pak.name+'\n]\n')
    password=secrets.token_hex(24)
    config=runtime/'platform'/'cfg'/'r5c_test.cfg'
    config.write_text('\n'.join(['sv_cheats 1','rcon_encryptframes 0','sv_rcon_useloopbacksocket 1',
        'sv_rcon_password '+password,'sv_rcon_sendlogs 1','sv_rcon_maxconnections 2','enable_motd 0','cl_onlineAuthEnable 0',
        'sv_onlineAuthEnable 0','pylon_matchmaking_enabled 0','backtrace_enabled 0'])+'\n')
    # R5R executes its server defaults after command-line +exec. Apply the
    # local test connection settings at the end of that server startup file.
    server_config=runtime/'platform/cfg/tools/rcon_server_dev.cfg'
    server_original=server_config.read_text()
    server_config.write_text(server_original+'\n'+config.read_text())
    args=[str(runtime/'r5apex.exe'),'-launcher','-offline','-dev','-devsdk','-fnf','-multiple',
        '-novid','-windowed','-w','1280','-h','720','-console','-playlistfile','playlists_r5_patch.txt',
        '+hostport',str(a.port),'+exec','r5c_test.cfg','+map',a.map,'+launchplaylist','dev_default']
    (runtime/'.r5c-session.json').write_text(json.dumps(dict(port=a.port,password=password)))
    process=None; connection=None; log=''
    report={'runtime':str(runtime),'game':str(Path(a.game).resolve()),'state':'starting',
            'runtime_sha256':hashlib.sha256((runtime/'r5apex.exe').read_bytes()).hexdigest(),
            'package_outputs':package['outputs'],'models':package['models']}
    previous_screenshots={str(p) for p in runtime.rglob('*.tga')}
    logs_root=runtime/'platform/logs'
    previous_logs={p.name for p in logs_root.iterdir() if p.is_dir()}
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
        connection.command('r_drawothermodels 1')
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
                    if not probe_started and text.strip()=='R5C_VM_READY':
                        connection.command('script R5C_Run()'); probe_started=True
                    if 'R5C_DONE' in text and a.collision and 'R5C_COL_DONE' not in log:
                        if 'R5C_COL_STARTED' not in log:
                            log+='R5C_COL_STARTED\n'; connection.command('script R5C_Collision()')
                        continue
                    if 'R5C_COL_DONE' in text or ('R5C_DONE' in text and not a.collision):
                        if a.collision: time.sleep(2)  # leave the drops on screen
                        connection.command('screenshot'); time.sleep(1)
                        connection.command('script R5C_Cleanup()'); time.sleep(1)
                        connection.command('script_client R5C_Visual()'); time.sleep(3)
                        connection.command('screenshot'); time.sleep(1)
                        for model_index in range(len(package['models'])):
                            connection.command('script_client R5C_VisualSelect('+str(model_index)+')')
                            time.sleep(1); connection.command('screenshot'); time.sleep(1)
                        break
                except socket.timeout: continue
                except ConnectionError: break
        report.update(summarize(log,package['models'])); report['state']='finished'
        if a.collision:
            report['collision']=summarize_collision(log,package['models']+package.get('collision_controls',[]))
            report['failures']+=report['collision']['failures']
        # Native disk logging is buffered. Wait for the final client selection
        # marker instead of reporting a false failure before its flush.
        for attempt in range(13):
            native_log=''
            for directory in logs_root.iterdir():
                if directory.is_dir() and directory.name not in previous_logs:
                    for name in ('script.log','error.log'):
                        path=directory/name
                        if path.exists(): native_log+=path.read_text(errors='replace')+'\n'
            if not summarize_visual(native_log,len(package['models']))['failures'] or process.poll() is not None:
                break
            if attempt<12: time.sleep(0.5)
        (runtime/'r5c-script.log').write_text(native_log,encoding='utf-8')
        report['visual']=summarize_visual(native_log,len(package['models']))
        report['failures']+=report['visual']['failures']
        if process.poll() not in (None,0):
            report['failures'].append('R5R exited with code '+str(process.poll()))
        report['passed']=not report['failures']
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
        if not a.keep_open: (runtime/'.r5c-session.json').unlink(missing_ok=True)
        server_config.write_text(server_original)
        report['elapsed_seconds']=time.monotonic()-started
        report['exit_code']=process.poll() if process else None
        report['screenshots']=[str(p) for p in runtime.rglob('*.tga') if str(p) not in previous_screenshots]
        (runtime/'r5c-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report.get('passed') else 1


if __name__=='__main__': raise SystemExit(main())
