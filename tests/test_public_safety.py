"""Regression checks for public commissioning and restart protections."""
import unittest
from jinja2 import Environment
from test_package import compile_package, fixture_settings, strings


def nodes(x):
    if isinstance(x, dict):
        yield x
        for v in x.values(): yield from nodes(v)
    elif isinstance(x, list):
        for v in x: yield from nodes(v)

class PublicSafetyTests(unittest.TestCase):
    def setUp(self):
        self.p=compile_package(fixture_settings())
        self.guard=next(x['value_template'] for x in nodes(self.p) if x.get('alias')=='Recheck operator, manual hold, units and freezing guard')
        self.env=Environment()
        self.home=True; self.hold=False; self.wind='mph'; self.weather='mph'; self.temp=60; self.tempunit='°F'; self.available=True
        self.env.globals.update(states=self.states,is_state=self.is_state,state_attr=self.attr,is_number=lambda x:isinstance(x,(int,float)))
    def states(self,e):
        if e.startswith('weather.'): return 'sunny' if self.available else 'unavailable'
        if e.endswith('bind_050'): return self.temp
        return 1
    def is_state(self,e,v):
        if e.startswith('person.'):return self.home
        if e=='input_boolean.mower_manual_hold':return not self.hold
        return True
    def attr(self,e,a):
        if e.startswith('weather.'):return self.weather
        if e.endswith('bind_050'):return self.tempunit
        return self.wind
    def allowed(self):return self.env.from_string(self.guard).render().strip()=='True'
    def test_valid_operator_and_units_allow_guard(self):self.assertTrue(self.allowed())
    def test_away_blocks(self):self.home=False;self.assertFalse(self.allowed())
    def test_manual_hold_blocks(self):self.hold=True;self.assertFalse(self.allowed())
    def test_metric_wind_blocks(self):
        for unit in ('m/s','km/h',None):self.wind=unit;self.assertFalse(self.allowed())
    def test_weather_unit_mismatch_blocks(self):self.weather='km/h';self.assertFalse(self.allowed())
    def test_weather_unavailable_blocks(self):self.available=False;self.assertFalse(self.allowed())
    def test_temperature_units_and_freezing_block(self):
        self.tempunit='°C';self.assertFalse(self.allowed())
        self.tempunit='°F';self.temp=32;self.assertFalse(self.allowed())
    def test_return_protection_survives_motion_disarm(self):
        names={'mower_obstruction_dock','mower_departure_safety','mower_start_rain_hold','mower_light_rain_safety','mower_orphan_battery_reserve','mower_roadside_orphan_return','mower_idle_but_not_charging'}
        for a in self.p['automation']:
            self.assertNotIn('initial_state',a)
            if a['id'] in names:self.assertNotIn('input_boolean.mower_package_enabled',str(a['conditions']))
    def test_static_safe_defaults(self):
        for n,v in [('high_wind_limit',25),('rain_hold_minutes',20),('recovery_target_battery',95),('roadside_stationary_limit_minutes',10)]:self.assertEqual(self.p['input_number']['mower_'+n]['initial'],v)
    def test_recovery_budget_persists_and_is_never_reset_by_automation(self):
        counter='input_number.mower_auto_resume_budget_used'
        self.assertNotIn('initial',self.p['input_number']['mower_auto_resume_budget_used'])
        writes=[n for n in nodes(self.p) if counter in str(n.get('target',{}))]
        self.assertEqual(len(writes),3)
        self.assertTrue(all(n['action']=='input_number.increment' for n in writes))
        gate=next(n['value_template'] for n in nodes(self.p) if n.get('alias')=='Persistent recovery budget must remain available')
        for count,expected in [('0',True),('2',True),('3',False),('unknown',False)]:
            self.assertEqual(self.env.from_string(gate).render(states=lambda _:count).strip()=='True',expected)
    def test_weather_is_bound_and_away_graduation_removed(self):
        text=' '.join(strings(self.p))
        self.assertNotIn('in states.weather',text)
        departure=next(a for a in self.p['automation'] if a['id']=='mower_departure_safety')
        self.assertNotIn('mower_intervention_free_batches',str(departure['conditions']))
        self.assertNotRegex(text,r"intervention_free_batches'\)\s*\|\s*int\(0\)\s*>=\s*5\s*or")
    def test_unstick_escape_requires_fresh_gps_after_observation(self):
        a=next(a for a in self.p['automation'] if a['id']=='mower_smart_auto_unstick')
        proof=next(n['physically_recovered'] for n in nodes(a) if 'physically_recovered' in n)
        self.assertIn('gps_work and as_timestamp(now()) - observation_started',proof)
        self.assertIn('>= 120',proof)
        self.assertIn('last_reported,0) <= 90',proof)
        self.assertNotIn('(physical_work or physical_movement_latched',proof)
