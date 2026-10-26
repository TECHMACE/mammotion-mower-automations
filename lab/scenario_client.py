"""Helpers for native Home Assistant acceptance scenarios in the fixed loopback lab."""
import time
from client import api, login

class Lab:
    def __init__(self):
        self.token = login()

    def call(self, domain, action, data=None):
        return api(f'/api/services/{domain}/{action}', data or {}, self.token)

    def state(self, entity):
        return api('/api/states/' + entity, token=self.token)

    def value(self, entity):
        return self.state(entity)['state']

    def fake(self, **fields):
        self.call('mower_simulator', 'set_state', fields)
        time.sleep(.15)
        # A later telemetry sample follows the cutting/movement report.
        self.call('mower_simulator', 'set_state')
        time.sleep(.15)

    def commands(self, action=None):
        records = self.state('sensor.lab_commands')['attributes']['records']
        return [record for record in records if action is None or record['action'] == action]

    def wait(self, predicate, timeout=15, message='condition', heartbeat=True):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            if heartbeat:
                self.call('mower_simulator', 'set_state')
            time.sleep(.5)
        raise AssertionError(f'Timed out waiting for {message}; status={self.value("sensor.lab_coordinator_status")}; explanation={self.value("sensor.lab_coordinator_explanation")}')

    def observe(self, seconds, invariant=None):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.fake()
            if invariant:
                invariant()
            time.sleep(.5)

    def press(self, suffix):
        self.call('button', 'press', {'entity_id': 'button.lab_coordinator_' + suffix})

    def disarm(self):
        self.call('switch', 'turn_off', {'entity_id': 'switch.lab_coordinator_automatic_control'})
        self.call('switch', 'turn_on', {'entity_id': 'switch.lab_coordinator_hold_new_work'})

    def arm(self):
        self.press('send_test_notification')
        self.press('confirm_test_notification_received')
        self.press('confirm_setup_and_competing_schedules_off')
        self.call('switch', 'turn_off', {'entity_id': 'switch.lab_coordinator_hold_new_work'})
        self.call('switch', 'turn_on', {'entity_id': 'switch.lab_coordinator_automatic_control'})

    def options(self, entry_id, section, overrides):
        flow = api('/api/config/config_entries/options/flow', {'handler': entry_id}, self.token)
        url = '/api/config/config_entries/options/flow/' + flow['flow_id']
        form = api(url, {'next_step_id': section}, self.token)
        assert form.get('step_id') == section, form
        data = {item['name']: item['default'] for item in form['data_schema'] if 'default' in item}
        data.update(overrides)
        result = api(url, data, self.token)
        assert result['type'] == 'menu', result
        review = api(url, {'next_step_id': 'review'}, self.token)
        assert review['step_id'] == 'review', review
        result = api(url, {'understood': True}, self.token)
        assert result['type'] == 'create_entry', result
        time.sleep(1)
        self.wait(lambda: self.value('switch.lab_coordinator_automatic_control') == 'off', message='options reload disarmed')
