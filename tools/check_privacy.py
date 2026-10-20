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

def check():
    result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True,text=True,check=True)
    failures=[]
    for name in result.stdout.split('\0'):
        if not name:continue
        if name.startswith(('local/','build/','.venv')) or name.endswith(('.log','.env')):
            failures.append((name,'private output tracked'));continue
        path=ROOT/name
        if not path.exists():continue
        content=path.read_text()
        for label,pattern in PATTERNS.items():
            if re.search(pattern,content):failures.append((name,label))
    for name,label in failures: print(f'{name}: {label}')
    if failures:raise SystemExit(1)
    print('Tracked-content privacy checks passed. Review history and prose separately before publishing.')

if __name__=='__main__':check()
