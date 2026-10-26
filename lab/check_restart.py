"""Restart only the named isolated lab; assert loaded state, saved work and no motion."""
import subprocess
import time
from pathlib import Path
from client import api, login

def run():
    token = login()
    def state(entity):
        return api('/api/states/' + entity, token=token, timeout=2)['state']
    checkpoint = float(state('sensor.lab_coordinator_saved_progress'))
    queue = state('sensor.lab_coordinator_remaining_areas')
    retries = state('sensor.lab_coordinator_recovery_attempts')
    subprocess.run(['docker', 'compose', '-f', str(Path(__file__).parent / 'compose.yaml'), 'restart', 'homeassistant'], check=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            entries = api('/api/config/config_entries/entry', token=token, timeout=2)
            entry = next(e for e in entries if e['domain'] == 'mower_coordinator')
            if entry['state'] == 'loaded' and state('sensor.lab_coordinator_status') == 'observe':
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        raise AssertionError('Coordinator did not load after full lab restart')
    assert state('switch.lab_coordinator_automatic_control') == 'off'
    assert state('switch.lab_coordinator_hold_new_work') == 'on'
    assert float(state('sensor.lab_coordinator_saved_progress')) == checkpoint
    assert state('sensor.lab_coordinator_remaining_areas') == queue
    assert state('sensor.lab_coordinator_recovery_attempts') == retries
    retry_attributes = api('/api/states/sensor.lab_coordinator_recovery_attempts', token=token)['attributes']
    assert all(key in retry_attributes for key in ('resume_attempts','return_attempts','limit_per_kind')), retry_attributes
    assert int(state('sensor.lab_commands')) == 0
    print('Full HA restart: integration loaded, checkpoint/queue/retry count retained, disarmed and no device command')

if __name__ == '__main__':
    run()
