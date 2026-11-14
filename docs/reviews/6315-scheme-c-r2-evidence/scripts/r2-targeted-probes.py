# SPDX-License-Identifier: Apache-2.0
import difflib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(os.environ.get('LMCACHE_REVIEW_WORKSPACE',Path(__file__).resolve().parent)).resolve()
REPO=ROOT/'LMCache-review'
PYTHON=str(ROOT/'r2-venv/bin/python')
OUT=ROOT/'evidence'
BASE=(REPO/'tools/client_wheel/manifest.toml').read_text()
ENV=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',LMCACHE_TRACK_USAGE='false',DO_NOT_TRACK='1')

def excluded(path):
    return BASE+f'\n[[exclude]]\nowner = "r2-review"\nreason = "counterexample"\npaths = ["{path}"]\n'

variants={
    'exclude-transitional-server':excluded('lmcache/v1/distributed/serde/aesgcm.py'),
    'exclude-from-module':excluded('lmcache/v1/platform/ops_types.py'),
    'top-gap':excluded('lmcache/logging.py').replace('boundary_gaps = [\n','boundary_gaps = [\n    "lmcache/__init__.py top lmcache/logging.py",\n',1),
    'requirements-no-reason':BASE.replace('requests = "lmcache/sdk/context.py imports it; the full wheel gets it transitively"\n',''),
}
results=[]
sys.path.insert(0,str(REPO/'tools/client_wheel'))
sys.dont_write_bytecode=True
from build import select,tracked,build_system
from scope import load_scope
entries=tracked('HEAD')
for name,body in variants.items():
    folder=OUT/name;folder.mkdir(exist_ok=True)
    manifest=folder/'manifest.toml';manifest.write_text(body)
    diff=''.join(difflib.unified_diff(BASE.splitlines(True),body.splitlines(True),fromfile='manifest.toml',tofile=name+'.toml'))
    (folder/'manifest.diff').write_text(diff)
    row={'name':name,'changed_lines':sum(l[:1] in ('+','-') and not l.startswith(('+++','---')) for l in diff.splitlines())}
    try:
        scope=load_scope(manifest)
        chosen,_=select(scope,entries,'transitional')
        row['excluded_but_selected']=[p for p in scope.exclude_paths if p in chosen]
    except SystemExit as exc: row['select_error']=str(exc)
    for label,extra in [('transitional',['--boundary','transitional']),('ratchet',['--ratchet'])]:
        cmd=[PYTHON,'-B','tools/client_wheel/check_imports.py','--source-tree','.',*extra,'--manifest',str(manifest)]
        proc=subprocess.run(cmd,cwd=REPO,env=ENV,capture_output=True,text=True)
        (folder/(label+'.log')).write_text(proc.stdout+proc.stderr)
        row[label]={'exit':proc.returncode,'errors':[l for l in (proc.stdout+proc.stderr).splitlines() if l.startswith(('FAIL ','ratchet:')) or 'cannot be a gap' in l]}
    results.append(row)

fixture=OUT/'attribute-shadow'
(fixture/'source/lmcache/pkg').mkdir(parents=True,exist_ok=True)
(fixture/'source/lmcache/__init__.py').write_text('')
(fixture/'source/lmcache/pkg/__init__.py').write_text('feature = 123\n')
(fixture/'source/lmcache/pkg/feature.py').write_text('raise RuntimeError("excluded module must never load")\n')
(fixture/'source/lmcache/consumer.py').write_text('from lmcache.pkg import feature\nassert feature == 123\n')
(fixture/'manifest.toml').write_text('trees = ["lmcache/"]\nfiles = []\ndeny = []\nnative_allow = []\nengines = []\n[[exclude]]\nowner = "r2-review"\nreason = "exclude optional submodule, keep scalar attribute"\npaths = ["lmcache/pkg/feature.py"]\n')
old=fixture/'old-tools';old.mkdir(exist_ok=True)
for name in ['check_imports.py','audit.py','scope.py','pyproject.toml']:
    body=subprocess.check_output(['git','show','03e89b199ab47804d19a3e55f93a4ff1d58c70c1:tools/client_wheel/'+name],cwd=REPO)
    (old/name).write_bytes(body)
shadow={}
for label,tool in [('before',old/'check_imports.py'),('after',REPO/'tools/client_wheel/check_imports.py')]:
    proc=subprocess.run([PYTHON,'-B',str(tool),'--source-tree',str(fixture/'source'),'--manifest',str(fixture/'manifest.toml')],env=ENV,capture_output=True,text=True)
    (fixture/(label+'.log')).write_text(proc.stdout+proc.stderr)
    shadow[label]={'exit':proc.returncode,'errors':[l for l in proc.stdout.splitlines() if l.startswith('FAIL ')]}
code='import sys;sys.path.insert(0,sys.argv[1]);import lmcache.consumer;print("feature =",lmcache.consumer.feature);print("excluded module loaded =", "lmcache.pkg.feature" in sys.modules)'
proc=subprocess.run([PYTHON,'-I','-B','-c',code,str(fixture/'source')],env=ENV,capture_output=True,text=True)
(fixture/'runtime.log').write_text(proc.stdout+proc.stderr)
shadow['runtime']={'exit':proc.returncode,'output':proc.stdout}
(OUT/'targeted-results.json').write_text(json.dumps({'variants':results,'attribute_shadow':shadow},indent=2)+'\n')
print(json.dumps({'variants':results,'attribute_shadow':shadow},indent=2))
