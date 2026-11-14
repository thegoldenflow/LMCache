# SPDX-License-Identifier: Apache-2.0
import difflib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(os.environ.get("LMCACHE_REVIEW_WORKSPACE", Path(__file__).resolve().parent))
REPO = ROOT / 'LMCache-review'
OUT = ROOT / 'evidence'
OUT.mkdir(exist_ok=True)
BASE = (REPO / 'tools/client_wheel/manifest.toml').read_text()
PYTHON = str(ROOT / 'venv-build/bin/python')
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')

def exclude(path):
    return BASE + f'\n[[exclude]]\nowner = "adversarial-review"\nreason = "counterexample"\npaths = ["{path}"]\n'

variants = {
    'exclude-shim': exclude('lmcache/v1/multiprocess/group_view.py'),
    'exclude-transitional': exclude('lmcache/v1/distributed/api.py'),
    'exclude-generated-pyi': exclude('lmcache/v1/transport/grpc/_proto_gen/common_pb2.pyi'),
    'exclude-device-cpu': exclude('lmcache/v1/platform/devices/cpu/__init__.py'),
    'exclude-scanned-leaf': exclude('lmcache/v1/common/kv_format/detectors/atom.py'),
    'exclude-scanned-leaf-via-files': BASE.replace('    "lmcache/integration/atom/",\n', '').replace('    "lmcache/v1/common/",', '    "lmcache/v1/common/",') + '\n[[exclude]]\nowner = "adversarial-review"\nreason = "counterexample"\npaths = ["lmcache/v1/common/kv_format/detectors/atom.py"]\n',
    'exclude-logging': exclude('lmcache/logging.py'),
    'common-no-slash': BASE.replace('"lmcache/v1/common/"', '"lmcache/v1/common"', 1),
    'no-grpc': exclude('lmcache/v1/transport/grpc/'),
    'no-init': exclude('lmcache/v1/common/__init__.py'),
    'no-native': BASE.replace('native_allow = ["lmcache.lmcache_native", "lmcache.cuda_ops"]', 'native_allow = ["lmcache.cuda_ops"]'),
    'server-file': BASE.replace('files = [\n','files = [\n    "lmcache/v1/multiprocess/server.py",\n',1),
    'json-data': BASE.replace('files = [\n','files = [\n    "lmcache/lmcache_frontend/config.json",\n',1).replace('    "lmcache/lmcache_frontend/",\n',''),
}

sys.path.insert(0, str(REPO / 'tools/client_wheel'))
sys.dont_write_bytecode = True
from scope import load_scope, matches
from build import tracked, select
entries = tracked('HEAD')
records = []
for name, body in variants.items():
    folder = OUT / name
    folder.mkdir(exist_ok=True)
    manifest = folder / 'manifest.toml'
    manifest.write_text(body)
    diff = ''.join(difflib.unified_diff(BASE.splitlines(True), body.splitlines(True), fromfile='manifest.toml', tofile=name+'.toml'))
    (folder / 'manifest.diff').write_text(diff)
    edits = [s for s in diff.splitlines() if s[:1] in ('+','-') and not s.startswith(('+++','---'))]
    record = {'name':name, 'changed_lines':len(edits), 'manifest':str(manifest)}
    try:
        scope = load_scope(manifest)
        package, inputs = select(scope, entries, 'transitional')
        relevant = [p for p in scope.exclude_paths if p in package]
        record['selection'] = {'package_files':len(package),'excluded_but_selected':relevant}
    except (SystemExit, Exception) as exc:
        record['selection_error'] = str(exc)
    command = [PYTHON,'-B','tools/client_wheel/check_imports.py','--source-tree','.','--boundary','transitional','--manifest',str(manifest)]
    proc = subprocess.run(command, cwd=REPO, env=ENV, text=True, capture_output=True)
    (folder/'imports.log').write_text(proc.stdout+proc.stderr)
    record['imports_exit']=proc.returncode
    record['imports_errors']=[s for s in (proc.stdout+proc.stderr).splitlines() if s.startswith('FAIL ') or 'exclude:' in s]
    records.append(record)
print('matching boundaries:',json.dumps({p: matches(p,['lmcache/v1/common/']) for p in ['lmcache/v1/common/a.py','lmcache/v1/common_x/a.py','lmcache/v1/common/__init__.py','lmcache/v1/common/a.pyi','lmcache/v1/common/a.proto','lmcache/v1/common/data.json']}))
(OUT/'manifest-probes.json').write_text(json.dumps(records,indent=2)+'\n')
print(json.dumps(records,indent=2))
