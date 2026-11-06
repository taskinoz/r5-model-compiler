"""Rebuild supported v54 sources; render-only mode explicitly excludes runtime metadata."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import subprocess
from decompile54 import decompile
from mdl54 import PROFILES
from validate54 import validate


def run(paths,target,compiler,out,render_only=False,jobs=1):
    out=Path(out).resolve(); out.mkdir(parents=True,exist_ok=True); compiler=Path(compiler).resolve()
    manifest=dict(target=target,scope='render-only' if render_only else 'implemented native subset',
                  compiler=str(compiler),compiler_sha256=hashlib.sha256(compiler.read_bytes()).hexdigest(),
                  tools={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*54.py')},
                  results=[])
    def one(item):
        index,path=item; path=Path(path).resolve(); work=out/f'{index:05d}-{path.stem}'
        result=dict(source=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        try:
            qc=decompile(path,work/'sources',target,render_only=render_only)
            rebuilt=work/'rebuilt.rmdl'
            command=[str(compiler),'--target',target,'-quiet','-o',str(rebuilt),str(qc)]
            process=subprocess.run(command,capture_output=True,text=True,timeout=180)
            if process.returncode: raise RuntimeError(process.stdout+process.stderr)
            result.update(status='pass',validation=validate(rebuilt,target,path))
            if result['validation']['differences']: result['status']='differ'
        except Exception as e: result.update(status='error',error=str(e))
        return result
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for result in pool.map(one,enumerate(paths)):
            manifest['results'].append(result)
            (out/'results.json').write_text(json.dumps(manifest,indent=2)+'\n')
            print(result['status'],result['source'],flush=True)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('models',nargs='+')
    p.add_argument('--target',choices=PROFILES,required=True); p.add_argument('--compiler',required=True)
    p.add_argument('--out',required=True); p.add_argument('--jobs',type=int,default=1)
    p.add_argument('--render-only',action='store_true'); a=p.parse_args()
    if a.jobs<1: p.error('--jobs must be positive')
    paths=[]
    for value in a.models:
        path=Path(value); paths.extend(sorted(path.rglob('*.rmdl')) if path.is_dir() else [path])
    if not paths: p.error('no model files found')
    report=run(paths,a.target,a.compiler,a.out,a.render_only,a.jobs)
    raise SystemExit(any(r['status']!='pass' for r in report['results']))
