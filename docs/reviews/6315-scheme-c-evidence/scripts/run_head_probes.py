# SPDX-License-Identifier: Apache-2.0
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(os.environ.get("LMCACHE_REVIEW_WORKSPACE", Path(__file__).resolve().parent))
REPO=ROOT/'LMCache-review'
PYTHON=str(ROOT/'venv-build/bin/python')
OUT=ROOT/'evidence/heads'
OUT.mkdir(exist_ok=True)
ENV=dict(os.environ,NO_NATIVE_EXT='1',NO_GPU_EXT='1',PYTHONDONTWRITEBYTECODE='1')
summary=[]
for name,sha in [('build','d848990d'),('audit','68a27383'),('clean','e13269a6'),('cuda','7f4df2bd')]:
    path=ROOT/('head-'+name)
    subprocess.run(['git','worktree','add','--detach',str(path),sha],cwd=REPO,check=True,capture_output=True)
    folder=OUT/name
    folder.mkdir(exist_ok=True)
    command=[PYTHON,'-B','tools/client_wheel/build.py','--no-isolation','--boundary','transitional','--version','0.0.0.dev0','--out',str(folder/'dist')]
    proc=subprocess.run(command,cwd=path,env=ENV,text=True,capture_output=True)
    (folder/'build.log').write_text(proc.stdout+proc.stderr)
    row={'name':name,'head':sha,'build_no_native_exit':proc.returncode}
    if (path/'tools/client_wheel/check_imports.py').exists():
        proc=subprocess.run([PYTHON,'-B','tools/client_wheel/check_imports.py','--source-tree','.','--boundary','transitional'],cwd=path,env=ENV,text=True,capture_output=True)
        (folder/'imports.log').write_text(proc.stdout+proc.stderr)
        row['source_imports_exit']=proc.returncode
    summary.append(row)
(OUT/'results.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
