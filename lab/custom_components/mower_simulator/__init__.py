"""Network-free fake mower. Never import this into a production installation."""
from datetime import datetime, timezone
from types import SimpleNamespace
from dataclasses import dataclass

@dataclass
class Frame:
    current_frame: int
    data_couple: list
    type: int = 0
    paternal_hash_a: int = 0
    paternal_hash_b: int = 0

@dataclass
class FrameList:
    total_frame: int
    data: list

import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.helpers import config_validation as cv, entity_registry as er, device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send

DOMAIN = "mower_simulator"
PLATFORMS = ["lawn_mower", "sensor", "binary_sensor", "switch", "notify", "weather"]
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)
DEFAULT = dict(mower="docked", battery=100, progress=0, activity="MODE_READY", error=0,
               blade_time=0, mileage=0, charging=True, rain=False, safety_clear=True,
               operator_home=True, latitude=40.0, longitude=-100.0, delay_ack=False,
               fail_dock=False, fail_notify=False, map_revision="lab-map-v1", map_sync_status="synced", no_go_revision=0, weather="sunny", temperature=20, wind_speed=2, wind_gust=3, forecast_rain=False, rtk="Fix", recent_fault_code=0, recent_fault_time="2000-01-01T00:00:00+00:00")

def publish(hass):
    sim = hass.data[DOMAIN]
    sim["updated"] = datetime.now(timezone.utc).isoformat()
    if "map" in sim:
        sim["map"].area = {i:FrameList(1,[Frame(0,[i,0,i,1,len(sim["state"]["map_revision"])])]) for i in (10001,10002,10003)}
        sim["map"].no_go_zone = {30001:FrameList(1,[Frame(0,[0,0,sim["state"]["no_go_revision"],1])])}
    hass.states.async_set("person.lab_operator", "home" if sim["state"]["operator_home"] else "not_home", {"friendly_name":"Lab operator (simulated)","observed_at":sim["updated"]})
    hass.states.async_set("device_tracker.lab_mower", "not_home", {"latitude":sim["state"]["latitude"], "longitude":sim["state"]["longitude"], "gps_accuracy":1, "source_type":"gps"})
    async_dispatcher_send(hass, DOMAIN)

async def command(hass, action, data):
    sim = hass.data[DOMAIN]
    sim["commands"].append({"action":action,"data":dict(data),"time":datetime.now(timezone.utc).isoformat()})
    sim["commands"] = sim["commands"][-100:]
    state = sim["state"]
    if action in ("start_mow", "start_mowing") and not state["delay_ack"]:
        state.update(mower="mowing", charging=False, activity="MODE_WORKING", progress=float(data.get("start_progress", state["progress"] if action == "start_mowing" else 0)), error=0)
    elif action == "dock" and not state["charging"]:
        # Upstream Dock is a toggle while returning: it cancels return.
        if state["activity"] == "MODE_RETURNING":
            state.update(mower="paused", activity="MODE_PAUSE")
        else:
            state.update(mower="returning", charging=False, activity="MODE_RETURNING")
    elif action in ("pause", "stop", "cancel_job"):
        state.update(mower="paused" if action == "pause" else "idle", activity="MODE_PAUSE" if action == "pause" else "MODE_READY", charging=False)
    publish(hass)

async def async_setup(hass, config):
    hass.async_create_task(hass.config_entries.flow.async_init(DOMAIN, context={"source":"import"}, data={}))
    return True

