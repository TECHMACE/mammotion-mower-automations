"""Actual HA acceptance of bounded in-place recovery and charger-free handoff.

All commands target the isolated synthetic device. Timers run in real time.
"""
from datetime import datetime, timezone
from exercise_wizard import exercise
from scenario_client import Lab

POLICY = dict(auto_recovery=True, allow_handoff=True, charging_stable_seconds=30,
              recovery_observation_seconds=30, recovery_grace_seconds=15,
              recovery_cooldown=30, ack_timeout=30, return_timeout=120,
              max_retries=2, handoff_minimum_battery=60)

def assert_count(lab, action, expected):
    records = lab.commands(action)
    assert len(records) == expected, (action, expected, records)

def prepare(lab):
    entry = exercise(recreate=True, rules_override=POLICY)
    lab.call('mower_simulator', 'reset')
    lab.fake(error='normal')
    lab.arm()
    lab.wait(lambda: len(lab.commands('start_mow')) == 1, 50, 'first launch')
    lab.fake(mower='mowing', activity='MODE_WORKING', charging=False,
             progress=35, blade_time=15, mileage=15)
    lab.wait(lambda: float(lab.value('sensor.lab_coordinator_saved_progress')) == 35, message='owned checkpoint')
    return entry

def recovery_handoff(lab):
    prepare(lab)
    lab.fake(mower='paused', activity='MODE_PAUSE', delay_ack=True)
    lab.observe(20, lambda: assert_count(lab, 'start_mowing', 0))
    # Delayed GPS/mileage arrives before the full observation/grace interval.
    lab.fake(latitude=40.0001, mileage=30)
    lab.observe(20, lambda: assert_count(lab, 'start_mowing', 0))
    lab.wait(lambda: len(lab.commands('start_mowing')) == 1, 60, 'stationary in-place recovery')
    assert_count(lab, 'start_mow', 1)
    assert_count(lab, 'dock', 0)
    assert float(lab.value('sensor.lab_coordinator_saved_progress')) == 35
    lab.observe(3, lambda: assert_count(lab, 'start_mowing', 1))
    lab.fake(delay_ack=False, mower='mowing', activity='MODE_WORKING', progress=36, blade_time=16)
    lab.wait(lambda: lab.value('sensor.lab_coordinator_status') == 'mowing', message='resume acknowledgement')
    assert int(float(lab.value('sensor.lab_coordinator_recovery_attempts'))) == 1
    lab.fake(progress=100, blade_time=90, mower='idle', activity='MODE_READY')
    lab.wait(lambda: len(lab.commands('start_mow')) == 2, message='charger-free next area')
    assert_count(lab, 'dock', 0)
    starts = lab.commands('start_mow')
    assert starts[1]['data']['areas'] == ['switch.lab_area_2'], starts
    assert starts[1]['data']['start_progress'] == 0, starts
    assert starts[1]['data']['toward'] == 45, starts
    print('PASS: delayed motion cancelled recovery; one native Resume retained35%; nextarea dispatched correctprofile with zero docks', flush=True)

def return_budget(lab):
    prepare(lab)
    lab.fake(battery=25)
    lab.wait(lambda: len(lab.commands('dock')) == 1, message='reserve return')
    for expected in (2, 3):
        lab.fake(mower='returning', activity='MODE_RETURNING', recent_fault_code=1214,
                 recent_fault_time=datetime.now(timezone.utc).isoformat())
        lab.wait(lambda: len(lab.commands('dock')) == expected, 100, 'bounded return retry')
        # A brief genuine travel report must not replenish the persisted budget.
        lab.fake(mower='returning', activity='MODE_RETURNING', mileage=expected * 30,
                 latitude=40 + expected * .0001)
        assert float(lab.value('sensor.lab_coordinator_saved_progress')) == 35
    lab.fake(mower='returning', activity='MODE_RETURNING', recent_fault_code=1214,
             recent_fault_time=datetime.now(timezone.utc).isoformat())
    lab.wait(lambda: lab.value('sensor.lab_coordinator_status') == 'attention', 100, 'exhausted return budget')
    assert_count(lab, 'dock', 3)
    assert_count(lab, 'pause', 2)
    assert_count(lab, 'start_mow', 1)
    assert_count(lab, 'start_mowing', 0)
    print('PASS: reserve return checkpoint retained; two pause-then-dock return retries despite brief movement; exhaustedbudget stopped commands', flush=True)

def run(mode):
    lab = Lab()
    try:
        (return_budget if mode == 'return' else recovery_handoff)(lab)
    finally:
        lab.disarm()
        lab.fake(mower='docked', activity='MODE_READY', charging=True, error='normal')

if __name__ == '__main__':
    import sys
    run(sys.argv[1] if len(sys.argv) > 1 else 'handoff')
