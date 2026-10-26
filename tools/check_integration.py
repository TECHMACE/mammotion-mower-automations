#!/usr/bin/env python3
"""Validate integration metadata and deterministic, allowlisted release archives.

Only the mower_coordinator component is packaged. Lab files, the YAML reference,
credentials, state, caches and ignored outputs cannot enter a release archive.
No network access or Home Assistant connection is made.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = 'mower_coordinator'
PREFIX = f'custom_components/{DOMAIN}/'
ALLOWED_SUFFIXES = {'.py', '.json', '.yaml', '.png'}
SKIP_PARTS = {'__pycache__'}
FORBIDDEN_PARTS = {'local', 'lab', 'build', '.storage', '.git', '.venv', 'node_modules'}
REQUIRED_FILES = {'__init__.py', 'manifest.json', 'config_flow.py', 'strings.json', 'translations/en.json', 'runtime.py', 'core.py', 'notifications.py', 'sensor.py', 'switch.py', 'button.py', 'diagnostics.py', 'brand/icon.png'}


def component_files(root: Path = ROOT) -> dict[str, bytes]:
    """Return a strict archive manifest; refuse unexpected files and symlinks."""
    component = root / 'custom_components' / DOMAIN
    files = {}
    for path in sorted(component.rglob('*')):
        rel = path.relative_to(component)
        if path.is_symlink():
            raise ValueError(f'Symlinks are not release inputs: {rel}')
        if SKIP_PARTS.intersection(rel.parts) or path.suffix == '.pyc':
            continue
        if not path.is_file():
            continue
        if FORBIDDEN_PARTS.intersection(rel.parts) or any(part.startswith('.') for part in rel.parts):
            raise ValueError(f'Private path in integration: {rel}')
        if path.suffix not in ALLOWED_SUFFIXES and rel.as_posix() != 'LICENSE':
            raise ValueError(f'Unexpected release file: {rel}')
        if path.suffix == '.png' and rel.as_posix() not in {'brand/icon.png', 'brand/icon@2x.png'}:
            raise ValueError(f'Unexpected binary asset: {rel}')
        files[PREFIX + rel.as_posix()] = path.read_bytes()
    missing = REQUIRED_FILES - {name.removeprefix(PREFIX) for name in files}
    if missing:
        raise ValueError(f'Missing integration files: {sorted(missing)}')
    if (root / 'LICENSE').is_file():
        files.setdefault(PREFIX + 'LICENSE', (root / 'LICENSE').read_bytes())
    return files


def validate_metadata(root: Path = ROOT) -> dict:
    files = component_files(root)
    manifest = json.loads(files[PREFIX + 'manifest.json'])
    for key in ('domain', 'name', 'version', 'documentation', 'issue_tracker', 'codeowners', 'config_flow', 'integration_type', 'iot_class', 'requirements'):
        if key not in manifest:
            raise ValueError(f'Manifest missing {key}')
    if manifest['domain'] != DOMAIN or manifest['config_flow'] is not True:
        raise ValueError('Manifest domain/config_flow mismatch')
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?', manifest['version']):
        raise ValueError('Expected explicit semantic release version')
    if not manifest['codeowners'] or not all(re.fullmatch(r'@[A-Za-z0-9-]+', owner) for owner in manifest['codeowners']):
        raise ValueError('Manifest needs GitHub code owners')
    for key in ('documentation', 'issue_tracker'):
        if not manifest[key].startswith('https://github.com/TECHMACE/mammotion-mower-automations'):
            raise ValueError(f'Unexpected public metadata URL: {key}')
    hacs = json.loads((root / 'hacs.json').read_text())
    if hacs.get('homeassistant') != '2026.10.4':
        raise ValueError('HACS minimum version must match the validated HA release')
    if hacs.get('content_in_root', False):
        raise ValueError('Component archive uses normal custom_components layout')
    strings = json.loads(files[PREFIX + 'strings.json'])
    english = json.loads(files[PREFIX + 'translations/en.json'])
    if strings != english:
        raise ValueError('English translation differs from source strings')
    for section in ('config', 'options'):
        if not strings[section].get('step') or not strings[section].get('error'):
            raise ValueError(f'Missing {section} wizard text')
    for section, required in [('config', {'user', 'bindings', 'zone', 'more_areas', 'rules', 'notifications', 'review'}), ('options', {'init', 'bindings', 'zones', 'zone', 'zone_action', 'delete_zone', 'rules', 'notifications', 'review'})]:
        if not required <= strings[section]['step'].keys():
            raise ValueError(f'Missing translated {section} steps')
        for step in strings[section]['step'].values():
            if not step.get('title'):
                raise ValueError('Every wizard step needs an explanatory title')
    # Compile Python without writing bytecode and check every JSON asset.
    for name, content in files.items():
        if name.endswith('.py'):
            ast.parse(content, filename=name)
        elif name.endswith('.json'):
            json.loads(content)
        elif name.endswith('.png'):
            if content[:8] != b'\x89PNG\r\n\x1a\n' or len(content) < 24:
                raise ValueError('Invalid PNG brand asset')
            width, height = struct.unpack('>II', content[16:24])
            if width != height or width not in (256, 512):
                raise ValueError('Brand icons must be square 256px or 512px PNGs')
    return manifest


def build_archive(output: Path, root: Path = ROOT) -> str:
    """Create a byte-reproducible archive with fixed dates and permissions."""
    validate_metadata(root)
    files = component_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    validate_archive(output, root)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def validate_archive(path: Path, root: Path = ROOT) -> None:
    expected = component_files(root)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError('Archive file list differs from the integration allowlist')
        for name in names:
            parts = PurePosixPath(name).parts
            if '..' in parts or not name.startswith(PREFIX) or name.startswith('/'):
                raise ValueError('Unsafe archive path')
            if archive.read(name) != expected[name]:
                raise ValueError(f'Archive content mismatch: {name}')
        if archive.testzip() is not None:
            raise ValueError('Archive CRC verification failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Also write a manual-install ZIP (normally under build/)')
    args = parser.parse_args()
    try:
        manifest = validate_metadata()
        with tempfile.TemporaryDirectory(prefix='mower-release-check-') as directory:
            first, second = Path(directory)/'one.zip', Path(directory)/'two.zip'
            digest = build_archive(first)
            if digest != build_archive(second):
                raise ValueError('Release archive is not reproducible')
        if args.output:
            digest = build_archive(args.output)
            print(f'Wrote {args.output}: SHA256 {digest}')
        print(f'Integration {manifest["version"]}: metadata, translations, Python syntax, allowlisted archive and reproducibility checks passed.')
    except (ValueError, KeyError, json.JSONDecodeError, OSError, SyntaxError) as exc:
        parser.exit(1, f'Integration validation failed: {exc}\n')


if __name__ == '__main__':
    main()
