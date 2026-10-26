#!/usr/bin/env python3
"""Check tracked release content for common accidental private exports. Not a secret-proof guarantee."""
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PATTERNS={
    'home directory':r'/(?:Users|home)/[A-Za-z0-9_.-]+/',
    'credential':r'(?:gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY|eyJ[A-Za-z0-9_-]{30,}\.)',
    'embedded device registry ID':r'(?<![A-Za-z0-9])[0-9a-f]{32}(?![A-Za-z0-9])',
    'embedded native map ID':r'(?<![0-9])[0-9]{16,20}(?![0-9])',
    'IPv4 address':r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
    'precise coordinate':r'(?<![\w.])-?\d{2,3}\.\d{5,}(?![\w.])',
    'mower serial in notification':r'mammotion_[A-Za-z0-9-]+_(?:warnings|self_check)',
}

# Public lab endpoints and RFC 5737 documentation address only. These are
# deliberate test constants, not a blanket exemption for files under lab/.
PUBLIC_TEST_ADDRESSES = {
    'tools/check_privacy.py': {'0.0.0.0', '1.1.1.1', '127.0.0.1', '192.0.2.1'},
    'lab/README.md': {'127.0.0.1'},
    'docs/INTEGRATION_VALIDATION.md': {'127.0.0.1'},
    'lab/client.py': {'127.0.0.1'},
    'lab/compose.yaml': {'127.0.0.1'},
    'lab/proxy.py': {'0.0.0.0'},
    'tools/test_lab.py': {'1.1.1.1', '127.0.0.1', '192.0.2.1'},
}

def check():
    result=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT,capture_output=True,text=True,check=True)
    failures=[]
    for name in sorted(set(result.stdout.split('\0'))):
        if not name:continue
        if name.startswith(('local/','build/','.venv')) or name.endswith(('.log','.env')):
            failures.append((name,'private output tracked'));continue
        path=ROOT/name
        if not path.exists():continue
        if path.suffix == '.png':
            if name not in {'custom_components/mower_coordinator/brand/icon.png', 'custom_components/mower_coordinator/brand/icon@2x.png'}:
                failures.append((name, 'unexpected binary asset'))
            elif path.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
                failures.append((name, 'invalid PNG asset'))
            continue
        try:
            content=path.read_text()
        except UnicodeDecodeError:
            failures.append((name, 'unexpected binary content'))
            continue
        for label,pattern in PATTERNS.items():
            matches = re.findall(pattern, content)
            if label == 'IPv4 address':
                matches = [value for value in matches if value not in PUBLIC_TEST_ADDRESSES.get(name, set())]
            if matches: failures.append((name,label))
    for name,label in failures: print(f'{name}: {label}')
    if failures:raise SystemExit(1)
    print('Tracked and nonignored candidate privacy checks passed. Review history and prose separately before publishing.')

if __name__=='__main__':check()
