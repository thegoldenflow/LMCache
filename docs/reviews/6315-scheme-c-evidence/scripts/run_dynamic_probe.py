# SPDX-License-Identifier: Apache-2.0
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT=Path(os.environ.get("LMCACHE_REVIEW_WORKSPACE", Path(__file__).resolve().parent))
summary=[]
for name in ['baseline/transitional','exclude-device-cpu/dist']:
    wheel,=(ROOT/'evidence'/name).glob('*.whl')
    with tempfile.TemporaryDirectory() as directory:
        with zipfile.ZipFile(wheel) as zf:
            zf.extractall(directory)
        command=[str(ROOT/'venv-client/bin/python'),'-I','-B','-c',
            'import sys; sys.path.insert(0,sys.argv[1]); from lmcache.v1.platform import get_device_spec; s=get_device_spec("cpu"); print("CPU_SPEC", None if s is None else type(s).__name__)',directory]
        proc=subprocess.run(command,cwd='/tmp',capture_output=True,text=True)
        summary.append({'wheel':name,'exit':proc.returncode,'output':proc.stdout,'stderr':proc.stderr})
(ROOT/'evidence/dynamic-probe.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
