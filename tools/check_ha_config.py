#!/usr/bin/env python3
"""Validate a synthetic, disabled package with an installed Home Assistant; never start HA."""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_package import fixture_settings
from build import compile_package

with tempfile.TemporaryDirectory(prefix='mower-config-check-') as directory:
    path=Path(directory)
    (path/'mower_package.yaml').write_text(json.dumps(compile_package(fixture_settings()),indent=2))
    (path/'configuration.yaml').write_text('homeassistant:\n  packages:\n    mower: !include mower_package.yaml\n')
    result=subprocess.run([sys.executable,'-m','homeassistant','--script','check_config','-c',directory],capture_output=True,text=True,timeout=180)
    output=result.stdout+result.stderr
    print(output)
    # HA's CLI may exit zero even when individual scripts were disabled by validation.
    if result.returncode or re.search(r'ERROR:|could not be validated|Invalid config',output,re.I):
        raise SystemExit(1)
    print('Isolated Home Assistant package validation passed. No live instance or device was contacted.')
