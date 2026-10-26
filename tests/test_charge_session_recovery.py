import json,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from jinja2 import Environment
from test_package import compile_package, fixture_settings
class States:
 def __init__(self,d,charging): self.d=d; self.binary_sensor=SimpleNamespace(fixture_bind_029=SimpleNamespace(last_changed=charging))
 def __call__(self,k):return self.d.get(k,'unknown')
class RepairTests(unittest.TestCase):
 def setUp(self):
  self.package=compile_package(fixture_settings());self.c=next(a for a in self.package['automation'] if a['id']=='mower_owner_reconcile');self.t=self.c['actions'][2]['choose'][1]['conditions'][0]['value_template']
  self.now=datetime.fromisoformat('2026-10-26T09:00:00-04:00');self.charge=self.now-timedelta(hours=1);self.started=self.now-timedelta(hours=2)
  self.d={'input_datetime.mower_resume_date':'2026-10-26','person.fixture_bind_104':'home','input_boolean.mower_rain_hold_active':'off','input_number.mower_owner_reconcile_attempts':'1','input_text.mower_carryover_last_attempt_date':'2026-10-26','sensor.fixture_bind_116':'MODE_READY'}
  self.safe=True;self.progress=55
 def eligible(self):
  env=Environment();env.filters['bool']=lambda v,default=False: bool(v)
  def dt(v,default=None):
   try:return datetime.fromisoformat(v)
   except (ValueError,TypeError):return default
  def ts(v,default=0):
   try:return (v if isinstance(v,datetime) else dt(v)).timestamp()
   except (ValueError,TypeError,AttributeError):return default
  return env.from_string(self.t).render(states=States(self.d,self.charge),is_state=lambda e,v:self.d.get(e)==v,state_attr=lambda e,a:self.started,as_datetime=dt,as_timestamp=ts,now=lambda:self.now,today_at=lambda t:self.now.replace(hour=int(t[:2]),minute=int(t[3:]),second=0),safe_dock=self.safe,checkpoint=self.progress).strip()=='True'
 def test_new_charge_allows_same_day_reattachment(self):self.assertTrue(self.eligible())
 def test_same_charge_cannot_reconsume(self):self.started=self.now;self.assertFalse(self.eligible())
 def test_unstable_charge_waits(self):self.charge=self.now-timedelta(seconds=30);self.assertFalse(self.eligible())
 def test_not_ready_blocks_extra_attempt(self):self.d['sensor.fixture_bind_116']='MODE_LOCK';self.assertFalse(self.eligible())
 def test_cross_day_saved_work_eligible_today(self):self.d['input_datetime.mower_resume_date']='2026-10-25';self.d['input_text.mower_carryover_last_attempt_date']='2026-10-25';self.assertTrue(self.eligible())
 def test_cross_day_daily_budget_preserved(self):self.d['input_datetime.mower_resume_date']='2026-10-25';self.assertFalse(self.eligible())
 def test_before_nine_blocked(self):self.now=self.now.replace(hour=8);self.assertFalse(self.eligible())
 def test_after_nineteen_blocked(self):self.now=self.now.replace(hour=19);self.assertFalse(self.eligible())
 def test_away_blocks(self):self.d['person.fixture_bind_104']='not_home';self.assertFalse(self.eligible())
 def test_rain_blocks(self):self.d['input_boolean.mower_rain_hold_active']='on';self.assertFalse(self.eligible())
 def test_no_safe_dock_blocks(self):self.safe=False;self.assertFalse(self.eligible())
 def test_complete_blocks(self):self.progress=100;self.assertFalse(self.eligible())
 def test_missing_saved_date_blocks(self):self.d['input_datetime.mower_resume_date']='unknown';self.assertFalse(self.eligible())
 def test_return_budget_not_reset_on_movement(self):
  c=next(a for a in self.package['automation'] if a['id']=='mower_obstruction_dock');writes=[]
  def walk(x):
   if isinstance(x,dict):
    if 'recovery_attempts' in x:writes.append(x['recovery_attempts'])
    for v in x.values():walk(v)
   elif isinstance(x,list):
    for v in x:walk(v)
  walk(c);self.assertEqual(writes,[0,'{{ recovery_attempts | int(0) + 1 }}'])
if __name__=='__main__':unittest.main()
