import asyncio
import importlib.util
import json
import unittest
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
# Load by path so this suite never executes the integration package __init__ or needs Home Assistant.
_SPEC = importlib.util.spec_from_file_location(
    'mower_coordinator_notifications', ROOT / 'custom_components/mower_coordinator/notifications.py')
notifications = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(notifications)
NotificationManager = notifications.NotificationManager

SECRET = 'notify.mobile_app_private_phone'


class FakeServices:
    """Records service calls in memory; nothing is delivered anywhere."""

    def __init__(self):
        self.calls = []
        self.fail = {}
        self.hang = set()
        self.available = {('notify', 'send_message'), ('notify', 'legacy_pager'),
                          ('notify', 'family_group'), ('persistent_notification', 'create'), ('persistent_notification', 'dismiss')}

    def has_service(self, domain, service):
        return (domain, service) in self.available

    async def async_call(self, domain, service, data, target=None, blocking=False):
        key = (target or {}).get('entity_id') or f'{domain}.{service}'
        if key in self.hang:
            await asyncio.sleep(3600)
        if key in self.fail:
            raise self.fail[key]
        self.calls.append({'domain': domain, 'service': service, 'data': dict(data),
                           'target': target, 'blocking': blocking})


class FakeHass:
    def __init__(self, time_zone='America/New_York'):
        self.services = FakeServices()
        self.config = SimpleNamespace(time_zone=time_zone)
        self.background = []

    def async_create_background_task(self, coro, name):
        task = asyncio.get_running_loop().create_task(coro, name=name)
        self.background.append(name)
        return task


class Clock:
    def __init__(self, local_hour=12, zone='America/New_York'):
        from zoneinfo import ZoneInfo
        self.now = datetime(2026, 7, 15, local_hour, 0, tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def config(**overrides):
    base = {'targets': [SECRET, 'notify.kitchen_display'], 'legacy_actions': ['notify.legacy_pager'],
            'events': ['attention', 'complete'], 'quiet_start': '22:00:00', 'quiet_end': '08:00:00',
            'urgent_override': False}
    base.update(overrides)
    return base


def pushes(hass):
    return [c for c in hass.services.calls if c['domain'] == 'notify']


def persistent(hass):
    return [c for c in hass.services.calls if c['domain'] == 'persistent_notification']


class ValidateConfigTests(unittest.TestCase):
    def test_defaults_and_normalization(self):
        cfg, errors = notifications.validate_config(
            {'targets': [' notify.a ', 'notify.a'], 'legacy_actions': ['notify.pager', 'pager'], 'quiet_start': '22:30'})
        self.assertEqual(errors, {})
        self.assertEqual(cfg['targets'], ['notify.a'])
        self.assertEqual(cfg['legacy_actions'], ['pager'])
        self.assertEqual(cfg['quiet_start'], '22:30:00')
        self.assertEqual(cfg['quiet_end'], '08:00:00')
        self.assertEqual(cfg['events'], ['attention', 'complete'])
        self.assertIs(cfg['urgent_override'], False)
        self.assertEqual(notifications.validate_config(None)[1], {})

    def test_invalid_values_return_codes_without_echoing_input(self):
        cfg, errors = notifications.validate_config({
            'targets': ['light.kitchen'], 'legacy_actions': ['send_message'], 'events': ['party'],
            'quiet_start': '25:00', 'quiet_end': 7, 'urgent_override': 'yes', 'surprise': 1})
        self.assertEqual(errors, {'targets': 'invalid_notify_entity', 'legacy_actions': 'invalid_notify_action',
                                  'events': 'invalid_event', 'quiet_start': 'invalid_time', 'quiet_end': 'invalid_time',
                                  'urgent_override': 'invalid_boolean', 'base': 'unknown_option'})
        self.assertNotIn('kitchen', json.dumps(errors))

    def test_destination_count_is_bounded(self):
        _, errors = notifications.validate_config({'targets': [f'notify.t{i}' for i in range(11)]})
        self.assertEqual(errors['base'], 'too_many_destinations')

    def test_non_mapping_and_non_list_rejected(self):
        self.assertEqual(notifications.validate_config(['x'])[1], {'base': 'invalid_config'})
        self.assertIn('targets', notifications.validate_config({'targets': 'notify.a'})[1])

    def test_manager_rejects_invalid_config(self):
        with self.assertRaises(ValueError):
            NotificationManager(FakeHass(), 'entry', {'events': ['nope']})


class QuietHoursTests(unittest.TestCase):
    def test_window_crossing_midnight(self):
        start, end = time(22), time(8)
        self.assertTrue(notifications.in_quiet_hours(time(23, 30), start, end))
        self.assertTrue(notifications.in_quiet_hours(time(0, 0), start, end))
        self.assertTrue(notifications.in_quiet_hours(time(7, 59, 59), start, end))
        self.assertFalse(notifications.in_quiet_hours(time(8, 0), start, end))
        self.assertTrue(notifications.in_quiet_hours(time(22, 0), start, end))
        self.assertFalse(notifications.in_quiet_hours(time(21, 59, 59), start, end))

    def test_same_day_window_and_disabled_window(self):
        self.assertTrue(notifications.in_quiet_hours(time(13), time(12), time(14)))
        self.assertFalse(notifications.in_quiet_hours(time(15), time(12), time(14)))
        self.assertFalse(notifications.in_quiet_hours(time(3), time(22), time(22)))

    def test_uses_home_assistant_time_zone_not_host_or_utc(self):
        hass = FakeHass('Asia/Tokyo')
        clock = Clock()
        clock.now = datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc)  # 22:30 Tokyo, 09:30 New York
        self.assertTrue(NotificationManager(hass, 'e', config(), clock=clock).is_quiet())
        hass.config.time_zone = 'America/New_York'
        self.assertFalse(NotificationManager(hass, 'e', config(), clock=clock).is_quiet())


class SendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = FakeHass()
        self.clock = Clock(local_hour=12)
        self.manager = NotificationManager(self.hass, 'Entry-01', config(), clock=self.clock)

    async def test_verified_recovery_dismisses_only_own_persistent_notice(self):
        await self.manager.async_send('attention', 'Mower needs help')
        notice=persistent(self.hass)[-1]['data']['notification_id']
        self.assertTrue(await self.manager.async_clear_attention())
        self.assertEqual(persistent(self.hass)[-1]['service'],'dismiss')
        self.assertEqual(persistent(self.hass)[-1]['data'],{'notification_id':notice})

    async def test_attention_reaches_every_destination_and_persistent(self):
        result = await self.manager.async_send('attention', 'Mower needs help in Zone A')
        self.assertEqual(result['status'], 'sent')
        self.assertEqual(result['delivered'], 4)
        calls = pushes(self.hass)
        self.assertEqual([c['target'] for c in calls[:2]], [{'entity_id': SECRET}, {'entity_id': 'notify.kitchen_display'}])
        self.assertEqual(calls[0]['service'], 'send_message')
        self.assertEqual(calls[2]['service'], 'legacy_pager')
        self.assertTrue(all(c['blocking'] for c in self.hass.services.calls))
        note = persistent(self.hass)
        self.assertEqual(len(note), 1)
        self.assertEqual(note[0]['data']['notification_id'], 'mower_coordinator_entry_01_attention')

    async def test_complete_has_no_persistent_notification(self):
        await self.manager.async_send('complete', 'Zone B finished')
        self.assertEqual(persistent(self.hass), [])
        self.assertEqual(len(pushes(self.hass)), 3)

    async def test_disabled_event_is_not_pushed_but_attention_still_persists(self):
        manager = NotificationManager(self.hass, 'e', config(events=['complete']), clock=self.clock)
        result = await manager.async_send('attention', 'Stuck')
        self.assertEqual(result['status'], 'suppressed_event')
        self.assertEqual(pushes(self.hass), [])
        self.assertEqual(len(persistent(self.hass)), 1)
        manager = NotificationManager(self.hass, 'e', config(events=['attention']), clock=self.clock)
        self.assertEqual((await manager.async_send('complete', 'Done'))['status'], 'suppressed_event')
        self.assertEqual(len(persistent(self.hass)), 1)

    async def test_quiet_hours_hold_push_but_keep_attention_visible(self):
        self.clock.advance(11 * 3600)  # 23:00 local
        result = await self.manager.async_send('attention', 'Paused overnight')
        self.assertEqual(result['status'], 'suppressed_quiet')
        self.assertEqual(pushes(self.hass), [])
        self.assertEqual(len(persistent(self.hass)), 1)
        self.assertEqual((await self.manager.async_send('complete', 'Done late'))['status'], 'suppressed_quiet')
        self.assertEqual(len(persistent(self.hass)), 1)

    async def test_urgent_breaks_quiet_hours_only_with_override(self):
        self.clock.advance(14 * 3600)  # 02:00 local
        self.assertEqual((await self.manager.async_send('attention', 'Trapped', urgent=True))['status'], 'suppressed_quiet')
        self.assertEqual(pushes(self.hass), [])
        manager = NotificationManager(self.hass, 'e', config(urgent_override=True), clock=self.clock)
        result = await manager.async_send('attention', 'Trapped again', urgent=True)
        self.assertEqual(result['status'], 'sent')
        self.assertTrue(pushes(self.hass)[0]['data']['title'].startswith('URGENT'))
        self.assertEqual((await manager.async_send('attention', 'Not urgent'))['status'], 'suppressed_quiet')

    async def test_one_failing_destination_does_not_stop_the_others(self):
        self.hass.services.fail[SECRET] = RuntimeError(f'push to {SECRET} failed token=abc123 https://example.invalid')
        result = await self.manager.async_send('attention', 'Check mower')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual((result['delivered'], result['failed']), (3, 1))
        self.assertEqual(result['last_error'], 'error:RuntimeError')
        self.assertEqual([c['target'] for c in pushes(self.hass)][0], {'entity_id': 'notify.kitchen_display'})

    async def test_hanging_destination_times_out_and_others_still_deliver(self):
        self.hass.services.hang.add(SECRET)
        original = notifications.SEND_TIMEOUT_SECONDS
        notifications.SEND_TIMEOUT_SECONDS = 0.05
        try:
            result = await asyncio.wait_for(self.manager.async_send('attention', 'Check'), 2)
        finally:
            notifications.SEND_TIMEOUT_SECONDS = original
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(self.manager.diagnostics()['destinations']['target_1']['last_error'], 'timeout')
        self.assertEqual(len(pushes(self.hass)), 2)

    async def test_missing_legacy_action_is_reported_not_called(self):
        self.hass.services.available.discard(('notify', 'legacy_pager'))
        result = await self.manager.async_send('complete', 'Done')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(self.manager.diagnostics()['destinations']['legacy_1'],
                         {'status': 'missing', 'last_error': 'service_missing', 'last_attempt': result['at']})
        self.assertNotIn('legacy_pager', [c['service'] for c in self.hass.services.calls])

    async def test_failed_persistent_notification_does_not_block_push(self):
        self.hass.services.fail['persistent_notification.create'] = OSError('disk')
        result = await self.manager.async_send('attention', 'Check')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(pushes(self.hass)), 3)

    async def test_send_never_raises_even_when_everything_fails(self):
        for key in (SECRET, 'notify.kitchen_display', 'notify.legacy_pager', 'persistent_notification.create'):
            self.hass.services.fail[key] = ValueError('boom')
        result = await self.manager.async_send('attention', 'Check')
        self.assertEqual((result['status'], result['delivered'], result['failed']), ('failed', 0, 4))
        self.assertEqual((await self.manager.async_send('unknown', 'x'))['status'], 'invalid_event')
        self.assertEqual((await self.manager.async_send('attention', '   '))['status'], 'invalid_message')
        self.manager._clock = lambda: 1 / 0  # internal fault: the guard still returns a result
        fault = await self.manager.async_send('attention', 'x')
        self.assertEqual((fault['status'], fault['last_error']), ('failed', 'error:ZeroDivisionError'))

    async def test_total_failure_stays_retryable(self):
        for key in (SECRET, 'notify.kitchen_display', 'notify.legacy_pager', 'persistent_notification.create'):
            self.hass.services.fail[key] = ValueError('down')
        await self.manager.async_send('attention', 'Check')
        self.hass.services.fail.clear()
        self.assertEqual((await self.manager.async_send('attention', 'Check'))['status'], 'sent')

    async def test_duplicates_are_suppressed_for_a_bounded_window(self):
        self.assertEqual((await self.manager.async_send('attention', 'Same'))['status'], 'sent')
        self.assertEqual((await self.manager.async_send('attention', 'Same', urgent=True))['status'], 'suppressed_duplicate')
        self.assertEqual((await self.manager.async_send('complete', 'Same'))['status'], 'sent')
        self.assertEqual((await self.manager.async_send('attention', 'Different'))['status'], 'sent')
        self.clock.advance(notifications.DEDUP_WINDOW_SECONDS)
        self.assertEqual((await self.manager.async_send('attention', 'Same'))['status'], 'sent')

    async def test_dedup_memory_is_bounded(self):
        for i in range(notifications.MAX_DEDUP_KEYS + 20):
            await self.manager.async_send('attention', f'm{i}', urgent=True)
        self.assertLessEqual(len(self.manager._recent), notifications.MAX_DEDUP_KEYS)

    async def test_rate_limit_bounds_routine_pushes_but_not_urgent(self):
        for i in range(notifications.RATE_LIMIT_COUNT):
            self.assertEqual((await self.manager.async_send('complete', f'done {i}'))['status'], 'sent')
        self.assertEqual((await self.manager.async_send('attention', 'one more'))['status'], 'suppressed_rate')
        self.assertEqual((await self.manager.async_send('attention', 'urgent one', urgent=True))['status'], 'sent')
        self.clock.advance(notifications.RATE_LIMIT_WINDOW_SECONDS)
        self.assertEqual((await self.manager.async_send('complete', 'later'))['status'], 'sent')

    async def test_user_test_bypasses_events_quiet_and_dedup_and_is_labelled(self):
        manager = NotificationManager(self.hass, 'e', config(events=[]), clock=self.clock)
        self.clock.advance(12 * 3600)  # midnight local
        first = await manager.async_send('attention', '', test=True)
        second = await manager.async_send('attention', '', test=True)
        self.assertEqual((first['status'], second['status']), ('test_sent', 'test_sent'))
        self.assertEqual(persistent(self.hass), [])
        for call in pushes(self.hass):
            self.assertIn('TEST', call['data']['title'])
            self.assertTrue(call['data']['message'].startswith(notifications.TEST_PREFIX))
        self.assertEqual(manager.diagnostics()['counts']['suppressed_quiet'], 0)

    async def test_test_without_destinations_uses_labelled_persistent_notification(self):
        manager = NotificationManager(self.hass, 'e', {'targets': [], 'legacy_actions': []}, clock=self.clock)
        result = await manager.async_send('complete', 'check', test=True)
        self.assertEqual(result['status'], 'test_sent')
        note = persistent(self.hass)[0]['data']
        self.assertIn('TEST', note['title'])
        self.assertTrue(note['notification_id'].endswith('_test'))

    async def test_send_nowait_runs_in_background_and_isolates_failures(self):
        self.hass.services.fail[SECRET] = RuntimeError('x')
        order = []
        task = self.manager.send_nowait('attention', 'Docking for rain', urgent=True)
        order.append('protective dock issued')
        result = await task
        self.assertEqual(order, ['protective dock issued'])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(self.hass.background, ['mower_coordinator_notify_attention'])

    async def test_cancellation_propagates(self):
        self.hass.services.hang.add(SECRET)
        task = asyncio.get_running_loop().create_task(self.manager.async_send('attention', 'x'))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_diagnostics_are_sanitized(self):
        self.hass.services.fail[SECRET] = RuntimeError(f'{SECRET} token=abc123')
        await self.manager.async_send('attention', 'Private message about Zone A')
        diag = self.manager.diagnostics()
        text = json.dumps(diag)
        for forbidden in (SECRET, 'kitchen_display', 'legacy_pager', 'abc123', 'Private message'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(diag['status'], 'partial')
        self.assertEqual(diag['last_error'], 'error:RuntimeError')
        self.assertEqual(diag['options']['target_count'], 2)
        self.assertEqual(set(diag['destinations']), {'target_1', 'target_2', 'legacy_1', 'persistent'})

    async def test_concurrent_duplicates_deliver_once(self):
        original = self.hass.services.async_call
        async def yielding_call(*args, **kwargs):
            await asyncio.sleep(0)
            return await original(*args, **kwargs)
        self.hass.services.async_call = yielding_call
        results = await asyncio.gather(*(self.manager.async_send('attention', 'Same event') for _ in range(5)))
        self.assertEqual(sum(r['status'] == 'suppressed_duplicate' for r in results), 4)
        self.assertEqual(len(pushes(self.hass)), 3)

    async def test_lifecycle_categories_are_delivered(self):
        manager = NotificationManager(self.hass, 'e', config(events=['started', 'resumed', 'charging', 'hold']), clock=self.clock)
        for event in ('started', 'resumed', 'charging', 'hold'):
            result = await manager.async_send(event, event)
            self.assertEqual(result['status'], 'sent')

    async def test_long_messages_are_clipped(self):
        await self.manager.async_send('complete', 'x' * 5000)
        self.assertEqual(len(pushes(self.hass)[0]['data']['message']), notifications.MAX_MESSAGE_LENGTH)


if __name__ == '__main__':
    unittest.main()
