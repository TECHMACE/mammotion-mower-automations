"""Forecast service adapter prevents launch when the synthetic outlook is unsafe."""
from client import api
import time
from exercise_wizard import exercise
from exercise_recovery import POLICY, assert_count
from scenario_client import Lab

def run():
    lab=Lab()
    try:
        entry=exercise(recreate=True,rules_override=POLICY,bindings_override={'weather_entity':'weather.lab_weather'})
        lab.call('mower_simulator','reset')
        lab.fake(error='normal',forecast_rain=True)
        lab.options(entry,'safety_weather',{'forecast_enabled':True,'forecast_horizon_hours':3,'multipleweather_entities':['weather.lab_weather']})
        lab.arm()
        lab.observe(35,lambda:assert_count(lab,'start_mow',0))
        explanation=lab.value('sensor.lab_coordinator_explanation').lower()
        assert 'weather' in explanation or 'forecast' in explanation,explanation
        lab.disarm()
        lab.fake(forecast_rain=False)
        api('/api/config/config_entries/entry/'+entry+'/reload',{},lab.token)
        time.sleep(1)
        lab.arm()
        lab.wait(lambda:len(lab.commands('start_mow'))==1,50,'clear forecast launch')
        print('PASS: native hourlyforecast blocked unsafeoutlook; clear outlook allowed exactly one simulated launch',flush=True)
    finally:
        lab.disarm()
        lab.fake(mower='docked',activity='MODE_READY',charging=True,error='normal')

if __name__=='__main__':run()
