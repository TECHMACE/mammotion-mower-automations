#!/usr/bin/env python3
"""Verify the isolated lab and simulator only; hardcoded loopback, no HA credentials from environment."""
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lab'))
from client import api, login

def docker(*args):
    return subprocess.check_output(['docker',*args],text=True)

def isolation():
    item=json.loads(docker('inspect','mower-coordinator-lab'))[0]
    assert item['HostConfig']['NetworkMode'] != 'host'
    assert item['HostConfig']['CapDrop'] == ['ALL']
    assert not item['HostConfig']['Privileged'] and not item['HostConfig']['Devices']
    assert not item['NetworkSettings']['Ports'].get('8123/tcp')
    networks=item['NetworkSettings']['Networks']
    assert len(networks)==1
    for name in networks:
        assert json.loads(docker('network','inspect',name))[0]['Internal'] is True
    routes=docker('exec','mower-coordinator-lab','cat','/proc/net/route')
    assert all(line.split()[1] != '00000000' for line in routes.splitlines()[1:]),routes
    probe='''import socket,json
result={}
for host,port in [('1.1.1.1',443),('192.0.2.1',8123),('host.docker.internal',8123)]:
 try:
  with socket.create_connection((host,port),timeout=1): result[host]='CONNECTED'
 except OSError as err: result[host]=type(err).__name__
print(json.dumps(result))
'''
    result=json.loads(docker('exec','mower-coordinator-lab','python3','-c',probe))
    assert 'CONNECTED' not in result.values(),result
    ui=json.loads(docker('inspect','mower-coordinator-lab-ui'))[0]
    assert ui['HostConfig']['PortBindings']['8123/tcp'][0]['HostIp']=='127.0.0.1'
    assert len(ui['Mounts'])==1 and ui['Mounts'][0]['Destination']=='/proxy.py'
    return result

def main():
    result=isolation()
    token=login()
    states={s['entity_id']:s for s in api('/api/states',token=token)}
    assert states.get('switch.lab_coordinator_automatic_control',{}).get('state','off') == 'off', 'Disarm the lab coordinator before simulator smoke tests'
    required=['lawn_mower.lab_mower','sensor.lab_battery','sensor.lab_progress','sensor.lab_activity','sensor.lab_error','binary_sensor.lab_charging','binary_sensor.lab_rain','switch.lab_area_1','person.lab_operator','device_tracker.lab_mower','notify.lab_notification_capture','sensor.lab_rtk','sensor.lab_mileage','sensor.lab_recent_fault_code','sensor.lab_recent_fault_time','weather.lab_weather']
    assert all(e in states for e in required),set(required)-set(states)
    def call(domain,service,data=None):return api(f'/api/services/{domain}/{service}',data or {},token)
    def state(entity):return api('/api/states/'+entity,token=token)
    call('mower_simulator','reset')
    call('mammotion','start_mow',{'entity_id':'lawn_mower.lab_mower','areas':['switch.lab_area_1'],'toward':90,'start_progress':32})
    assert state('lawn_mower.lab_mower')['state']=='mowing'
    call('mower_simulator','tick',{'progress':8})
    assert float(state('sensor.lab_progress')['state'])==40
    call('lawn_mower','dock',{'entity_id':'lawn_mower.lab_mower'})
    assert state('lawn_mower.lab_mower')['state']=='returning'
    call('lawn_mower','dock',{'entity_id':'lawn_mower.lab_mower'})
    assert state('lawn_mower.lab_mower')['state']=='paused', 'Native Dock toggles return off while returning'
    call('lawn_mower','dock',{'entity_id':'lawn_mower.lab_mower'})
    assert state('lawn_mower.lab_mower')['state']=='returning'
    call('mower_simulator','tick')
    assert state('binary_sensor.lab_charging')['state']=='on'
    call('notify','send_message',{'entity_id':'notify.lab_notification_capture','message':'SIMULATION ONLY: notification test'})
    assert int(state('sensor.lab_notifications')['state'])==1
    call('mower_simulator','reset')
    call('mower_simulator','set_state',{'delay_ack':True})
    call('mammotion','start_mow',{'entity_id':'lawn_mower.lab_mower','areas':['switch.lab_area_2']})
    assert state('lawn_mower.lab_mower')['state']=='docked'
    assert int(state('sensor.lab_commands')['state'])==1
    call('mower_simulator','reset')
    print(json.dumps({'isolation':result,'simulator_checks':'passed','production_access':'none','physical_validation':False},indent=2))
if __name__=='__main__':main()
