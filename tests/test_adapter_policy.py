"""Physical evidence, weather and recharge policies without HA or devices."""
import importlib.util
from pathlib import Path
import unittest
from datetime import datetime, timezone, timedelta
spec=importlib.util.spec_from_file_location('portable_adapter_policy',Path(__file__).resolve().parents[1]/'custom_components/mower_coordinator/adapter_policy.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)

class AdapterPolicyTests(unittest.TestCase):
    def setUp(self):
        self.weather={'temperature':20,'temperature_unit':'°C','wind_speed':3,'wind_speed_unit':'m/s'}
    def test_units_for_distance(self):
        self.assertEqual(policy.mileage_m(2,'km'),2000)
        self.assertIsNone(policy.mileage_m(2,'unknown'))
        self.assertIsNone(policy.mileage_m(float('nan'),'m'))
        self.assertIsNone(policy.mileage_m(-1,'m'))
    def test_physical_distance_not_coordinate_format(self):
        self.assertEqual(policy.distance_m((40,-100),(40,-100)),0)
        self.assertGreater(policy.distance_m((40,-100),(40.001,-100)),100)
    def test_weather_units_dormancy_gust_and_unknown(self):
        self.assertTrue(policy.weather_condition('sunny',self.weather,10,5))
        self.assertFalse(policy.weather_condition('sunny',{**self.weather,'temperature':4},10,5))
        self.assertFalse(policy.weather_condition('sunny',{**self.weather,'wind_gust_speed':20},10,5))
        self.assertIsNone(policy.weather_condition('sunny',{**self.weather,'wind_speed_unit':'x'},10,5))
        self.assertTrue(policy.weather_condition('sunny',{**self.weather,'temperature':68,'temperature_unit':'°F','wind_speed':10,'wind_speed_unit':'mph'},10,5))
    def test_light_rain_permission_never_accepts_severe_weather(self):
        self.assertFalse(policy.weather_condition('rainy',self.weather,10,5))
        self.assertTrue(policy.weather_condition('rainy',self.weather,10,5,True))
        for condition in policy.SEVERE_WEATHER:
            self.assertFalse(policy.weather_condition(condition,self.weather,10,5,True))
    def test_forecast_must_be_future_and_have_own_measurements(self):
        now=datetime(2026,10,26,12,tzinfo=timezone.utc)
        item={'datetime':(now+timedelta(hours=1)).isoformat(),'condition':'sunny','temperature':20,'wind_speed':3,'precipitation_probability':10}
        args=(self.weather,now.timestamp(),6,50,10,5)
        full=[{**item,'datetime':(now+timedelta(hours=h)).isoformat()} for h in range(1,7)]
        self.assertTrue(policy.forecast_safe(full,*args))
        self.assertIsNone(policy.forecast_safe([item],*args))
        self.assertFalse(policy.forecast_safe([{**row,'precipitation_probability':70} for row in full],*args))
        self.assertIsNone(policy.forecast_safe([{**item,'datetime':(now-timedelta(hours=1)).isoformat()}],*args))
        self.assertIsNone(policy.forecast_safe([{'datetime':item['datetime'],'condition':'sunny'}],*args))
        self.assertIsNone(policy.forecast_safe([], *args))
    def test_forecast_requires_continuous_hourly_horizon(self):
        now=datetime(2026,10,26,12,tzinfo=timezone.utc)
        def row(hour):return {'datetime':(now+timedelta(hours=hour)).isoformat(),'condition':'sunny','temperature':20,'wind_speed':3,'precipitation_probability':10}
        args=(self.weather,now.timestamp(),6,50,10,5)
        self.assertTrue(policy.forecast_safe([row(h) for h in (1,2,3,4,5)],*args))
        self.assertTrue(policy.forecast_safe([row(h) for h in (5,4,3,2,1)],*args))
        for hours in ((2,3,4,5,6),(1,2,3,4),(1,2,4,5,6),(1,1,1)):
            self.assertIsNone(policy.forecast_safe([row(h) for h in hours],*args))
        self.assertTrue(policy.forecast_safe([row(h+.005) for h in (1,2,3,4,5)],*args))
        self.assertIsNone(policy.forecast_safe([row(h) for h in (1,2,3.1,4,5,6)],*args))

    def test_forecast_probability_must_be_present_finite_and_in_range(self):
        now=datetime(2026,10,26,12,tzinfo=timezone.utc)
        rows=[{'datetime':(now+timedelta(hours=h)).isoformat(),'condition':'sunny','temperature':20,'wind_speed':3,'precipitation_probability':0} for h in range(1,7)]
        args=(self.weather,now.timestamp(),6,50,10,5)
        for invalid in (None,float('nan'),float('inf'),-1,101,True,'invalid'):
            changed=[dict(row) for row in rows];changed[3]['precipitation_probability']=invalid
            self.assertIsNone(policy.forecast_safe(changed,*args))
        changed=[dict(row) for row in rows];del changed[3]['precipitation_probability']
        self.assertIsNone(policy.forecast_safe(changed,*args))
        changed[3]['precipitation_probability']=50
        self.assertFalse(policy.forecast_safe(changed,*args))
        changed[3]['precipitation_probability']=49
        self.assertTrue(policy.forecast_safe(changed,*args))

    def test_adaptive_recharge_fallback_floor_cap_and_progress(self):
        cfg={'reserve_battery':25,'resume_battery':85,'adaptive_recharge':True,'recharge_min_target':60,'recharge_max_target':95,'recharge_buffer':10}
        self.assertEqual(policy.recharge_target(cfg,80,None),85)
        self.assertEqual(policy.recharge_target(cfg,80,.5),60)
        self.assertEqual(policy.recharge_target(cfg,0,2),95)
        self.assertEqual(policy.recharge_target({**cfg,'adaptive_recharge':False},80,.5),85)
        self.assertLess(policy.recharge_target(cfg,80,1),policy.recharge_target(cfg,20,1))
if __name__=='__main__':unittest.main()
