"""Offline HA-adapter seam tests. All HA services, registry and storage are fakes."""
import asyncio
from copy import deepcopy
from dataclasses import make_dataclass
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch, AsyncMock

ROOT = Path(__file__).resolve().parents[1] / "custom_components/mower_coordinator"
PACKAGE = "mower_adapter_test"
NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Error(Exception): pass
class Store:
    def __init__(self, *args): self.data=None; self.after_save=None
    async def async_load(self): return self.data
    async def async_save(self, data):
        self.data=deepcopy(data)
        if self.after_save:
            hook,self.after_save=self.after_save,None
            hook()


stubs={name:types.ModuleType(name) for name in ("homeassistant", "homeassistant.core", "homeassistant.exceptions", "homeassistant.helpers", "homeassistant.helpers.entity_registry", "homeassistant.helpers.event", "homeassistant.helpers.storage", "homeassistant.util", "homeassistant.util.dt", PACKAGE)}
stubs[PACKAGE].__path__=[str(ROOT)]
stubs["homeassistant.core"].callback=lambda f:f
stubs["homeassistant.exceptions"].HomeAssistantError=Error
stubs["homeassistant.helpers.entity_registry"].async_get=lambda h:h.registry
stubs["homeassistant.helpers.event"].async_track_state_change_event=lambda *a:lambda:None
stubs["homeassistant.helpers.event"].async_track_time_interval=lambda *a:lambda:None
stubs["homeassistant.helpers.storage"].Store=Store
stubs["homeassistant.util.dt"].utcnow=lambda:NOW
stubs["homeassistant.util.dt"].now=lambda:NOW
with patch.dict(sys.modules, stubs):
    core=load(PACKAGE+".core",ROOT/"core.py")
    load(PACKAGE+".notifications",ROOT/"notifications.py")
    runtime=load(PACKAGE+".runtime",ROOT/"runtime.py")


class Services:
    def __init__(self): self.calls=[]
    def has_service(self,*args):return True
    async def async_call(self,domain,service,data,**kwargs):self.calls.append((domain,service,data))


class States:
    def __init__(self):self.items={}
    def get(self,eid):return self.items.get(eid)
    def async_all(self):return list(self.items.values())
    def put(self,eid,value,age=0,attrs=None):
        self.items[eid]=types.SimpleNamespace(entity_id=eid,state=value,attributes=attrs or {},last_reported=NOW-timedelta(seconds=age),last_changed=NOW-timedelta(seconds=age))


class Registry:
    def async_get(self,eid):return types.SimpleNamespace(device_id="fake_device",platform="mower_simulator")


