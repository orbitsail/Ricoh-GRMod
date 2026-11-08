# SPDX-License-Identifier: GPL-2.0-only
"""Run upstream 1.20 boot checks on a learned-module build.
The AWB/shadow hooks intentionally change values and have their own full function suites;
treat them as function-level entries, exactly as upstream treats HDR/ADJ replacements.
"""
from pathlib import Path
import importlib.util,sys,json,hashlib
root=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('boot_checks120',root/'tools/gr4v120/aspect/boot_checks.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
out=Path(sys.argv[1]);official=(out/'official120.rtos').read_bytes();patched=(out/'120-final.rtos').read_bytes()
for address,log in [(0x53960e90,'awb120-fw.log'),(0x539473a4,'shadow120-fw.log')]:
 text=(out/log).read_text()
 assert 'RESULT all passed' in text,log+' must pass first'
 m.SPECIAL[address]='entry'
result=m.run(official,patched,(out/'120-final.icons').read_bytes(),(out/'official120.icons').read_bytes())
result.update(imageSha256=hashlib.sha256(patched).hexdigest(),functionSuites=['awb120-fw.log','shadow120-fw.log'],addedFunctionEntries=['0x53960e90','0x539473a4'])
(out/'boot120.json').write_text(json.dumps(result,indent=2))
