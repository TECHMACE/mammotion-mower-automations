"""Exercise native setup forms against local HA; leaves a usable observe-only entry."""
import json,time
from client import api, login, PRIVATE

def exercise(recreate=False, rules_override=None, bindings_override=None):
 t=login()
 for _ in range(60):
  states=api("/api/states",token=t)
  if any(s["entity_id"]=="lawn_mower.lab_mower" for s in states):break
  time.sleep(1)
 entries=api('/api/config/config_entries/entry',token=t)
 existing=next((e for e in entries if e['domain']=='mower_coordinator'),None)
 if existing and recreate:
  saved=PRIVATE/'integration.json'
  assert saved.exists() and json.loads(saved.read_text())['entry_id']==existing['entry_id'], 'Refusing to replace an entry not created by this lab fixture'
  assert existing['title']=='Lab coordinator', 'Refusing to replace a renamed lab entry'
  api('/api/config/config_entries/entry/'+existing['entry_id'],token=t,method='DELETE')
  existing=None
 if existing:return existing['entry_id']
 f=api('/api/config/config_entries/flow',{'handler':'mower_coordinator','show_advanced_options':False},t)
 def step(data):
  nonlocal f
  f=api('/api/config/config_entries/flow/'+f['flow_id'],data,t)
  return f
 def expect_error(data,key):
  result=step(data);assert result['errors'].get(key),result
 expect_error({'name':'Lab coordinator','mower_entity':'lawn_mower.missing'},'mower_entity')
 result=step({'name':'Lab coordinator','mower_entity':'lawn_mower.lab_mower'})
 assert result.get('step_id')=='bindings',result
 bindings=dict(battery_entity='sensor.lab_battery',progress_entity='sensor.lab_progress',charging_entity='binary_sensor.lab_charging',activity_entity='sensor.lab_activity',error_entity='sensor.lab_error',rain_entity='binary_sensor.lab_rain',person_entity='person.lab_operator',tracker_entity='device_tracker.lab_mower',blade_time_entity='sensor.lab_blade_time',safety_entity='binary_sensor.lab_safety_clear',mileage_entity='sensor.lab_mileage',rtk_entity='sensor.lab_rtk',recent_fault_code_entity='sensor.lab_recent_fault_code',recent_fault_time_entity='sensor.lab_recent_fault_time')
 bindings.update(bindings_override or {})
 expect_error({**bindings,'battery_entity':'sensor.missing'},'battery_entity')
 assert step(bindings)['step_id']=='zone'
 zone=dict(name='First lawn',area_entities=['switch.lab_area_1'],angles='0,90',spacing_cm=11,perimeter_laps=2,interval_days=3,minimum_battery=80)
 expect_error({**zone,'angles':'not an angle'},'base')
 assert step(zone)['step_id']=='more_areas'
 assert step({'add_another':True})['step_id']=='zone'
 expect_error({**zone,'name':'Overlapping lawn'},'base')
 assert step({**zone,'name':'Second lawn','area_entities':['switch.lab_area_2'],'angles':'45,135'})['step_id']=='more_areas'
 assert step({'add_another':False})['step_id']=='rules'
 rules=dict(start_time='00:00:00',end_time='23:59:00',reserve_battery=25,resume_battery=85,weather_max_age=1800,wind_limit_mps=10,auto_recovery=False,allow_handoff=False)
 rules.update(rules_override or {})
 expect_error({**rules,'start_time':'20:00:00','end_time':'09:00:00'},'base')
 result=step(rules)
 if result.get('step_id')=='advanced':
  result=step({'configure_advanced':False})
 assert result['step_id']=='notifications',result
 notifications=dict(targets=['notify.lab_notification_capture'],legacy_actions=[],events=['attention','complete','started','resumed','charging','hold'],quiet_start='23:00:00',quiet_end='00:00:00',urgent_override=False)
 expect_error({**notifications,'targets':['notify.missing']},'targets')
 assert step(notifications)['step_id']=='review'
 expect_error({'understood':False},'base')
 result=step({'understood':True})
 assert result['type']=='create_entry',result
 entry_id=result['result']['entry_id']
 PRIVATE.joinpath('integration.json').write_text(json.dumps({'entry_id':entry_id}))
 for _ in range(30):
  entries=api('/api/config/config_entries/entry',token=t)
  e=next(e for e in entries if e['entry_id']==entry_id)
  if e['state']=='loaded':break
  time.sleep(.5)
 assert e['state']=='loaded',e
 print('Native wizard: all steps, invalid input checks and two arbitrary zones passed')
 return entry_id

if __name__=='__main__':print('Lab entry:',exercise())