class Entry:
    entry_id="fake-entry";options={}
    def __init__(self,data):self.data=data;self.tasks=[]
    def async_create_background_task(self,hass,coro,name):
        task=asyncio.create_task(coro);self.tasks.append(task);return task


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        states=States()
        config={key:eid for key,eid in (("mower_entity","lawn_mower.fake"),("battery_entity","sensor.battery"),("progress_entity","sensor.progress"),("charging_entity","binary_sensor.charging"),("activity_entity","sensor.activity"),("error_entity","sensor.error"),("rain_entity","binary_sensor.rain"),("safety_entity","binary_sensor.safe"),("person_entity","person.operator"),("blade_time_entity","sensor.blade"))}
        for key,value in (("mower_entity","docked"),("battery_entity","100"),("progress_entity","0"),("charging_entity","on"),("activity_entity","MODE_READY"),("error_entity","0"),("rain_entity","off"),("safety_entity","on"),("person_entity","home"),("blade_time_entity","20")):
            states.put(config[key],value)
        states.items["lawn_mower.fake"].attributes["map_revision"]="fake-map-v1"
        states.put("switch.area","off",attrs={"hash":11,"map_revision":"fake-map-v1"})
        config["auto_recovery"]=False; config["allow_handoff"]=False
        config["zones"]=[{"id":"lawn","name":"Lawn","area_entities":["switch.area"],"angles":[0,90],"spacing_cm":11,"perimeter_laps":2,"interval_days":3,"minimum_battery":80}]
        self.hass=types.SimpleNamespace(states=states,services=Services(),registry=Registry(),config=types.SimpleNamespace(time_zone="UTC"))
        self.entry=Entry(config);self.r=runtime.MowerRuntime(self.hass,self.entry)
        self.r.armed=True;self.r.hold=False;self.r.evidence["setup_confirmed"]=True
        self.r.state.was_charging=True;self.r.state.charging_since=NOW.timestamp()-120

    async def asyncTearDown(self):
        if self.entry.tasks:await asyncio.gather(*self.entry.tasks)

    async def own_job(self):
        await self.r.async_evaluate()
        self.assertEqual(self.hass.services.calls[-1][1],"start_mow")
        self.r.state.pending_command=None;self.r.state.phase="mowing";self.r.state.seen_work=True;self.r.state.checkpoint=40
        self.r.state.last_dispatch_at=NOW.timestamp()-100
        self.hass.states.put("lawn_mower.fake","mowing",attrs={"map_revision":"fake-map-v1"})
        self.hass.states.put("binary_sensor.charging","off")
        self.hass.states.put("sensor.activity","MODE_WORKING")
        self.hass.services.calls.clear()

    def install_motion(self):
        for key,eid,value,attrs in (
            ("tracker_entity","device_tracker.fake","not_home",{"latitude":40,"longitude":-100}),
            ("mileage_entity","sensor.mileage","2",{"unit_of_measurement":"km"}),
            ("rtk_entity","sensor.rtk","Fix",{})):
            self.r.config[key]=eid; self.hass.states.put(eid,value,attrs=attrs)
        self.r.config["auto_recovery"]=True

    async def test_motion_evidence_uses_units_and_repeats_same_sample(self):
        self.install_motion()
        self.assertEqual(self.r.motion_evidence()[:1],(False,))
        self.hass.states.items["sensor.mileage"].state="2.011"
        self.assertTrue(self.r.motion_evidence()[0])
        self.assertTrue(self.r.motion_evidence()[0],"Repeated same report must not consume motion proof")
        self.hass.states.items["sensor.rtk"].state="Float"
        self.assertFalse(self.r.motion_evidence()[2])
        self.assertFalse(self.r.preflight()["recovery_bindings_ready"])

    async def test_unknown_and_critical_current_faults_block_recovery(self):
        await self.own_job(); self.install_motion()
        self.hass.states.put("lawn_mower.fake","paused",attrs={"map_revision":"fake-map-v1"})
        self.hass.states.put("sensor.activity","MODE_PAUSE")
        self.r.config.update(recent_fault_code_entity="sensor.fault",recent_fault_time_entity="sensor.fault_time")
        self.hass.states.put("sensor.fault_time",NOW.isoformat())
        for code in ("9999","1004","2800"):
            self.hass.states.put("sensor.fault",code)
            obs=self.r.observation()
            self.assertFalse(obs.safe);self.assertFalse(obs.recoverable)
        self.hass.states.put("sensor.fault","1201")
        self.assertTrue(self.r.observation().recoverable)
        self.hass.states.put("sensor.fault","1004")
        self.hass.states.items["sensor.fault_time"].state=(NOW-timedelta(hours=1)).isoformat()
        self.assertTrue(self.r.observation().safe,"Old log entry must not act as a current fault")

    async def test_cancel_return_withheld_when_movement_arrives_during_save(self):
        await self.own_job();self.install_motion()
        self.hass.states.put("lawn_mower.fake","returning",attrs={"map_revision":"fake-map-v1"})
        self.hass.states.put("sensor.activity","MODE_RETURNING")
        self.r.observation()
        self.hass.services.calls.clear()
        self.r.store.after_save=lambda:self.hass.states.put("sensor.mileage","0.1",attrs={"unit_of_measurement":"km"})
        decision=types.SimpleNamespace(state=self.r.state,reason="retry",intents=[core.Intent("cancel_return",{})])
        with patch.object(runtime,"tick",return_value=decision):
            await self.r.async_evaluate()
        self.assertFalse(any(service=="pause" for _,service,_ in self.hass.services.calls))
        self.assertIn("recovery evidence changed",self.r.reason)

    async def test_resume_rechecks_configured_battery_and_profile(self):
        await self.own_job();self.install_motion()
        self.hass.states.put("lawn_mower.fake","paused",attrs={"map_revision":"fake-map-v1"})
        self.hass.states.put("sensor.activity","MODE_PAUSE")
        intent=core.Intent("resume",{"job_token":self.r.state.job_token})
        self.assertTrue(self.r.final_motion_gate(intent,self.r.observation()))
        self.hass.states.put("sensor.battery","30")
        self.assertFalse(self.r.final_motion_gate(intent,self.r.observation()))
        self.hass.states.put("sensor.battery","100")
        self.r.config["zones"][0]["spacing_cm"]=20
        self.assertFalse(self.r.final_motion_gate(intent,self.r.observation()))

    async def test_cancel_return_uses_pause_not_toggling_dock(self):
        await self.r.dispatch(core.Intent("cancel_return",{}))
        self.assertEqual(self.hass.services.calls[-1],("lawn_mower","pause",{"entity_id":"lawn_mower.fake"}))

    async def test_dock_withheld_if_native_activity_is_already_returning(self):
        await self.own_job()
        self.hass.states.put("lawn_mower.fake","returning",attrs={"map_revision":"fake-map-v1"})
        self.hass.states.put("sensor.activity","MODE_RETURNING")
        self.hass.services.calls.clear()
        decision=types.SimpleNamespace(state=self.r.state,reason="retry",intents=[core.Intent("dock",{})])
        with patch.object(runtime,"tick",return_value=decision):
            await self.r.async_evaluate()
        self.assertFalse(any(service=="dock" for _,service,_ in self.hass.services.calls))
        self.assertIn("native activity changed",self.r.reason)

    async def test_native_resume_preserves_route_and_rechecks_hold(self):
        await self.own_job();self.install_motion()
        self.hass.states.put("lawn_mower.fake","paused",attrs={"map_revision":"fake-map-v1"})
        self.hass.states.put("sensor.activity","MODE_PAUSE")
        intent=core.Intent("resume",{"job_token":self.r.state.job_token})
        self.assertTrue(self.r.final_motion_gate(intent,self.r.observation()))
        self.r.hold=True
        self.assertFalse(self.r.final_motion_gate(intent,self.r.observation()))
        self.r.hold=False
        await self.r.dispatch(intent)
        self.assertEqual(self.hass.services.calls[-1],("lawn_mower","start_mowing",{"entity_id":"lawn_mower.fake"}))
        self.assertEqual(self.r.state.checkpoint,40)

    async def test_changed_configuration_invalidates_receipt_without_losing_checkpoint(self):
        await self.own_job()
        self.r.evidence.update(notification_received=True,setup_confirmed=True)
        self.r._burn_rates={"zone":0.5}
        await self.r.save()
        self.r.config["notifications"]={"targets":["notify.new_destination"]}
        await self.r.async_load()
        self.assertFalse(self.r.evidence["notification_received"])
        self.assertEqual(self.r._burn_rates,{})
        self.assertFalse(self.r.evidence["setup_confirmed"])
        self.assertEqual(self.r.state.checkpoint,40)

    async def test_rain_drying_hold_and_light_rain_require_dry_owner_proof(self):
        self.r.config["rain_dry_minutes"]=30
        self.hass.states.put("binary_sensor.rain","on")
        self.assertTrue(self.r.observation().rain)
        self.hass.states.put("binary_sensor.rain","off")
        self.assertTrue(self.r.observation().rain)
        self.r.config["weather_entity"]="weather.fake"
        self.r.config["light_rain_tolerance"]=True
        self.hass.states.put("weather.fake","rainy",attrs={"temperature":20,"temperature_unit":"°C","wind_speed":1,"wind_speed_unit":"m/s"})
        self.assertFalse(self.r.weather_safe())
        self.r.state.job_token="owned-job";self.r._dry_launch_token="owned-job"
        self.assertTrue(self.r.weather_safe())
        self.hass.states.items["weather.fake"].state="lightning"
        self.assertFalse(self.r.weather_safe())

    async def test_adaptive_recharge_requires_measured_cutting_and_retains_rate(self):
        await self.own_job()
        obs=self.r.observation()
        from dataclasses import replace
        self.r.learn_recharge(replace(obs,working=True,progress=10,battery=90))
        self.hass.states.items["sensor.blade"].state="40"
        self.r.learn_recharge(replace(obs,working=True,progress=30,battery=80))
        self.assertEqual(self.r._burn_rates["lawn"],.5)
        self.r.state.checkpoint=80
        self.assertEqual(self.r.settings().resume_battery,60)
        await self.r.save();self.r._burn_rates={};await self.r.async_load()
        self.assertEqual(self.r._burn_rates["lawn"],.5)

    async def test_startup_before_mower_entity_exists_stays_loaded_without_commands(self):
        self.r.armed=False
        self.hass.states.items.pop("lawn_mower.fake")
        self.assertFalse(self.r.preflight()["telemetry_fresh"])
        self.assertFalse(self.r.preflight()["map_revision_available"])
        await self.r.async_evaluate()
        self.assertEqual(self.hass.services.calls, [])
        self.assertIn("Not ready", self.r.reason)

    async def test_static_presence_and_rain_do_not_make_device_telemetry_stale(self):
        self.hass.states.put("person.operator","home",age=86400)
        self.hass.states.put("binary_sensor.rain","off",age=86400)
        self.hass.states.put("binary_sensor.safe","on",age=86400)
        self.assertTrue(self.r.preflight()["telemetry_fresh"])
        await self.r.async_evaluate()
        self.assertEqual(self.hass.services.calls[-1][1],"start_mow")

    async def test_missing_rain_protection_still_requests_owned_protective_return(self):
        await self.own_job()
        self.hass.states.put("binary_sensor.rain","unavailable")
        await self.r.async_evaluate()
        self.assertEqual(self.hass.services.calls[-1][1],"dock")
        self.assertEqual(self.r.state.checkpoint,40)

    async def test_missing_configured_weather_still_requests_owned_return(self):
        await self.own_job()
        self.r.config["weather_entity"]="weather.missing"
        await self.r.async_evaluate()
        self.assertEqual(self.hass.services.calls[-1][1],"dock")

    async def test_physical_safety_missing_never_requests_motion(self):
        await self.own_job()
        self.hass.states.put("binary_sensor.safe","unavailable")
        self.hass.states.put("sensor.battery","10")
        await self.r.async_evaluate()
        self.assertFalse(any(s in {"dock","start_mow"} for _,s,_ in self.hass.services.calls))

    async def test_final_gate_rechecks_battery_after_durable_write(self):
        self.r.store.after_save=lambda:self.hass.states.put("sensor.battery","10")
        await self.r.async_evaluate()
        self.assertFalse(self.hass.services.calls)
        self.assertIsNone(self.r.state.pending_command)
        self.assertIsNone(self.r.state.active_zone)

    async def test_final_gate_rechecks_native_map_after_durable_write(self):
        self.r.store.after_save=lambda:self.hass.states.put("switch.area","off",attrs={"hash":12})
        await self.r.async_evaluate()
        self.assertFalse(self.hass.services.calls)
        self.assertIsNone(self.r.state.pending_command)

    async def test_map_geometry_revision_change_is_detected_with_same_area_ids(self):
        await self.own_job()
        self.hass.states.put("lawn_mower.fake","mowing",attrs={"map_revision":"fake-map-v2"})
        await self.r.async_evaluate()
        self.assertEqual(self.r.state.phase,"quarantined")
        self.assertFalse(any(s in {"dock","start_mow"} for _,s,_ in self.hass.services.calls))

    async def test_no_map_revision_contract_prevents_control(self):
        self.hass.states.items["lawn_mower.fake"].attributes.clear()
        self.hass.states.items["switch.area"].attributes.pop("map_revision")
        self.assertFalse(self.r.preflight()["map_revision_available"])
        await self.r.async_evaluate()
        self.assertEqual(self.hass.services.calls,[])

    async def test_observer_emits_no_device_or_notification_commands(self):
        self.r.armed=False
        await self.r.async_evaluate()
        self.assertEqual(self.hass.services.calls,[])
        self.assertEqual(self.entry.tasks,[])
        self.assertIsNone(self.r.state.active_zone)

    async def test_notification_button_waits_for_state_lock(self):
        await self.r._lock.acquire()
        task=asyncio.create_task(self.r.async_button("notification_test"))
        await asyncio.sleep(0)
        self.assertFalse(self.r.evidence["notification_test_requested"])
        self.r.armed=False
        self.r._lock.release()
        await task
        self.assertTrue(self.r.evidence["notification_test_requested"])

    async def test_attention_marks_urgency_for_explicit_quiet_hours_override(self):
        self.r.notifier.async_send=AsyncMock()
        self.r.notify("attention","Needs inspection")
        await asyncio.gather(*self.entry.tasks)
        self.r.notifier.async_send.assert_awaited_once_with("attention","Needs inspection",urgent=True)

    async def test_hold_notification_only_on_reason_change(self):
        calls=[]
        self.r.notify=lambda event,message:calls.append((event,message))
        self.r.hold=True
        await self.r.async_evaluate()
        await self.r.async_evaluate()
        self.assertEqual([e for e,_ in calls],["hold"])

    async def test_return_is_routed_to_charging_notification_category(self):
        await self.own_job()
        calls=[]
        self.r.notify=lambda event,message:calls.append((event,message))
        self.hass.states.put("sensor.battery","25")
        await self.r.async_evaluate()
        self.assertEqual([e for e,_ in calls],["charging"])

    async def test_weather_uses_wizard_max_age_and_metric_conversion(self):
        self.r.config.update(weather_entity="weather.local",weather_max_age=60,wind_limit_mps=10)
        self.hass.states.put("weather.local","sunny",age=61,attrs={"temperature":68,"temperature_unit":"°F","wind_speed":10,"wind_speed_unit":"mph"})
        self.assertIsNone(self.r.weather_safe())
        self.hass.states.put("weather.local","sunny",age=30,attrs={"temperature":20,"temperature_unit":"°C","wind_speed":36,"wind_speed_unit":"km/h"})
        self.assertTrue(self.r.weather_safe())

    async def test_stale_completion_cannot_borrow_new_blade_proof(self):
        await self.own_job()
        self.r.observation()  # baseline at blade=20
        self.hass.states.put("sensor.blade","21")
        # A distinct new blade sample at NOW; previous sample must precede it.
        self.r._last_blade_reported=NOW.timestamp()-1
        self.hass.states.put("sensor.progress","100",age=20)
        self.assertFalse(self.r.observation().working)

    async def test_telemetry_stale_prevents_every_physical_intent(self):
        await self.own_job()
        self.hass.states.put("sensor.battery","10",age=121)
        await self.r.async_evaluate()
        self.assertFalse(any(s in {"dock","start_mow"} for _,s,_ in self.hass.services.calls))

    def real_map_fixture(self):
        entries={eid:types.SimpleNamespace(entity_id=eid,device_id="fake_device",platform="mammotion",translation_key="") for eid in self.hass.states.items}
        entries["sensor.map_sync"]=types.SimpleNamespace(entity_id="sensor.map_sync",device_id="fake_device",platform="mammotion",translation_key="map_sync_status")
        self.hass.registry=types.SimpleNamespace(entities=entries,async_get=lambda eid:entries.get(eid))
        self.hass.states.put("sensor.map_sync","synced")
        frame_type=make_dataclass("MapFrame",[("current_frame",int),("data_couple",list),("type",int)])
        frames_type=make_dataclass("MapFrames",[("total_frame",int),("data",list)])
        self.frame=frame_type(0,[{"x":1,"y":2},{"x":3,"y":4}],0)
        buckets={name:{} for name in ("area","path","obstacle","dump","svg","visual_safety_zone","visual_obstacle_zone","corridor_line","corridor_point","virtual_wall","no_go_zone_variant","no_go_zone","unknown_type_frames")}
        buckets["area"]={11:frames_type(1,[self.frame])}
        self.mapping=types.SimpleNamespace(**buckets,area_root_hashlist=[11])
        entries["lawn_mower.fake"].unique_id="fake_mower"
        coordinator=types.SimpleNamespace(unique_name="fake",data=types.SimpleNamespace(map=self.mapping))
        fakeentry=types.SimpleNamespace(runtime_data=types.SimpleNamespace(mowers=[types.SimpleNamespace(reporting_coordinator=coordinator)]))
        self.hass.config_entries=types.SimpleNamespace(async_entries=lambda domain:[fakeentry])

    async def test_real_map_read_only_geometry_hash_changes_same_area_id(self):
        self.real_map_fixture()
        await self.r.refresh_map_identity()
        first=self.r.native_map_revision()
        self.assertIsNotNone(first)
        self.assertNotIn("points",first)
        self.assertEqual(self.hass.services.calls,[])
        self.frame.data_couple[0]={"x":5,"y":6}
        await self.r.refresh_map_identity()
        self.assertNotEqual(first,self.r.native_map_revision())

    async def test_real_map_out_of_sync_or_missing_blocks(self):
        self.real_map_fixture()
        await self.r.refresh_map_identity()
        self.hass.states.put("sensor.map_sync","out_of_sync")
        self.assertIsNone(self.r.native_map_revision())
        await self.r.refresh_map_identity()
        self.assertIsNone(self.r._geometry_revision)
        self.hass.states.put("sensor.map_sync","synced")
        self.mapping.area={}
        await self.r.refresh_map_identity()
        self.assertIsNone(self.r.native_map_revision())

    async def test_cached_map_detects_obstacle_nogo_and_path_edits(self):
        self.real_map_fixture()
        await self.r.refresh_map_identity()
        for bucket in ("obstacle","no_go_zone","path"):
            previous=self.r.native_map_revision()
            getattr(self.mapping,bucket)[12]=deepcopy(self.mapping.area[11])
            await self.r.refresh_map_identity()
            self.assertNotEqual(previous,self.r.native_map_revision())
            previous=self.r.native_map_revision()
            getattr(self.mapping,bucket)[12].data[0].data_couple[0]["x"]+=1
            await self.r.refresh_map_identity()
            self.assertNotEqual(previous,self.r.native_map_revision())
        self.mapping.unknown_type_frames={99:{}}
        await self.r.refresh_map_identity()
        self.assertIsNone(self.r.native_map_revision())

    async def test_cached_map_unknown_shape_and_incomplete_frames_fail_closed(self):
        self.real_map_fixture()
        self.mapping.area[11].total_frame=2
        await self.r.refresh_map_identity()
        self.assertIsNone(self.r.native_map_revision())
        self.mapping.area[11]={"data":[]}
        await self.r.refresh_map_identity()
        self.assertIsNone(self.r.native_map_revision())

    async def test_native_self_check_clear_historical_error_rejected(self):
        self.real_map_fixture()
        await self.r.refresh_map_identity()
        self.hass.states.put("sensor.error","normal")
        self.assertTrue(self.r.observation().safe)
        self.hass.registry.entities["sensor.error"].translation_key="error_1_code"
        self.assertFalse(self.r.preflight()["active_error_source"])
        self.hass.states.put("sensor.error","emergency_stop")
        self.assertFalse(self.r.observation().safe)

    async def test_notification_receipt_required_when_destination_configured(self):
        self.r.config["notifications"]={"legacy_actions":["notify.phone"]}
        with self.assertRaises(Error):await self.r.async_button("commission")
        with self.assertRaises(Error):await self.r.async_set_control("armed",True)
        self.r.evidence["notification_received"]=True
        self.r.require_notification_confirmation()

    async def test_charging_onset_does_not_borrow_old_progress_time(self):
        self.r.state.was_charging=False
        self.hass.states.put("sensor.progress","0",age=100)
        await self.r.async_evaluate()
        self.assertEqual(self.r.state.charging_since,NOW.timestamp())
        self.assertFalse(any(s=="start_mow" for _,s,_ in self.hass.services.calls))


if __name__ == "__main__":unittest.main()
