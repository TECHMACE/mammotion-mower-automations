"""Reject configuration mistakes that could change safety roles or state machines."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build import compile_package, load


class CompilerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.specs = load(ROOT / 'source/bindings.json')
        self.settings = {}
        for key, spec in self.specs.items():
            kind = spec['kind']
            if kind == 'external':
                self.settings[key] = spec['domain'] + '.fixture_' + key.lower()
            elif kind == 'map_hash':
                self.settings[key] = str(100 + int(key.rsplit('_', 1)[1]))
            elif kind == 'device':
                self.settings[key] = '0' * 32
            elif kind == 'notification_id':
                self.settings[key] = 'fixture_' + key.lower()

    def test_injected_enable_helper_cannot_be_external_safety_role(self):
        key = next(k for k, s in self.specs.items()
                   if s['kind'] == 'external' and s['domain'] == 'input_boolean')
        self.settings[key] = 'input_boolean.mower_package_enabled'
        with self.assertRaisesRegex(ValueError, 'package-owned'):
            compile_package(self.settings)

    def test_weather_sources_must_be_distinct(self):
        keys = [k for k, s in self.specs.items()
                if s['kind'] == 'external' and s['domain'] == 'weather']
        self.assertGreaterEqual(len(keys), 2)
        self.settings[keys[1]] = self.settings[keys[0]]
        with self.assertRaisesRegex(ValueError, 'distinct'):
            compile_package(self.settings)

    def test_notifications_cannot_share_an_id(self):
        keys = [k for k, s in self.specs.items() if s['kind'] == 'notification_id']
        self.assertGreaterEqual(len(keys), 2)
        self.settings[keys[1]] = self.settings[keys[0]]
        with self.assertRaisesRegex(ValueError, 'Notification IDs must be distinct'):
            compile_package(self.settings)

    def test_settings_root_must_be_a_mapping(self):
        for invalid in (None, [], '', 7, True, {3: 'value'}):
            with self.subTest(value=invalid), self.assertRaisesRegex(ValueError, 'JSON object'):
                compile_package(invalid)

    def test_helper_settings_root_must_be_a_mapping(self):
        for invalid in ([], '', 7, False):
            with self.subTest(value=invalid), self.assertRaisesRegex(ValueError, 'JSON object'):
                compile_package(self.settings, invalid)

    def test_digit_leading_entity_breaking_attribute_templates_rejected(self):
        key = next(k for k, s in self.specs.items() if s['kind'] == 'external')
        self.settings[key] = self.specs[key]['domain'] + '.123_mower'
        with self.assertRaisesRegex(ValueError, 'expected'):
            compile_package(self.settings)

    def test_helper_overrides_cannot_rewrite_state_machine_or_persistence(self):
        for kind, override in (
            ('input_select', {'options': ['Mowing']}),
            ('input_number', {'min': -5}),
            ('input_number', {'max': -5}),
            ('input_number', {'initial': 'abc'}),
            ('input_boolean', {'initial': False}),
            ('input_text', {'initial': 'discard checkpoint'}),
        ):
            entity = next(s['entity'] for s in self.specs.values()
                          if s['kind'] == 'helper' and s['entity'].startswith(kind + '.'))
            with self.subTest(entity=entity, override=override), self.assertRaisesRegex(ValueError, 'name and icon only'):
                compile_package(self.settings, {entity: override})

    def test_presentation_overrides_preserve_safety_configuration(self):
        entity = next(s['entity'] for s in self.specs.values()
                      if s['kind'] == 'helper' and s['entity'].startswith('input_select.'))
        domain, name = entity.split('.')
        original = compile_package(self.settings)[domain][name]
        result = compile_package(self.settings, {entity: {'name': 'Mower status', 'icon': 'mdi:robot-mower'}})[domain][name]
        self.assertEqual(result, {**original, 'name': 'Mower status', 'icon': 'mdi:robot-mower'})

    def test_presentation_override_values_are_nonempty_strings(self):
        entity = next(s['entity'] for s in self.specs.values() if s['kind'] == 'helper')
        for value in (None, [], False, 2, '', ' '):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'nonempty strings'):
                compile_package(self.settings, {entity: {'name': value}})

    def test_cli_reports_invalid_root_without_traceback_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / 'settings.json'
            output = Path(directory) / 'output.yaml'
            settings.write_text(json.dumps(None))
            result = subprocess.run([sys.executable, str(ROOT / 'tools/build.py'), '--settings', str(settings),
                                     '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('Settings must be a JSON object', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
