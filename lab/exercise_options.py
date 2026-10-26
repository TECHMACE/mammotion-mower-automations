"""Exercise options and delivery failure isolation using local capture targets."""
import time
from client import api,login

def run():
 t=login()
 entries=api('/api/config/config_entries/entry',token=t)
 entry=next(e for e in entries if e['domain']=='mower_coordinator')
 f=api('/api/config/config_entries/options/flow',{'handler':entry['entry_id']},t)
 assert f['type']=='menu',f
 def step(data):
  nonlocal f
  f=api('/api/config/config_entries/options/flow/'+f['flow_id'],data,t);return f
 assert step({'next_step_id':'notifications'})['step_id']=='notifications'
 data=dict(targets=['notify.lab_notification_capture'],legacy_actions=['notify.lab_capture'],events=['attention','complete'],quiet_start='00:00:00',quiet_end='23:59:00',urgent_override=False)
 assert step(data)['type']=='menu'
 assert step({'next_step_id':'review'})['step_id']=='review'
 assert step({'understood':True})['type']=='create_entry'
 time.sleep(1)
 def state(e):return api('/api/states/'+e,token=t)
 assert state('switch.lab_coordinator_automatic_control')['state']=='off'
 assert state('switch.lab_coordinator_hold_new_work')['state']=='on'
 def call(domain,service,data):return api(f'/api/services/{domain}/{service}',data,t)
 before=int(state('sensor.lab_notifications')['state'])
 call('button','press',{'entity_id':'button.lab_coordinator_send_test_notification'})
 time.sleep(.3)
 assert int(state('sensor.lab_notifications')['state'])==before+2
 call('mower_simulator','set_state',{'fail_notify':True})
 call('button','press',{'entity_id':'button.lab_coordinator_send_test_notification'})
 assert state('sensor.lab_coordinator_notification_delivery')['state']=='failed'
 assert state('switch.lab_coordinator_automatic_control')['state']=='off'
 call('mower_simulator','set_state',{'fail_notify':False})
 call('button','press',{'entity_id':'button.lab_coordinator_send_test_notification'})
 assert state('sensor.lab_coordinator_notification_delivery')['state']=='test_sent'
 print('Options reload disarmed; modern+legacy targets, explicit test during quiet hours, failure isolation and recovery passed')
if __name__=='__main__':run()
