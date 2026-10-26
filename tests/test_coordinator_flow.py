"""Wizard tests against real HA objects, isolated local registries and synthetic states.

Run with the pinned Home Assistant interpreter; no services or devices are contacted.
The reference package's lightweight test environment skips this module without HA.
"""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntries
    from homeassistant.helpers import device_registry as dr, entity_registry as er
except ImportError:
    HomeAssistant = None

MODULE = Path(__file__).resolve().parents[1] / 'custom_components/mower_coordinator/config_flow.py'
if HomeAssistant:
    from custom_components.mower_coordinator import config_flow as flow


@unittest.skipIf(HomeAssistant is None, 'Home Assistant is required for native flow tests')
class WizardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.hass = HomeAssistant(self.directory.name)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        dr.async_setup(self.hass)
        await dr.async_load(self.hass)
        await er.async_get(self.hass).async_load()
        self.flow = flow.MowerConfigFlow()
        self.flow.hass = self.hass
        self.flow.context = {'source': 'user'}
        self.hass.states.async_set('lawn_mower.example', 'docked')
        self.hass.states.async_set('switch.area_one', 'off', {'hash': 101})
        self.hass.states.async_set('switch.area_two', 'off', {'hash': 102})
        self.bindings = {key: domain + '.' + key for key, domain in flow.BINDINGS.items()}
        for entity in self.bindings.values():
            self.hass.states.async_set(entity, '50')
        self.calls = []
        self.hass.bus.async_listen('call_service', lambda event: self.calls.append(event))

    async def asyncTearDown(self):
        await self.hass.async_stop(force=True)
        self.directory.cleanup()

    async def configure(self):
        result = await self.flow.async_step_user({'name': 'Example', 'mower_entity': 'lawn_mower.example'})
        self.assertEqual(result['step_id'], 'bindings')
        result = await self.flow.async_step_bindings(self.bindings)
        self.assertEqual(result['step_id'], 'zone')
        result = await self.flow.async_step_zone({'name': 'One', 'area_entities': ['switch.area_one'], 'angles': '0,90'})
        self.assertEqual(result['step_id'], 'more_areas')
        result = await self.flow.async_step_more_areas({'add_another': False})
        self.assertEqual(result['step_id'], 'rules')
        result = await self.flow.async_step_rules({'start_time': '09:00:00', 'end_time': '19:00:00', 'reserve_battery': 25, 'resume_battery': 85})
        self.assertEqual(result['step_id'], 'advanced')
        await self.flow.async_step_advanced({'configure_advanced': False})
        self.hass.states.async_set('notify.example', 'unknown')
        result = await self.flow.async_step_notifications({'targets': ['notify.example'], 'events': ['complete'], 'quiet_start': '22:00', 'quiet_end': '08:00'})
        self.assertEqual(result['step_id'], 'review')
        return await self.flow.async_step_review({'understood': True})

    async def test_complete_wizard_is_observe_only_and_sends_nothing(self):
        result = await self.configure()
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(result['data']['mode'], 'observe')
        self.assertTrue(result['data']['auto_recovery'])
        self.assertTrue(result['data']['allow_handoff'])
        self.assertFalse(result['data']['protect_unowned_work'])
        self.assertTrue(result['data']['adaptive_recharge'])
        self.assertEqual(result['data']['zones'][0]['angles'], [0, 90])
        self.assertEqual(result['data']['notifications']['targets'], ['notify.example'])
        self.assertEqual(self.calls, [])

    async def test_toggle_helper_is_accepted_only_for_safety_binding(self):
        self.hass.states.async_set('input_boolean.lawn_safety_permission', 'off')
        bindings = {**self.bindings, 'safety_entity': 'input_boolean.lawn_safety_permission'}
        self.assertEqual(self.flow._binding_errors(bindings), {})
        result = await self.flow.async_step_bindings(bindings)
        self.assertEqual(result['step_id'], 'zone')
        self.assertEqual(self.flow._settings['safety_entity'], 'input_boolean.lawn_safety_permission')
        schema = self.flow._schema_bindings()
        self.assertEqual(schema(bindings)['safety_entity'], 'input_boolean.lawn_safety_permission')
        for key in set(flow.BINDINGS) - {'safety_entity'}:
            with self.subTest(binding=key):
                invalid = {**bindings, key: 'input_boolean.lawn_safety_permission'}
                self.assertEqual(self.flow._binding_errors(invalid)[key], 'missing_entity')
        self.assertEqual(self.calls, [])

    async def test_health_suggestion_uses_self_check_metadata_not_historical_errors(self):
        # Entity IDs can be renamed; the upstream translation key is stable.
        current = SimpleNamespace(entity_id='sensor.renamed_health', domain='sensor', translation_key='self_check')
        historical = SimpleNamespace(entity_id='sensor.error_1_code', domain='sensor', translation_key='error_1_code')
        self.hass.states.async_set(current.entity_id, 'normal')
        self.hass.states.async_set(historical.entity_id, '123')
        with patch.object(flow.er, 'async_entries_for_device', return_value=[current, historical]):
            self.flow._suggest_bindings('example-device')
        self.assertEqual(self.flow._settings['error_entity'], current.entity_id)
        self.flow._settings.pop('error_entity')
        with patch.object(flow.er, 'async_entries_for_device', return_value=[historical]):
            self.flow._suggest_bindings('example-device')
        self.assertNotIn('error_entity', self.flow._settings)
        import json
        for filename in ('strings.json', 'translations/en.json'):
            translations = json.loads((MODULE.parent / filename).read_text())
            for section in ('config', 'options'):
                step = translations[section]['step']['bindings']
                self.assertIn('Self check', step['data']['error_entity'])
                self.assertIn('clear state is normal', step['description'])
                self.assertIn('Do not select historical error', step['description'])

    async def test_recovery_discovery_uses_registry_metadata_and_avoids_ambiguity(self):
        distance = SimpleNamespace(entity_id='sensor.renamed_distance', domain='sensor', translation_key='maintenance_distance')
        rtk = SimpleNamespace(entity_id='sensor.renamed_position_mode', domain='sensor', translation_key='positioning_mode')
        tracker = SimpleNamespace(entity_id='device_tracker.renamed_mower', domain='device_tracker', translation_key=None)
        for entry in (distance, rtk, tracker):
            self.hass.states.async_set(entry.entity_id, 'Fix' if entry is rtk else '10')
        with patch.object(flow.er, 'async_entries_for_device', return_value=[distance, rtk, tracker]):
            self.flow._suggest_bindings('example-device')
        self.assertEqual(self.flow._settings['mileage_entity'], distance.entity_id)
        self.assertEqual(self.flow._settings['rtk_entity'], rtk.entity_id)
        self.assertEqual(self.flow._settings['tracker_entity'], tracker.entity_id)
        self.flow._settings.clear()
        second = SimpleNamespace(entity_id='sensor.other_distance', domain='sensor', translation_key='maintenance_distance')
        self.hass.states.async_set(second.entity_id, '10')
        with patch.object(flow.er, 'async_entries_for_device', return_value=[distance, second]):
            self.flow._suggest_bindings('example-device')
        self.assertNotIn('mileage_entity', self.flow._settings)

    async def test_multiple_areas_and_overlap_rejection(self):
        await self.configure()
        result = await self.flow.async_step_zone({'name': 'Two', 'area_entities': ['switch.area_two'], 'angles': '45'})
        self.assertEqual(result['step_id'], 'more_areas')
        self.assertEqual(len(self.flow._settings['zones']), 2)
        result = await self.flow.async_step_zone({'name': 'Duplicate', 'area_entities': ['switch.area_one'], 'angles': '90'})
        self.assertEqual(result['errors']['base'], 'overlapping_areas')

    async def test_unsupported_values_are_rejected(self):
        for angle in ('nan', '181', '-1', '0,', '12.5'):
            with self.subTest(angle=angle), self.assertRaisesRegex(ValueError, 'invalid_angles'):
                flow.validate_zone({'name': 'One', 'area_entities': ['switch.area_one'], 'angles': angle}, [])
        for speed in (.1, .9, float('nan')):
            with self.subTest(speed=speed), self.assertRaisesRegex(ValueError, 'invalid_number'):
                flow.validate_zone({'name': 'One', 'area_entities': ['switch.area_one'], 'speed': speed}, [])

    async def test_advanced_calendar_weather_charge_and_profile_validation(self):
        await self.configure()
        self.flow._settings['zones'][0]['group'] = 'Main'
        result = await self.flow.async_step_calendar({'weekdays': [], 'season_months': ['1']})
        self.assertEqual(result['errors']['base'], 'invalid_calendar')
        result = await self.flow.async_step_calendar({'excluded_dates': '2027-02-30'})
        self.assertEqual(result['errors']['base'], 'invalid_calendar')
        for invalid in (-1, 31, 1.5):
            result = await self.flow.async_step_calendar({'rest_days_between_plans': invalid})
            self.assertEqual(result['errors']['base'], 'invalid_calendar')
        result = await self.flow.async_step_calendar({'weekdays': ['0', '2'], 'season_months': ['3', '10'], 'excluded_dates': '2027-01-01', 'eligible_groups': ['Main']})
        self.assertEqual(result['step_id'], 'safety_weather')
        self.assertEqual(self.flow._settings['weekdays'], [0, 2])
        self.hass.states.async_set('weather.additional', 'sunny')
        result = await self.flow.async_step_safety_weather({'multipleweather_entities': ['weather.additional'], 'forecast_enabled': True})
        self.assertEqual(result['step_id'], 'charging')
        self.assertFalse(self.flow._settings['light_rain_tolerance'])
        result = await self.flow.async_step_charging({'recharge_min_target': 90, 'recharge_max_target': 80})
        self.assertEqual(result['errors']['base'], 'invalid_battery')
        result = await self.flow.async_step_charging({})
        self.assertEqual(result['step_id'], 'notifications')
        self.assertTrue(self.flow._settings['adaptive_recharge'])
        zone = flow.validate_zone({'name': 'One', 'area_entities': ['switch.area_one'], 'not_before': '2027-01-01', 'group': 'Main', 'seasonal_intervals': {'1': 14}, 'cutting_path_mode': 3, 'mow_order': 0, 'obstacle_laps': 4, 'stationary_return_seconds': 120}, [])
        self.assertEqual(zone['seasonal_intervals'], {'1': 14})
        anchor = flow.validate_zone({'name': 'Anchor', 'area_entities': ['switch.area_one'], 'group': 'Main', 'group_anchor': True}, [])
        self.assertTrue(anchor['group_anchor'])
        with self.assertRaises(ValueError):
            flow.validate_zone({'name': 'Anchor', 'area_entities': ['switch.area_one'], 'group_anchor': True}, [])
        for extra in ({'seasonal_intervals': {'13': 10}}, {'seasonal_intervals': {'1': 0}}, {'cutting_path_mode': 4}, {'stationary_return_seconds': -1}, {'not_before': 'bad-date'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                flow.validate_zone({'name': 'One', 'area_entities': ['switch.area_one'], **extra}, [])
        lone = {**self.bindings, 'recent_fault_time_entity': ''}
        self.assertEqual(self.flow._binding_errors(lone)['base'], 'fault_pair_required')
        self.assertEqual(self.calls, [])

    async def test_bad_time_and_reserve_above_area_floor_rejected(self):
        await self.configure()
        result = await self.flow.async_step_rules({'start_time': '19:00', 'end_time': '09:00', 'reserve_battery': 25, 'resume_battery': 85})
        self.assertEqual(result['errors']['base'], 'invalid_window')
        self.flow._settings['zones'][0]['minimum_battery'] = 30
        result = await self.flow.async_step_rules({'start_time': '09:00', 'end_time': '19:00', 'reserve_battery': 30, 'resume_battery': 85})
        self.assertEqual(result['errors']['base'], 'invalid_battery')

    async def test_recovery_rules_bounds_defaults_and_explicit_disable(self):
        await self.configure()
        rules = {'start_time': '09:00', 'end_time': '19:00', 'reserve_battery': 25, 'resume_battery': 85}
        for key, (default, minimum, maximum) in flow.RECOVERY_NUMBERS.items():
            self.assertEqual(self.flow._settings[key], default)
            for invalid in (minimum - 1, maximum + 1, float('nan'), 30.5):
                with self.subTest(key=key, invalid=invalid):
                    result = await self.flow.async_step_rules({**rules, key: invalid})
                    self.assertEqual(result['errors']['base'], 'invalid_number')
        result = await self.flow.async_step_rules({**rules, 'reserve_battery': 35, 'handoff_minimum_battery': 35})
        self.assertEqual(result['errors']['base'], 'invalid_battery')
        result = await self.flow.async_step_rules({**rules, 'protect_unowned_work': 'true'})
        self.assertEqual(result['errors']['base'], 'invalid_number')
        result = await self.flow.async_step_rules({**rules, 'auto_recovery': False, 'allow_handoff': False, 'max_retries': 1, 'protect_unowned_work': True})
        self.assertEqual(result['step_id'], 'advanced')
        await self.flow.async_step_advanced({'configure_advanced': False})
        saved = await self.flow.async_step_review({'understood': True})
        self.assertFalse(saved['data']['auto_recovery'])
        self.assertFalse(saved['data']['allow_handoff'])
        self.assertEqual(saved['data']['max_retries'], 1)
        self.assertTrue(saved['data']['protect_unowned_work'])
        self.assertEqual(saved['data']['mode'], 'observe')
        self.assertEqual(self.calls, [])

    async def test_missing_entities_actions_and_acknowledgment_rejected(self):
        await self.configure()
        result = await self.flow.async_step_notifications({'targets': ['notify.absent']})
        self.assertEqual(result['errors']['targets'], 'missing_entity')
        result = await self.flow.async_step_notifications({'legacy_actions': ['notify.absent']})
        self.assertEqual(result['errors']['legacy_actions'], 'missing_action')
        result = await self.flow.async_step_review({'understood': False})
        self.assertEqual(result['errors']['base'], 'confirmation_required')

    async def test_notification_limits_reserved_actions_and_no_destinations(self):
        await self.configure()
        result = await self.flow.async_step_notifications({'targets': [f'notify.target_{i}' for i in range(11)]})
        self.assertEqual(result['errors']['base'], 'too_many_destinations')
        result = await self.flow.async_step_notifications({'legacy_actions': ['notify.notify']})
        self.assertEqual(result['errors']['legacy_actions'], 'invalid_notify_action')
        result = await self.flow.async_step_notifications({'events': ['charging', 'resumed', 'started', 'hold']})
        self.assertEqual(result['step_id'], 'review')
        self.assertEqual(self.flow._settings['notifications']['targets'], [])
        self.assertEqual(self.calls, [])

    async def test_options_rename_keeps_identity_and_does_not_mutate_until_save(self):
        await self.configure()
        class Options(flow.MowerOptionsFlow):
            @property
            def config_entry(self):
                return self.fixture
        options = Options()
        options.hass = self.hass
        options.fixture = SimpleNamespace(data=self.flow._settings, options={})
        result = await options.async_step_init()
        self.assertEqual(result['type'], 'menu')
        old_id = self.flow._settings['zones'][0]['id']
        await options.async_step_zones({'zone': old_id})
        result = await options.async_step_zone({'name': 'Renamed', 'area_entities': ['switch.area_one'], 'angles': '45'})
        self.assertEqual(result['type'], 'menu')
        self.assertEqual(options._settings['zones'][0]['id'], old_id)
        self.assertEqual(self.flow._settings['zones'][0]['name'], 'One')
        result = await options.async_step_delete_zone({'confirm_delete': True})
        self.assertEqual(result['errors']['base'], 'last_zone')
        result = await options.async_step_review({'understood': True})
        self.assertEqual(result['data']['zones'][0]['name'], 'Renamed')
        self.assertEqual(result['data']['mode'], 'observe')
        self.assertEqual(self.calls, [])

    async def test_options_clear_optional_bindings_survives_runtime_merge_and_reopen(self):
        await self.configure()
        class Options(flow.MowerOptionsFlow):
            @property
            def config_entry(self):
                return self.fixture
        options = Options()
        options.hass = self.hass
        options.fixture = SimpleNamespace(data=self.flow._settings, options={})
        await options.async_step_init()
        required = {key: value for key, value in self.bindings.items() if key in flow.REQUIRED_BINDINGS}
        result = await options.async_step_bindings(required)
        self.assertEqual(result['type'], 'menu')
        saved = await options.async_step_review({'understood': True})
        merged = {**options.fixture.data, **saved['data']}
        for key in set(flow.BINDINGS) - set(flow.REQUIRED_BINDINGS):
            self.assertEqual(merged[key], '')
            self.assertEqual(options.fixture.data[key], self.bindings[key])
        options.fixture.options = saved['data']
        reopened = Options()
        reopened.hass = self.hass
        reopened.fixture = options.fixture
        await reopened.async_step_init()
        self.assertEqual(reopened._settings['weather_entity'], '')
        self.assertEqual(reopened._settings['tracker_entity'], '')
        self.assertEqual(self.calls, [])

    async def test_options_clear_zone_speed_height_without_restoring_entry_values(self):
        await self.configure()
        original = self.flow._settings['zones'][0]
        original.update(speed=0.4, blade_height=50)
        class Options(flow.MowerOptionsFlow):
            @property
            def config_entry(self):
                return self.fixture
        options = Options()
        options.hass = self.hass
        options.fixture = SimpleNamespace(data=self.flow._settings, options={})
        await options.async_step_init()
        await options.async_step_zones({'zone': original['id']})
        await options.async_step_zone({'name': 'One', 'area_entities': ['switch.area_one'], 'angles': '0,90'})
        saved = await options.async_step_review({'understood': True})
        merged = {**options.fixture.data, **saved['data']}
        zone = merged['zones'][0]
        self.assertEqual(zone['id'], original['id'])
        self.assertNotIn('speed', zone)
        self.assertNotIn('blade_height', zone)
        self.assertEqual(original['speed'], 0.4)
        self.assertEqual(original['blade_height'], 50)
        self.assertEqual(self.calls, [])
