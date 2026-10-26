"""Native-HA runtime scenario acceptance tests, fake mower only."""
import time
from client import api,login
from exercise_wizard import exercise

def run(from_checkpoint=False, fresh=False, map_change=False):
 token=login();entry=exercise(recreate=fresh)
 def call(domain,service,data=None):return api(f'/api/services/{domain}/{service}',data or {},token)
 def state(e):return api('/api/states/'+e,token=token)
 def set_fake(**fields):
  call('mower_simulator','set_state',fields);time.sleep(.2)
  call('mower_simulator','set_state',{});time.sleep(.2)
 def wait(e,expected,seconds=10):
  for _ in range(int(seconds*2)):
   s=state(e)
   if s['state']==expected or (expected.replace('.','',1).isdigit() and float(s['state'])==float(expected)):return s
   time.sleep(.5)
  raise AssertionError((e,expected,s))
 def press(suffix):call('button','press',{'entity_id':'button.lab_coordinator_'+suffix})
 if not from_checkpoint:
  call('mower_simulator','reset')
  assert int(state('sensor.lab_commands')['state'])==0
  assert state('switch.lab_coordinator_automatic_control')['state']=='off'
  press('send_test_notification');time.sleep(.5)
  assert int(state('sensor.lab_notifications')['state'])==1
  assert 'TEST' in state('sensor.lab_notifications')['attributes']['records'][0]['message']
  press('confirm_test_notification_received')
  press('confirm_setup_and_competing_schedules_off')
  assert state('sensor.lab_coordinator_commissioning')['attributes']['steps']['setup_confirmed']
  set_fake(delay_ack=True)
  call('switch','turn_off',{'entity_id':'switch.lab_coordinator_hold_new_work'})
  call('switch','turn_on',{'entity_id':'switch.lab_coordinator_automatic_control'})
  print('Armed fake mower; waiting for charging stability...',flush=True)
  for n in range(75):
   if int(state('sensor.lab_commands')['state'])>=1:break
   call('mower_simulator','set_state',{})
   time.sleep(1)
  commands=state('sensor.lab_commands')['attributes']['records']
  assert len([c for c in commands if c['action']=='start_mow'])==1,commands
  for _ in range(3):set_fake()
  assert len([c for c in state('sensor.lab_commands')['attributes']['records'] if c['action']=='start_mow'])==1
  print('Delayed acknowledgement: exactly one dispatch',flush=True)
  set_fake(delay_ack=False,mower='mowing',activity='MODE_WORKING',charging=False,progress=10,blade_time=10)
  wait('sensor.lab_coordinator_status','mowing')
  set_fake(progress=55,blade_time=60)
  wait('sensor.lab_coordinator_saved_progress','55')
 if map_change:
  before=len([c for c in state('sensor.lab_commands')['attributes']['records'] if c['action']=='start_mow'])
  set_fake(no_go_revision=1)
  wait('sensor.lab_coordinator_status','quarantined')
  assert float(state('sensor.lab_coordinator_saved_progress')['state'])==55
  assert len([c for c in state('sensor.lab_commands')['attributes']['records'] if c['action']=='start_mow'])==before
  api('/api/config/config_entries/entry/'+entry+'/reload',{},token)
  time.sleep(1)
  assert state('switch.lab_coordinator_automatic_control')['state']=='off'
  assert float(state('sensor.lab_coordinator_saved_progress')['state'])==55
  assert len([c for c in state('sensor.lab_commands')['attributes']['records'] if c['action']=='start_mow'])==before
  print('Same-area-ID no-go geometry change quarantined checkpoint55; reload preserved checkpoint and disarmed; no dispatch',flush=True)
  return
 set_fake(battery=25,blade_time=65)
 wait('lawn_mower.lab_mower','returning')
 assert float(state('sensor.lab_coordinator_saved_progress')['state'])==55
 print('Progress55 saved and reserve return observed',flush=True)
 set_fake(mower='docked',activity='MODE_READY',charging=True,battery=40)
 wait('sensor.lab_coordinator_status','charging')
 set_fake(battery=90)
 print('Waiting for stable charging before checkpoint resume...',flush=True)
 for n in range(75):
  starts=[c for c in state('sensor.lab_commands')['attributes']['records'] if c['action']=='start_mow']
  if len(starts)>=2:break
  call('mower_simulator','set_state',{})
  time.sleep(1)
 starts=[c for c in state('sensor.lab_commands')['attributes']['records'] if c['action']=='start_mow']
 assert len(starts)==2,starts
 assert starts[-1]['data']['start_progress']==55,starts[-1]
 set_fake(progress=56,blade_time=70)
 wait('sensor.lab_coordinator_status','mowing')
 set_fake(progress=100,blade_time=120,mower='idle',activity='MODE_READY')
 time.sleep(1)
 steps=state('sensor.lab_coordinator_commissioning')['attributes']['steps']
 assert all(steps[k] for k in ['launch_observed','completion_observed','charging_observed']),steps
 print('Checkpoint55 resumed once and completion recorded',flush=True)
 call('switch','turn_off',{'entity_id':'switch.lab_coordinator_automatic_control'})
 call('switch','turn_on',{'entity_id':'switch.lab_coordinator_hold_new_work'})
 set_fake(mower='docked',activity='MODE_READY',charging=True)
 print('Runtime scenario passed; lab left disarmed',flush=True)
if __name__=='__main__':
 import sys
 try:
  run('--from-checkpoint' in sys.argv, '--fresh' in sys.argv, '--map-change' in sys.argv)
 finally:
  token=login()
  api('/api/services/switch/turn_off',{'entity_id':'switch.lab_coordinator_automatic_control'},token)
  api('/api/services/switch/turn_on',{'entity_id':'switch.lab_coordinator_hold_new_work'},token)
  api('/api/services/mower_simulator/set_state',{'mower':'docked','activity':'MODE_READY','charging':True},token)
