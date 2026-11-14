# SPDX-License-Identifier: Apache-2.0
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(os.environ.get("LMCACHE_REVIEW_WORKSPACE", Path(__file__).resolve().parent))
REPO = ROOT / 'LMCache-review'
OUT = ROOT / 'evidence'
PYTHON = str(ROOT / 'venv-build/bin/python')
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', NO_NATIVE_EXT='1', NO_GPU_EXT='1', CC='gcc', CXX='g++')
summary = []
for name in ['exclude-shim','exclude-generated-pyi','no-grpc','json-data','no-native']:
    folder = OUT / name
    manifest = folder / 'manifest.toml'
    build = [PYTHON,'-B','tools/client_wheel/build.py','--no-isolation','--boundary','transitional','--version','0.0.0.dev0','--manifest',str(manifest),'--out',str(folder/'dist')]
    proc = subprocess.run(build,cwd=REPO,env=ENV,text=True,capture_output=True)
    (folder/'build.log').write_text(proc.stdout+proc.stderr)
    row = {'name':name,'build_exit':proc.returncode}
    if proc.returncode == 0:
        wheel, = (folder/'dist').glob('*.whl')
        audit = [PYTHON,'-B','tools/client_wheel/audit.py',str(wheel),'--boundary','transitional','--manifest',str(manifest),'--staging',str(folder/'dist/STAGING_MANIFEST.json')]
        proc = subprocess.run(audit,cwd=REPO,env=ENV,text=True,capture_output=True)
        (folder/'audit.log').write_text(proc.stdout+proc.stderr)
        row['audit_exit']=proc.returncode
        row['audit_errors']=[l for l in proc.stdout.splitlines() if l.startswith('FAIL ') or 'failure(s)' in l]
        import zipfile
        with zipfile.ZipFile(wheel) as zf:
            row['overlap_shipped']={p:p in zf.namelist() for p in ['lmcache/v1/multiprocess/group_view.py','lmcache/v1/transport/grpc/_proto_gen/common_pb2.pyi']}
    else:
        row['last_lines']=(proc.stdout+proc.stderr).splitlines()[-12:]
    summary.append(row)
(OUT/'build-probes.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