async def async_setup_entry(hass, entry):
    hass.data[DOMAIN] = {"state":dict(DEFAULT),"commands":[],"notifications":[],"updated":""}
    map_data=SimpleNamespace(**{key:{} for key in ("area","path","obstacle","dump","svg","visual_safety_zone","visual_obstacle_zone","corridor_line","corridor_point","virtual_wall","no_go_zone_variant","no_go_zone","unknown_type_frames")})
    map_data.area_root_hashlist=[10001,10002,10003]
    hass.data[DOMAIN]["map"]=map_data
    entry.runtime_data=SimpleNamespace(mowers=[SimpleNamespace(reporting_coordinator=SimpleNamespace(unique_name="lab",data=SimpleNamespace(map=map_data)))])
    device = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN,"lab-mower")}, name="Lab mower", manufacturer="Mower simulator", model="Simulated Mammotion contract")
    registry = er.async_get(hass)
    for domain, obj in [("person","lab_operator"),("device_tracker","lab_mower")]:
        registry.async_get_or_create(domain, DOMAIN, obj, suggested_object_id=obj, config_entry=entry, device_id=device.id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async def fake(call):
        await command(hass, call.service, call.data)
    # Exact keys are intentionally restricted, to catch adapter/schema drift.
    start_schema = vol.Schema({
        vol.Optional("entity_id"):vol.Any(str,[str]), vol.Optional("device_id"):vol.Any(str,[str]),
        vol.Required("areas"):list,
        **{vol.Optional(k):object for k in ["modify","plan_only","is_mow","is_dump","is_edge","collect_grass_frequency","border_mode","job_version","job_id","speed","ultra_wave","channel_mode","channel_width","blade_height","toward","toward_included_angle","toward_mode","mowing_laps","obstacle_laps","start_progress","route_angle","path_spacing"]}
    })
    hass.services.async_register("mammotion", "start_mow", fake, schema=start_schema)
    for action in ["cancel_job"]:
        hass.services.async_register("mammotion", action, fake, schema=vol.Schema({},extra=vol.ALLOW_EXTRA))
    async def get_map_data(call):
        # Synthetic geometry only; revision changes geometry with stable IDs.
        revision = hass.data[DOMAIN]["state"]["map_revision"]
        return {"area": {str(i): {"points": [[i, 0], [i, 1], [i + 1, 1]], "revision": revision} for i in (10001,10002,10003)}, "svg": {}}
    hass.services.async_register("mammotion", "get_map_data", get_map_data, schema=vol.Schema({vol.Required("entity_id"):str}), supports_response=SupportsResponse.ONLY)
    async def get_geojson(call):
        return {"type":"FeatureCollection","features":[
            {"type":"Feature","properties":{"type":"area","hash":10001},"geometry":{"type":"Polygon","coordinates":[[[0,0],[0,1],[1,1],[0,0]]]}},
            {"type":"Feature","properties":{"type":"path","hash":20001},"geometry":{"type":"LineString","coordinates":[[0,0],[1,1]]}}
        ]}
    hass.services.async_register("mammotion", "get_geojson", get_geojson, schema=vol.Schema({vol.Required("entity_id"):str}), supports_response=SupportsResponse.ONLY)
    async def set_state(call):
        state = hass.data[DOMAIN]["state"]
        for key, value in call.data.items():
            if key not in DEFAULT: raise ValueError(f"Unknown simulator field: {key}")
            state[key] = value
        publish(hass)
    async def reset(call):
        hass.data[DOMAIN].update(state=dict(DEFAULT), commands=[], notifications=[])
        publish(hass)
    async def tick(call):
        state = hass.data[DOMAIN]["state"]
        seconds = call.data.get("seconds",60)
        if state["mower"] == "mowing":
            state["progress"] = min(100, state["progress"] + call.data.get("progress",5))
            state["battery"] = max(0, state["battery"] - call.data.get("battery",1))
            state["blade_time"] += seconds
            state["mileage"] += 10
            state["latitude"] += 0.0001
            if state["progress"] >= 100: state.update(mower="idle",activity="MODE_READY")
        elif state["mower"] == "returning" and not state["fail_dock"]:
            state.update(mower="docked", activity="MODE_READY", charging=True)
        elif state["charging"]:
            state["battery"] = min(100, state["battery"] + call.data.get("battery",10))
        publish(hass)
    async def notify(call):
        await capture(hass, call.data.get("message",""),call.data.get("title"))
    hass.services.async_register(DOMAIN,"set_state",set_state, schema=vol.Schema({},extra=vol.ALLOW_EXTRA))
    hass.services.async_register(DOMAIN,"reset",reset)
    hass.services.async_register(DOMAIN,"tick",tick, schema=vol.Schema({},extra=vol.ALLOW_EXTRA))
    hass.services.async_register("notify","lab_capture",notify, schema=vol.Schema({vol.Required("message"):str,vol.Optional("title"):str},extra=vol.ALLOW_EXTRA))
    publish(hass)
    return True

async def capture(hass,message,title=None):
    sim = hass.data[DOMAIN]
    if sim["state"]["fail_notify"]: raise RuntimeError("Simulated notification delivery failure")
    sim["notifications"].append({"message":message,"title":title})
    sim["notifications"] = sim["notifications"][-100:]
    publish(hass)

async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry,PLATFORMS)
