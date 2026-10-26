"""Native HA prelaunch gates with valid fake telemetry and configured weather."""
from exercise_wizard import exercise
from exercise_recovery import POLICY, assert_count
from scenario_client import Lab

def run():
    lab = Lab()
    try:
        entry=exercise(recreate=True, rules_override=POLICY,
                 bindings_override={'weather_entity':'weather.lab_weather'})
        lab.options(entry,'safety_weather',{'rain_dry_minutes':0})
        lab.call('mower_simulator','reset')
        lab.fake(error='normal',rain=True)
        lab.arm()
        # Allow charging stability to mature while rain blocks launch; a timer
        # alone must not be the reason these subsequent gates produce no start.
        lab.observe(35, lambda: assert_count(lab,'start_mow',0))
        for fields in [
            {'rain':False,'operator_home':False},
            {'operator_home':True,'weather':'pouring'},
            {'weather':'sunny','battery':20},
            {'battery':100,'safety_clear':False},
        ]:
            lab.fake(**fields)
            lab.observe(2, lambda: assert_count(lab,'start_mow',0))
            assert_count(lab,'start_mowing',0)
            print('Gate',fields,'=>',lab.value('sensor.lab_coordinator_explanation'),flush=True)
        assert float(lab.value('sensor.lab_coordinator_saved_progress')) == 0
        print('PASS: rain, absentoperator, unsafeweather, lowbattery and physicalsafety vetoed launch/resume',flush=True)
    finally:
        lab.disarm()
        lab.fake(mower='docked',activity='MODE_READY',charging=True,error='normal')

if __name__ == '__main__':
    run()
