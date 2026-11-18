"""Build an S3 R5R RPak from r5studiomdl --external-assets output using RePak.

RePak is a separate user-provided program. No game or third-party binaries are bundled.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mdl54 import Model, SequenceAsset


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def asset_path(name):
    name=name.replace('\\','/')
    parts=name.split('/')
    if not parts or name.startswith('/') or any(p in ('..','.','') for p in parts) or ':' in name or any(ord(c)<32 for c in name):
        raise ValueError('unsafe model asset path')
    if not name.startswith('mdl/'): name='mdl/'+name
    if not name.endswith('.rmdl'): raise ValueError('expected .rmdl model name')
    return name


def installed_animrig_path(name):
    """A dependency already present in the target install, not an asset to package."""
    name=name.replace('\\','/')
    if not name.startswith('animrig/') or not name.endswith('.rrig'):
        raise ValueError('installed rig must be an animrig/*.rrig asset path')
    # Reuse the path-component checks without the model prefix/extension rules.
    asset_path(name[:-5]+'.rmdl')
    return name


def package(models, output, name, repak, target, *, installed_animrigs=(), retail_paths=False):
    if target!='s3': raise ValueError('RPak packaging currently requires the surveyed s3 / R5R profile')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',name): raise ValueError('invalid pak name')
    installed_animrigs=list(dict.fromkeys(installed_animrig_path(p) for p in installed_animrigs))
    models=list(models)
    if not models: raise ValueError('at least one model is required')
    output=Path(output).resolve(); sources=output/'sources'; sources.mkdir(parents=True,exist_ok=True)
    files=[]; inputs={}; outputs=[]; names=set()
    def copy(source,dest):
        source=Path(source).resolve(); dest=sources/dest
        dest.parent.mkdir(parents=True,exist_ok=True)
        if source!=dest: shutil.copyfile(source,dest)
        inputs[str(source)]=sha(source)
    for path in models:
        path=Path(path).resolve(); m=Model(path,target)
        if m.get('i',0x124) and m.get('i',0x158)!=-1:
            raise ValueError(f'{path}: embedded IK chains require the native external-rig sentinel; recompile with --external-assets')
        if any(not mat['guid'] for mat in m.materials):
            raise ValueError(f'{path}: every material needs an existing nonzero GUID (--material-guid)')
        marker=path.with_suffix('.assetset'); lines=marker.read_text().splitlines()
        if len(lines)!=3 or lines[:2]!=['R5AS1',target]: raise ValueError('asset set target/magic mismatch')
        count=int(lines[2])
        if count!=len(m.sequences): raise ValueError('model/asset set sequence count mismatch')
        if not 0<=count<=32767: raise ValueError('invalid asset set sequence count')
        native=asset_path(m.name)
        if native.casefold() in names: raise ValueError('duplicate model asset path')
        names.add(native.casefold()); base=native[4:-5]; rigpath=f'animrig/{base}.rrig'
        rigfile=path.with_suffix('.rrig'); rig=Model(rigfile,target)
        # the rig repeats the model's bones, except that procedures (jiggle bones) stay
        # in the model: rig copies have no procedure and no always-procedural flag (4)
        if any(b['proctype'] for b in rig.bones) or rig.get('i',0x198):
            raise ValueError('rig carries procedural bones; recompile with this compiler')
        strip=lambda b: dict(b,proctype=0,flags=b['flags']&0x20 if b['proctype'] else b['flags'])
        if rig.bones!=[strip(b) for b in m.bones]: raise ValueError('model/rig bone layout mismatch')
        if rig.ik_chains()!=m.ik_chains(): raise ValueError('model/rig IK chain layout mismatch')
        copy(path,native); copy(path.with_suffix('.vg'),native[:-5]+'.vg'); copy(rigfile,rigpath)
        if m.get('i',0x1DC):
            # the native PHY: RePak reads it beside the model; its checksum must match
            phy=path.with_suffix('.phy')
            if not phy.exists(): raise ValueError('model records a PHY but none was found: '+str(phy))
            data=phy.read_bytes()
            if len(data)!=m.get('i',0x1DC) or data[12:16]!=path.read_bytes()[8:12]:
                raise ValueError('PHY size/checksum does not match its model: '+str(phy))
            copy(phy,native[:-5]+'.phy')
        sequences=[]; labels=[]; stems=set()
        for i in range(count):
            source=path.with_suffix(f'.seq{i}.rseq'); seq=SequenceAsset(source,rig)
            if seq.name!=m.sequences[i]['name']: raise ValueError('model/asset set sequence label mismatch')
            # retail names a sequence asset animseq/<model path>/<label>.rseq, and the game
            # resolves a short label (Anim_PlayOnly( "drone_active_idle" )) by that file
            # name; an imported retail label is itself an asset path, so its base name is used
            stem=seq.name.replace('\\','/').rsplit('/',1)[-1]
            if stem.lower().endswith('.rseq'): stem=stem[:-5]
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}',stem) or stem in ('.','..'):
                raise ValueError('sequence label cannot name an asset: '+seq.name)
            if stem.casefold() in stems: raise ValueError('duplicate sequence asset name: '+stem)
            stems.add(stem.casefold())
            dest=f'animseq/{base}/{stem}.rseq'
            # with retail_paths an imported retail label stays the asset path: autolayers
            # name their sequence by the hash of that path (replacing the installed asset)
            label=seq.name.replace('\\','/')
            parts=label.split('/')
            if (retail_paths and label.lower().startswith('animseq/') and label.lower().endswith('.rseq') and len(parts)>2
                    and all(re.fullmatch(r'[A-Za-z0-9_.-]{1,96}',x) and x not in ('.','..') for x in parts)):
                dest=label
            copy(source,dest); sequences.append(dest); labels.append(seq.name)
            # Native ASEQ labels are canonical asset paths, not QC short labels.
            staged=sources/dest; data=bytearray(staged.read_bytes())
            struct.pack_into('<i',data,4,len(data))
            data.extend(dest.encode('utf-8')+b'\0'); staged.write_bytes(data)

        files.append(dict(_type='arig',_path=rigpath,**{'$sequences':sequences}))
        files.append(dict(_type='mdl_',_path=native,**{'$animrigs':list(dict.fromkeys([rigpath]+installed_animrigs)),'$sequences':sequences}))
        inputs[str(marker)]=sha(marker)
        animated=[i for i,s in enumerate(m.sequences) if s['animations'] and
                  all(m.get('i',a+16)>1 for a in s['animations'])]
        outputs.append(dict(path=native,rig=rigpath,installed_animrigs=installed_animrigs,sequences=sequences,labels=labels,
                            animated_sequences=animated,
                            ik_chains=len(m.ik_chains()),external_rig=m.get('i',0x158)==-1,
                            has_ref=any(a['name'].lower()=='ref' for a in m.attachments),
                            reference_sequences=[i for i,s in enumerate(m.sequences) if not s['animations']]))
    build=dict(version=8,name=name,assetsDir=str(sources),outputDir=str(output),
               streamFileMandatory=f'paks/Win64/{name}.starpak',keepClientOnly=True,keepServerOnly=True,files=files)
    config=output/(name+'.json'); config.write_text(json.dumps(build,indent=2)+'\n')
    # Build in a fresh directory: an old successful package cannot mask a failed run.
    with tempfile.TemporaryDirectory(prefix='.repak-',dir=output) as scratch:
        build['outputDir']=scratch
        transient=Path(scratch)/(name+'.json')
        transient.write_text(json.dumps(build,indent=2)+'\n')
        run=subprocess.run([str(Path(repak).resolve()),str(transient)],cwd=output,capture_output=True,text=True,timeout=180)
        (output/(name+'.repak.log')).write_text(run.stdout+run.stderr)
        if run.returncode: raise ValueError(f'RePak failed ({run.returncode}): {run.stdout[-2000:]}{run.stderr[-2000:]}')
        artifacts=[Path(scratch)/(name+suffix) for suffix in ('.rpak','.starpak')]
        if not all(p.is_file() and p.stat().st_size for p in artifacts):
            raise ValueError('RePak did not produce RPak and mandatory stream')
        for artifact in artifacts: shutil.copy2(artifact,output/artifact.name)
    pak=output/(name+'.rpak'); stream=output/(name+'.starpak')
    if any(sha(p)!=h for p,h in inputs.items()): raise ValueError('asset input changed during packaging')
    report=dict(target=target,scope='RePak build; runtime compatibility requires an in-game test',models=outputs,
                inputs=inputs,repak_sha256=sha(repak),build_map_sha256=sha(config),
                outputs={str(p):sha(p) for p in (pak,stream)},tools={p.name:sha(p) for p in (Path(__file__),Path(__file__).with_name('mdl54.py'))})
    (output/(name+'.report.json')).write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('models',nargs='+')
    p.add_argument('--target',required=True,choices=['s3']); p.add_argument('--repak',required=True)
    p.add_argument('--installed-animrig',action='append',default=[],help='reference an existing animrig/*.rrig in the target game for every model; repeatable, not packaged')
    p.add_argument('--out',required=True); p.add_argument('--name',default='r5c_models')
    p.add_argument('--retail-paths',action='store_true',help='package imported retail sequences at their own asset paths (needed for autolayers between them; replaces the installed assets)')
    a=p.parse_args()
    try:
        report=package(a.models,a.out,a.name,a.repak,a.target,installed_animrigs=a.installed_animrig,retail_paths=a.retail_paths)
        print(json.dumps(report,indent=2))
    except (OSError,ValueError,subprocess.SubprocessError) as e: p.exit(1,str(e)+'\n')

if __name__=='__main__': main()
