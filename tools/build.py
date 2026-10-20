#!/usr/bin/env python3
"""Compile local bindings into a motion-disarmed Home Assistant package. No network or device control."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r'@@([A-Z0-9_]+)@@')
ENTITY = re.compile(r'^[a-z_]+\.[a-z_][a-z0-9_]*$')

def load(path):
    return json.loads(Path(path).read_text())

def compile_package(settings, helper_settings=None, root=ROOT):
    if not isinstance(settings, dict) or not all(isinstance(k, str) for k in settings):
        raise ValueError('Settings must be a JSON object with string binding keys')
    if helper_settings is not None and not isinstance(helper_settings, dict):
        raise ValueError('Helper settings must be a JSON object keyed by helper entity ID')
    specs = load(root / 'source/bindings.json')
    expected = {k for k, v in specs.items() if v['kind'] in ('external', 'device', 'map_hash', 'notification_id')}
    if set(settings) != expected:
        raise ValueError(f'Binding keys differ. Missing: {sorted(expected-set(settings))}; extra: {sorted(set(settings)-expected)}')
    values = {}
    for key, spec in specs.items():
        kind = spec['kind']
        if kind in ('automation', 'script', 'helper'):
            value = spec['entity']
        else:
            value = settings[key]
            if not isinstance(value, str) or not value:
                raise ValueError(f'{key}: supply a nonempty local string ({spec["purpose"]})')
            if kind == 'external' and (not ENTITY.fullmatch(value) or value.split('.')[0] != spec['domain']):
                raise ValueError(f'{key}: expected {spec["domain"]} entity/service')
            if kind == 'device' and not re.fullmatch(r'[a-f0-9]{32}', value):
                raise ValueError(f'{key}: expected a 32-character HA device registry ID')
            if kind == 'map_hash' and not re.fullmatch(r'[1-9][0-9]*', value):
                raise ValueError(f'{key}: expected a positive native map hash, kept as a string')
            if kind == 'notification_id' and not re.fullmatch(r'[A-Za-z0-9_-]+', value):
                raise ValueError(f'{key}: expected a notification identifier')
        values[key] = value
    hashes = [values[k] for k, v in specs.items() if v['kind'] == 'map_hash']
    if len(set(hashes)) != len(hashes):
        raise ValueError('Area hashes must be unique')
    for kind, label in (('external', 'External entity/service bindings'), ('notification_id', 'Notification IDs')):
        bound = [values[k] for k, v in specs.items() if v['kind'] == kind]
        if len(set(bound)) != len(bound):
            raise ValueError(f'{label} must be distinct for each role')
    internal = [v['entity'] for v in specs.values() if v['kind'] in ('automation', 'script', 'helper')]
    internal.append('input_boolean.mower_package_enabled')
    if len(set(internal)) != len(internal):
        raise ValueError('Duplicate internal entity names')
    if set(settings.values()) & set(internal):
        raise ValueError('An external binding collides with a package-owned entity')

    def replace(obj):
        if isinstance(obj, dict):
            return {k: replace(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [replace(v) for v in obj]
        if isinstance(obj, str):
            return TOKEN.sub(lambda m: values[m[1]], obj)
        return obj

    package = {'input_boolean': {'mower_package_enabled': {'name': 'Mower package enabled', 'initial': False}}, 'automation': [], 'script': {}}
    for item in load(root / 'source/configurations.json'):
        config = replace(item['config'])
        # Package merging drops empty selector dictionaries; explicit config preserves the type.
        for field in config.get('fields', {}).values():
            for selector, options in field.get('selector', {}).items():
                if options == {}:
                    field['selector'][selector] = {'read_only': False}
        if item['kind'] == 'automation':
            package['automation'].append(config)
        else:
            package['script'][values[item['binding']].split('.')[1]] = config
    helper_entities = set()
    for key, config in load(root / 'source/helpers.json').items():
        entity = values[key]
        domain, name = entity.split('.')
        helper_entities.add(entity)
        package.setdefault(domain, {})[name] = replace(config)
    for entity, override in (helper_settings or {}).items():
        if entity not in helper_entities or not isinstance(override, dict):
            raise ValueError(f'Unknown helper or invalid override: {entity}')
        domain, name = entity.split('.')
        allowed = {'name', 'icon'}
        if set(override) - allowed:
            raise ValueError(f'{entity}: helper overrides support name and icon only; runtime values, ranges and state options cannot be overridden')
        if any(not isinstance(value, str) or not value.strip() for value in override.values()):
            raise ValueError(f'{entity}: helper name and icon overrides must be nonempty strings')
        package[domain][name].update(override)
    # Installation cannot silently enable motion, even through helper overrides.
    package['input_boolean']['mower_manual_hold']['initial'] = True
    if '@@' in json.dumps(package):
        raise ValueError('Unresolved binding token')
    return package

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', required=True, type=Path)
    parser.add_argument('--helper-settings', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        package = compile_package(load(args.settings), load(args.helper_settings) if args.helper_settings else None)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(package, indent=2)+'\n')
    print(f'Wrote {len(package["automation"])} automations (motion disarmed) and {len(package["script"])} scripts. Validate in HA before enabling.')
    print('Output contains YOUR local bindings: keep it private. No device was contacted.')

if __name__ == '__main__':
    main()
