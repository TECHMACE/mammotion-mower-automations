import copy
import json
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build import compile_package, load, TOKEN

def fixture_settings():
    result = {}
    for key, spec in load(ROOT / 'source/bindings.json').items():
        if spec['kind'] == 'external': result[key] = spec['domain']+'.fixture_'+key.lower()
        if spec['kind'] == 'map_hash': result[key] = str(100+int(key.rsplit('_', 1)[1]))
        if spec['kind'] == 'device': result[key] = '0'*32
        if spec['kind'] == 'notification_id': result[key] = 'fixture_'+key.lower()
    return result

def strings(obj):
    if isinstance(obj, dict):
        for v in obj.values(): yield from strings(v)
    elif isinstance(obj, list):
        for v in obj: yield from strings(v)
    elif isinstance(obj, str): yield obj

class BuildTests(unittest.TestCase):
    def setUp(self):
        self.settings=fixture_settings()

    def test_complete_build(self):
        p=compile_package(self.settings)
        self.assertEqual(len(p['automation']),26)
        self.assertEqual(len(p['script']),8)
        self.assertNotIn('@@',json.dumps(p))

    def test_missing_binding_rejected(self):
        self.settings.pop(next(iter(self.settings)))
        with self.assertRaises(ValueError):compile_package(self.settings)

    def test_empty_binding_rejected(self):
        self.settings[next(iter(self.settings))]=''
        with self.assertRaises(ValueError):compile_package(self.settings)

    def test_wrong_domain_rejected(self):
        key=next(k for k,v in load(ROOT/'source/bindings.json').items() if v.get('domain')=='person')
        self.settings[key]='switch.fixture'
        with self.assertRaises(ValueError):compile_package(self.settings)

    def test_template_injection_rejected(self):
        key=next(iter(self.settings));self.settings[key]="sensor.x' }} {{ evil }}"
        with self.assertRaises(ValueError):compile_package(self.settings)

    def test_duplicate_map_hash_rejected(self):
        self.settings['MAP_HASH_2']=self.settings['MAP_HASH_1']
        with self.assertRaises(ValueError):compile_package(self.settings)

    def test_device_id_rejected(self):
        self.settings['DEVICE_1']='not-a-device'
        with self.assertRaises(ValueError):compile_package(self.settings)

    def test_initially_disabled(self):
        p=compile_package(self.settings)
        self.assertFalse(p['input_boolean']['mower_package_enabled']['initial'])
        self.assertTrue(p['input_boolean']['mower_manual_hold']['initial'])
        for a in p['automation']:
            self.assertNotIn('initial_state',a)

    def test_checkpoint_restores(self):
        p=compile_package(self.settings)
        for key in ('mower_owner_checkpoint','mower_resume_progress'):
            self.assertNotIn('initial',p['input_number'][key])
        self.assertNotIn('initial',p['input_text']['mower_job_token'])

    def test_invalid_helper_rejected(self):
        with self.assertRaises(ValueError):compile_package(self.settings,{'input_text.unknown':{'initial':'x'}})

    def test_manual_hold_cannot_be_removed_by_override(self):
        with self.assertRaises(ValueError):compile_package(self.settings,{'input_boolean.mower_manual_hold':{'initial':False}})

    def test_jinja_syntax_all_templates(self):
        env=Environment()
        count=0
        for s in strings(compile_package(self.settings)):
            if '{{' in s or '{%' in s:
                env.parse(s);count+=1
        self.assertGreater(count,300)

    def test_binding_inventory_complete(self):
        source=json.dumps(load(ROOT/'source/configurations.json'))+json.dumps(load(ROOT/'source/helpers.json'))
        refs=set(TOKEN.findall(source));specs=load(ROOT/'source/bindings.json')
        self.assertFalse(refs-set(specs))

    def test_motion_dispatch_rechecks_enable(self):
        count=0
        def walk(o):
            nonlocal count
            if isinstance(o,list):
                for i,v in enumerate(o):
                    if isinstance(v,dict) and v.get('action') in ('mammotion.start_mow','lawn_mower.start_mowing'):
                        self.assertGreater(i,0)
                        self.assertEqual(o[i-1].get('entity_id'),'input_boolean.mower_package_enabled')
                        self.assertEqual(o[i-1].get('state'),'on');count+=1
                    walk(v)
            elif isinstance(o,dict):
                for v in o.values():walk(v)
        walk(compile_package(self.settings))
        self.assertGreater(count,3)

    def test_map_hash_tokens_match_native_area_numbers(self):
        p=json.dumps(load(ROOT/'source/configurations.json'))
        for i in range(1,7):self.assertIn(f"'Area {i}': '@@MAP_HASH_{i}@@'",p)

    def test_example_settings_exact_required_keys(self):
        self.assertEqual(set(load(ROOT/'settings.example.json')),set(self.settings))

    def test_empty_selectors_survive_package_merge(self):
        for script in compile_package(self.settings)['script'].values():
            for field in script.get('fields',{}).values():
                for config in field.get('selector',{}).values():self.assertNotEqual(config,{})

