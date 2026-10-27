"""Supplemental synthetic acceptance checks; no physical devices or network."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from dataclasses import replace
from test_coordinator_core import Scenario, core, kinds

class AdditionalAcceptance(unittest.TestCase):
    def test_new_york_dst_window_edges(self):
        zone=ZoneInfo('America/New_York')
        for day in ((2026,3,8),(2026,11,1)):
            for hour,minute,allowed in ((8,59,False),(9,0,True),(18,59,True),(19,0,False)):
                with self.subTest(day=day,hour=hour,minute=minute):
                    s=Scenario();s.now=datetime(*day,hour,minute,tzinfo=zone)
                    self.assertEqual(core._window(s.settings,s.now),allowed)
    def test_repeated_dst_hour_cannot_restart_completed_area(self):
        s=Scenario();zone=ZoneInfo('America/New_York')
        s.settings=replace(s.settings,window_start='00:00',window_end='23:59')
        s.state.completed_dates={'one':'2026-11-01','two':'2026-11-01'}
        for fold in (0,1):
            now=datetime(2026,11,1,1,30,tzinfo=zone,fold=fold)
            self.assertEqual(core.new_plan(s.settings,s.state,now).queue,[])
    def test_midnight_local_date_not_utc(self):
        s=Scenario();s.state.completed_dates={'one':'2026-10-31','two':'2026-10-31'}
        s.settings=replace(s.settings,zones=tuple(replace(z,interval_days=1) for z in s.settings.zones))
        zone=ZoneInfo('America/New_York')
        self.assertEqual(core.new_plan(s.settings,s.state,datetime(2026,10,31,23,59,tzinfo=zone)).queue,[])
        self.assertEqual(core.new_plan(s.settings,s.state,datetime(2026,11,1,0,0,tzinfo=zone)).queue,['one','two'])
    def test_disconnect_late_ack_does_not_duplicate_launch(self):
        s=Scenario();self.assertEqual(kinds(s.launch()),['start'])
        for _ in range(4):
            self.assertNotIn('start',kinds(s.tick(60,safe=False)))
        self.assertNotIn('start',kinds(s.cut(15,safe=True)))
        for _ in range(5):self.assertNotIn('start',kinds(s.tick(10)))
