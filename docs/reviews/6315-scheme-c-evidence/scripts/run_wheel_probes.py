# SPDX-License-Identifier: Apache-2.0
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(os.environ.get("LMCACHE_REVIEW_WORKSPACE", Path(__file__).resolve().parent))
REPO=ROOT/'LMCache-review'
OUT=ROOT/'evidence/wheel-mutations'
OUT.mkdir(exist_ok=True)
PYTHON=str(ROOT/'venv-build/bin/python')
BASE,=(ROOT/'evidence/baseline/transitional').glob('*.whl')
with zipfile.ZipFile(BASE) as zf:
    original={p:zf.read(p) for p in zf.namelist()}
record=next(p for p in original if p.endswith('.dist-info/RECORD'))

def write_wheel(folder, content):
    rows=[]
    for p,b in sorted(content.items()):
        digest=base64.urlsafe_b64encode(hashlib.sha256(b).digest()).decode().rstrip('=')
        rows.append([p, 'sha256='+digest, str(len(b))])
    rows=[r for r in rows if r[0]!=record]
    rows.append([record,'',''])
    stream=io.StringIO()
    csv.writer(stream,lineterminator='\n').writerows(rows)
    content[record]=stream.getvalue().encode()
    folder.mkdir(exist_ok=True)
    wheel=folder/BASE.name
    with zipfile.ZipFile(wheel,'w',zipfile.ZIP_DEFLATED) as zf:
        for p,b in content.items():
            zf.writestr(p,b)
    return wheel

cases={}
changed=dict(original)
changed['lmcache/logging.py']+=b'\nraise RuntimeError("adversarial audit source mismatch")\n'
cases['source-changed']=changed
changed=dict(original)
changed['lmcache_client-0.0.0.dev0.data/scripts/lmcache-server']=b'#!/bin/sh\necho unexpected-server-cli\n'
cases['server-script']=changed
changed=dict(original)
changed['unexpected_server.py']=b'raise RuntimeError("unlisted top-level module")\n'
cases['top-level-module']=changed
changed=dict(original)
for p in list(changed):
    if p.startswith('lmcache/lmcache_native.') and p.endswith('.so'):
        del changed[p]
cases['native-missing']=changed
summary=[]
for name,contents in cases.items():
    folder=OUT/name
    wheel=write_wheel(folder,contents)
    cmd=[PYTHON,'-B','tools/client_wheel/audit.py',str(wheel),'--boundary','transitional','--staging',str(ROOT/'evidence/baseline/transitional/STAGING_MANIFEST.json')]
    proc=subprocess.run(cmd,cwd=REPO,text=True,capture_output=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
    (folder/'audit.log').write_text(proc.stdout+proc.stderr)
    summary.append({'name':name,'exit':proc.returncode,'result':proc.stdout.splitlines()[-1:]})
(OUT/'results.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