class RecoveryTests(unittest.TestCase):
    """Evaluate the ACTUAL released recheck template with synthetic HA state."""
    def setUp(self):
        self.package=compile_package(fixture_settings())
        self.config=next(a for a in self.package['automation'] if a['id']=='mower_smart_auto_unstick')
        self.template=next(a for a in self.config['actions'] if a.get('alias')=='Recheck physical progress and cancellation after telemetry grace')['if'][0]['value_template']
        specs=load(ROOT/'source/bindings.json');settings=fixture_settings()
        self.external={s['purpose']:settings[k] for k,s in specs.items() if s['kind']=='external'}
        self.state={'script.mower_run_owned_area':'on','input_text.mower_job_token':'test-owner','input_select.mower_active_area':'Zone B','input_boolean.mower_manual_hold':'off','input_boolean.mower_roadside_return_due':'off','input_boolean.mower_owner_cut_proved':'off','input_boolean.mower_batch_cut_complete':'off'}
        for purpose,value in [('sensor.mower_progress','94'),('sensor.mower_blade_used_time','10'),('sensor.mower_total_mileage','100'),('sensor.mower_activity_mode','MODE_PAUSE'),('sensor.mower_last_error_code','1201'),('binary_sensor.mower_charging','off'),('lawn_mower.mower','paused'),('device_tracker.mower_position','home')]:self.state[self.external[purpose]]=value
        self.attrs={self.external['device_tracker.mower_position']:{'latitude':1.0,'longitude':1.0}}
        self.vars=dict(physical_area='Zone B',owner_token='test-owner',proof_lat=1.0,proof_lon=1.0,proof_mileage=100,proof_progress=94,proof_blade=10,proof_gps_valid=True,proof_mileage_valid=True,proof_progress_valid=True,proof_blade_valid=True)
        self.env=Environment(undefined=StrictUndefined)
        self.env.filters['bool']=lambda v,default=False: v if isinstance(v,bool) else str(v).lower() in ('true','on','1')
        self.env.globals.update(states=lambda e:self.state.get(e,'unknown'),is_state=lambda e,v:self.state.get(e,'unknown')==v,state_attr=lambda e,a:self.attrs.get(e,{}).get(a),is_number=lambda v: isinstance(v,(int,float)) or isinstance(v,str) and v.replace('.','',1).isdigit(),as_timestamp=lambda v,default=0:default,now=lambda:datetime(2000,1,2,tzinfo=timezone.utc))

    def aborted(self):return self.env.from_string(self.template).render(**self.vars).strip()=='True'
    def test_stationary_same_owner_proceeds(self):self.assertFalse(self.aborted())
    def test_progress_cancels(self):self.state[self.external['sensor.mower_progress']]='95';self.assertTrue(self.aborted())
    def test_blade_activity_cancels(self):self.state[self.external['sensor.mower_blade_used_time']]='10.1';self.assertTrue(self.aborted())
    def test_position_change_cancels(self):self.attrs[self.external['device_tracker.mower_position']]['latitude']=1.001;self.assertTrue(self.aborted())
    def test_mileage_change_cancels(self):self.state[self.external['sensor.mower_total_mileage']]='120';self.assertTrue(self.aborted())
    def test_owner_change_cancels(self):self.state['input_text.mower_job_token']='different';self.assertTrue(self.aborted())
    def test_manual_hold_cancels(self):self.state['input_boolean.mower_manual_hold']='on';self.assertTrue(self.aborted())
    def test_charging_cancels(self):self.state[self.external['binary_sensor.mower_charging']]='on';self.assertTrue(self.aborted())
    def test_returning_cancels(self):self.state[self.external['lawn_mower.mower']]='returning';self.assertTrue(self.aborted())
    def test_safety_lock_cancels(self):self.state[self.external['sensor.mower_activity_mode']]='MODE_LOCK';self.assertTrue(self.aborted())
    def test_other_recovery_cancels(self):self.attrs['automation.mower_obstruction_dock']={'current':1};self.assertTrue(self.aborted())

    def test_actual_grace_loop_bound_and_freshness(self):
        action=next(a for a in self.config['actions'] if a.get('alias','').startswith('Allow late telemetry'))
        template=action['repeat']['while'][0]['value_template']
        tracker=self.external['device_tracker.mower_position'].split('.')[1]
        for index,report,expected in [(1,900,True),(6,900,True),(7,900,False),(1,1001,False),(1,800,True)]:
            states=SimpleNamespace(device_tracker=SimpleNamespace(**{tracker:SimpleNamespace(last_reported=report)}))
            result=Environment().from_string(template).render(repeat={'index':index},states=states,stall_observation_started=1000,as_timestamp=lambda x,default=0:x,now=lambda:1060)
            self.assertEqual(result.strip()=='True',expected)

if __name__=='__main__':unittest.main()
