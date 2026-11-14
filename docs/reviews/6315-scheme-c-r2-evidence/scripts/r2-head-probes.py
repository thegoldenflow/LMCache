# SPDX-License-Identifier: Apache-2.0
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(os.environ.get('LMCACHE_REVIEW_WORKSPACE',Path(__file__).resolve().parent)).resolve()
REPO=ROOT/'LMCache-review'
OUT=ROOT/'evidence/heads';OUT.mkdir(exist_ok=True)
prs=json.loads((ROOT/'r2-pr-snapshot.json').read_text())
prs.sort(key=lambda p:[6582,6584,6594,6597,6630].index(p['number']))
summary=[]
for pr in prs[:4]:
    path=ROOT/f"head-{pr['number']}"
    subprocess.run(['git','worktree','add','--detach',str(path),pr['head_sha']],cwd=REPO,check=True,capture_output=True)
    folder=OUT/str(pr['number']);folder.mkdir(exist_ok=True)
    env=dict(os.environ,NO_NATIVE_EXT='1',NO_GPU_EXT='1',PYTHONDONTWRITEBYTECODE='1')
    command=[str(ROOT/'r2-venv/bin/python'),'-B','tools/client_wheel/build.py','--no-isolation','--boundary','transitional','--version','0.0.0.dev0','--out',str(folder/'dist')]
    p=subprocess.run(command,cwd=path,env=env,capture_output=True,text=True)
    (folder/'build.log').write_text(p.stdout+p.stderr)
    row={'pr':pr['number'],'head':pr['head_sha'],'no_native_build_exit':p.returncode}
    if (path/'tools/client_wheel/check_imports.py').exists():
        p=subprocess.run([str(ROOT/'r2-venv/bin/python'),'-B','tools/client_wheel/check_imports.py','--source-tree','.','--boundary','transitional'],cwd=path,env=env,capture_output=True,text=True)
        (folder/'imports.log').write_text(p.stdout+p.stderr);row['imports_exit']=p.returncode
    summary.append(row)
(OUT/'results.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
