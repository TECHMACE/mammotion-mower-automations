"""HA adapter: serialized decisions, durable intent, final guards and explanations."""
from __future__ import annotations
import asyncio
from datetime import timedelta
from dataclasses import asdict, is_dataclass
import hashlib
import json
import math
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from .core import Zone, Settings, Observation, State, tick, reconcile_restart, reset_recovery, route_signature
from .notifications import NotificationManager
from .adapter_policy import CLEAR_HEALTH, CRITICAL_CODES, RECOVERABLE_CODES, distance_m, mileage_m, event_timestamp, weather_condition, forecast_safe, recharge_target

DOMAIN="mower_coordinator"
BAD={"unknown","unavailable","",None}
DEVICE_TELEMETRY=("mower_entity","battery_entity","progress_entity","charging_entity","activity_entity","error_entity","blade_time_entity")
COMPATIBILITY_CHECKS=("supported_adapter","saved_state_readable","start_action_available","dock_action_available","areas_match_mower","map_revision_available","active_error_source","settings_valid","no_legacy_controller_enabled")

class MowerRuntime:
    def __init__(self,hass,entry):
        self.hass=hass; self.entry=entry; self.config={**entry.data,**entry.options}
        self.store=Store(hass,1,f"{DOMAIN}.{entry.entry_id}")
        self.state=State(); self.armed=False; self.hold=True
        self.evidence={"setup_confirmed":False,"notification_test_requested":False,"notification_received":False,"launch_observed":False,"completion_observed":False,"charging_observed":False}
        self.reason="Observation only. Complete setup checks before enabling automatic control."
        self.next_step="Check readiness, test notifications, then confirm setup."
        self.updated_at=None; self.storage_error=False; self._stopped=False
        self._listeners=set(); self._unsubs=[]; self._lock=asyncio.Lock()
        self._geometry_revision=None; self._geometry_checked_at=0
        self._last_blade=None; self._last_blade_reported=0; self._cutting_proof_at=0
        self._motion_anchor=None; self._travel_anchor=None; self._motion_at=0; self._motion_key=None; self._motion_result=False; self._travel_moving=False
        self._last_wet=0; self._dry_launch_token=None
        self._fault_journal=[]; self._last_fault_key=None
        self._burn_sample=None; self._burn_rates={}
        self._forecasts={}; self._forecast_checked_at=0
        self._telemetry_requested_at=0
        self.notifier=NotificationManager(hass,entry.entry_id,self.config.get("notifications",{}))

    def subscribe(self,cb):
        self._listeners.add(cb)
        return lambda:self._listeners.discard(cb)

    def publish(self):
        self.updated_at=dt_util.utcnow().isoformat()
        for cb in list(self._listeners): cb()

    async def async_load(self):
        try:
            data=await self.store.async_load()
            if data:
                self.state=reconcile_restart(State.from_dict(data["state"]))
                self.evidence.update({k:bool(v) for k,v in data.get("evidence",{}).items() if k in self.evidence})
                policy=data.get("policy",{})
                self._last_wet=float(policy.get("last_wet",0))
                self._burn_rates={k:float(v) for k,v in policy.get("burn_rates",{}).items() if isinstance(k,str) and isinstance(v,(float,int)) and 0<float(v)<=2}
                self._fault_journal=[item for item in policy.get("fault_journal",[]) if isinstance(item,dict) and set(item)<={"at","category","code"}][-20:]
                if data.get("configuration_signature") != self.configuration_signature():
                    self._burn_rates={}  # Changed route/profile invalidates learned consumption.
                    for key in ("setup_confirmed","notification_test_requested","notification_received"):
                        self.evidence[key]=False
        except (ValueError,TypeError,KeyError,OSError):
            self.storage_error=True
            self.reason="Saved state could not be read. Automatic control is blocked; preserve storage for diagnosis."

    def configuration_signature(self):
        return hashlib.sha256(json.dumps(self.config,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

    async def save(self):
        if self.storage_error: raise HomeAssistantError("Saved state needs repair; no command was sent.")
        try: await self.store.async_save({"state":self.state.to_dict(),"evidence":self.evidence,"configuration_signature":self.configuration_signature(),"policy":{"last_wet":self._last_wet,"burn_rates":self._burn_rates,"fault_journal":self._fault_journal}})
        except Exception:
            self.storage_error=True; self.armed=False
            raise HomeAssistantError("Could not save job state; control is disarmed.") from None

    async def async_start(self):
        entities=[v for k,v in self.config.items() if k.endswith("_entity") and v]
        entities += self.weather_entities()
        entities += [a for z in self.config.get("zones",[]) for a in z["area_entities"]]
        @callback
        def changed(event):
            if self._stopped:return
            data=getattr(event,"data",{})
            state=data.get("new_state")
            if data.get("entity_id")==self.config.get("mower_entity") and state and state.state in {"paused","idle"} and getattr(getattr(state,"context",None),"user_id",None):
                self.entry.async_create_background_task(self.hass,self.async_set_control("hold",True),"Respect manual mower pause")
            else:
                self.entry.async_create_background_task(self.hass,self.async_evaluate(),"Mower decision")
        self._unsubs.append(async_track_state_change_event(self.hass,entities,changed))
        self._unsubs.append(async_track_time_interval(self.hass,changed,timedelta(seconds=15)))
        await self.async_evaluate()

    async def async_stop(self):
        self._stopped=True; self.armed=False
        for unsub in self._unsubs:unsub()
        self._unsubs.clear()
        async with self._lock:
            if not self.storage_error: await self.save()

    def entity(self,key): return self.hass.states.get(self.config.get(key,""))
    def fresh(self,state,seconds=None):
        seconds=self.config.get("freshness_seconds",120) if seconds is None else seconds
        if state is None or state.state in BAD:return False
        age=(dt_util.utcnow()-state.last_reported).total_seconds()
        return 0 <= age <= seconds
    def number(self,key):
        s=self.entity(key)
        try:
            value=float(s.state)
            return value if math.isfinite(value) else -1
        except (TypeError,ValueError,AttributeError):return -1

    def weather_entities(self):
        return list(dict.fromkeys([*self.config.get("multipleweather_entities",[]), *([self.config["weather_entity"]] if self.config.get("weather_entity") else [])]))

    def settings(self):
        zones=[]
        for z in self.config.get("zones",[]):
            ids=[]
            for entity_id in z["area_entities"]:
                item=self.hass.states.get(entity_id)
                ids.append(str(item.attributes.get("hash","missing")) if item else "missing")
            zones.append(Zone(
                id=z["id"],name=z["name"],area_ids=tuple(ids),angles=tuple(z["angles"]),
                spacing_cm=z["spacing_cm"],perimeter_laps=z["perimeter_laps"],interval_days=z["interval_days"],
                min_start_battery=z["minimum_battery"],handoff_battery=self.config.get("handoff_minimum_battery",60),
                blade_height=z.get("blade_height"),speed=z.get("speed"),
                cutting_path_mode=z.get("cutting_path_mode",0),mow_order=z.get("mow_order",1),obstacle_laps=z.get("obstacle_laps",1),
                not_before=z.get("not_before"),group=z.get("group",""),group_anchor=z.get("group_anchor",False),seasonal_intervals=z.get("seasonal_intervals",{}),
                stationary_return_seconds=z.get("stationary_return_seconds",0)))
        thresholds={key:self.config.get(key,default) for key,default in (
            ("reserve_battery",25),("max_retries",2),("ack_timeout",120),("freshness_seconds",120),
            ("charging_stable_seconds",60),("recovery_cooldown",120),("return_timeout",1200),
            ("recovery_observation_seconds",120),("recovery_grace_seconds",30),
            ("contact_confirmation_seconds",120),("contact_battery_gain",2))}
        return Settings(zones=tuple(zones),window_start=self.config.get("start_time","09:00:00"),window_end=self.config.get("end_time","19:00:00"),
            weekdays=tuple(self.config.get("weekdays",range(7))),excluded_dates=tuple(self.config.get("excluded_dates",[])),
            season_months=tuple(self.config.get("season_months",range(1,13))),eligible_groups=tuple(self.config.get("eligible_groups",[])),
            resume_battery=recharge_target(self.config,self.state.checkpoint,self._burn_rates.get(self.state.active_zone)),
            allow_handoff=self.config.get("allow_handoff",True),auto_recovery=self.config.get("auto_recovery",True),
            weather_required=bool(self.weather_entities()),protect_unowned_work=self.config.get("protect_unowned_work",False),rest_days_between_plans=self.config.get("rest_days_between_plans",0),**thresholds)

    def registry_key(self, entity):
        reg=er.async_get(self.hass).async_get(entity)
        return getattr(reg,"translation_key",None) or ""

    def map_sync_state(self):
        registry=er.async_get(self.hass)
        mower=registry.async_get(self.config.get("mower_entity",""))
        for item in getattr(registry,"entities",{}).values():
            if item.device_id==getattr(mower,"device_id",None) and getattr(item,"translation_key",None)=="map_sync_status":
                return self.hass.states.get(item.entity_id)
        return None

    def cached_map_identity(self):
        """Shape-gated Mammotion-HA 0.6.19-beta4 / PyMammotion 0.10.11 adapter.

        Only cached static map geometry is read; no cloud/device requests occur.
        Unknown frame types fail closed rather than silently losing safety zones.
        """
        registry=er.async_get(self.hass)
        entity=registry.async_get(self.config["mower_entity"])
        matches=[]
        for entry in self.hass.config_entries.async_entries("mower_simulator" if entity.platform=="mower_simulator" else "mammotion"):
            for mower in getattr(getattr(entry,"runtime_data",None),"mowers",[]):
                coordinator=mower.reporting_coordinator
                if entity.unique_id.startswith(coordinator.unique_name):matches.append(coordinator)
        if len(matches)!=1:raise ValueError("Unsupported coordinator ownership")
        mapping=matches[0].data.map
        buckets=("area","path","obstacle","dump","svg","visual_safety_zone","visual_obstacle_zone","corridor_line","corridor_point","virtual_wall","no_go_zone_variant","no_go_zone")
        roots=mapping.area_root_hashlist
        if not isinstance(roots,list) or not roots or any(type(x) is not int or x<=0 for x in roots):raise ValueError("Missing static map manifest")
        if not isinstance(mapping.unknown_type_frames,dict) or mapping.unknown_type_frames:raise ValueError("Unknown map types")
        payload={"manifest":sorted(roots)}
        for name in buckets:
            bucket=getattr(mapping,name)
            if not isinstance(bucket,dict):raise ValueError("Unsupported map bucket")
            frames={}
            for key,value in bucket.items():
                if not str(key).isdigit():raise ValueError("Unsupported map hash")
                if not is_dataclass(value):raise ValueError("Unsupported map frame list")
                item=asdict(value)
                if not isinstance(item.get("data"),list) or not item["data"] or item.get("total_frame")!=len(item["data"]):raise ValueError("Incomplete map frames")
                canonical=[]
                for frame in sorted(item["data"],key=lambda f:f.get("current_frame",0)):
                    geometry="svg_message" if name=="svg" else "data_couple"
                    if geometry not in frame:raise ValueError("Missing frame geometry")
                    # Exclude transport result/version/time/name fields, not geometry.
                    canonical.append({k:frame[k] for k in (geometry,"type","paternal_hash_a","paternal_hash_b") if k in frame})
                frames[str(key)]=canonical
            payload[name]=frames
        ids={a for z in self.settings().zones for a in z.area_ids}
        if not ids <= set(payload["area"]):raise ValueError("Configured area missing")
        return hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False,separators=(",",":")).encode()).hexdigest()

    async def refresh_map_identity(self):
        """Read a synchronous in-process snapshot; retain only a digest."""
        registry=er.async_get(self.hass)
        mower=registry.async_get(self.config.get("mower_entity",""))
        if getattr(mower,"platform",None)=="mower_simulator" and self.entity("mower_entity") is not None and self.entity("mower_entity").attributes.get("map_revision"):return
        self._geometry_revision=None; self._geometry_checked_at=0
        sync=self.map_sync_state()
        if not self.fresh(sync) or sync.state!="synced":return
        try:
            digest=self.cached_map_identity()
            self._geometry_revision=digest
            self._geometry_checked_at=dt_util.utcnow().timestamp()
        except (AttributeError,TypeError,ValueError,KeyError):
            self._geometry_revision=None

    def native_map_revision(self):
        registry=er.async_get(self.hass)
        mower=registry.async_get(self.config.get("mower_entity",""))
        if getattr(mower,"platform",None)=="mower_simulator" and self.entity("mower_entity") is not None and self.entity("mower_entity").attributes.get("map_revision"):
            entity=self.entity("mower_entity")
            return entity.attributes.get("map_revision") if entity else None
        sync=self.map_sync_state()
        age=dt_util.utcnow().timestamp()-self._geometry_checked_at
        return self._geometry_revision if 0<=age<=120 and self.fresh(sync) and sync.state=="synced" else None

    def preflight(self):
        registry=er.async_get(self.hass); mower=registry.async_get(self.config.get("mower_entity",""))
        supported=bool(mower and mower.platform in {"mammotion","mower_simulator"})
        required=("mower_entity","battery_entity","progress_entity","charging_entity","activity_entity","error_entity","rain_entity","safety_entity","person_entity","blade_time_entity")
        checks={"supported_adapter":supported,"saved_state_readable":not self.storage_error,"telemetry_fresh":all(self.fresh(self.entity(k)) for k in DEVICE_TELEMETRY),"battery_and_progress_valid":all(0<=self.number(k)<=100 for k in ("battery_entity","progress_entity")),"start_action_available":self.hass.services.has_service("mammotion","start_mow"),"dock_action_available":self.hass.services.has_service("lawn_mower","dock")}
        members=[a for z in self.config.get("zones",[]) for a in z.get("area_entities",[])]
        hashes=[]; valid=bool(members)
        for eid in members:
            s=self.hass.states.get(eid); reg=registry.async_get(eid)
            h=str(s.attributes.get("hash","")) if s else ""
            valid=valid and bool(s and s.state not in BAD and reg and mower and reg.device_id==mower.device_id and h.isdigit() and int(h)>0)
            hashes.append(h)
        checks["areas_match_mower"]=valid and len(set(hashes))==len(hashes)
        checks["map_revision_available"]=self.native_map_revision() is not None
        checks["active_error_source"]=not self.registry_key(self.config.get("error_entity","")).startswith("error_")
        try:self.settings(); checks["settings_valid"]=True
        except (ValueError,KeyError,TypeError):checks["settings_valid"]=False
        checks["no_legacy_controller_enabled"]=not any(s.state=="on" and (s.entity_id=="input_boolean.mower_package_enabled" or s.entity_id.startswith("automation.mower_")) for s in self.hass.states.async_all())
        checks["weather_ready"]=self.weather_safe() is not None
        checks["rain_available"]=bool(self.entity("rain_entity") and self.entity("rain_entity").state in {"on","off"})
        checks["presence_available"]=bool(self.entity("person_entity") and self.entity("person_entity").state not in BAD)
        checks["recovery_bindings_ready"]=not self.config.get("auto_recovery",True) or (
            all(self.fresh(self.entity(k),min(90,self.config.get("freshness_seconds",120))) for k in ("tracker_entity","mileage_entity","rtk_entity"))
            and self.entity("rtk_entity").state.lower() in {"fix","rtk_fix"}
            and mileage_m(self.entity("mileage_entity").state,self.entity("mileage_entity").attributes.get("unit_of_measurement")) is not None)
        checks["recovery_action_available"]=not self.config.get("auto_recovery",True) or self.hass.services.has_service("lawn_mower","start_mowing")
        checks["cancel_action_available"]=not (self.config.get("auto_recovery",True) or self.config.get("allow_handoff",True)) or self.hass.services.has_service("mammotion","cancel_job")
        checks["pause_action_available"]=not self.config.get("auto_recovery",True) or self.hass.services.has_service("lawn_mower","pause")
        checks["forecast_configuration_valid"]=not self.config.get("forecast_enabled",False) or bool(self.weather_entities())
        checks["physical_safety_ready"]=bool(self.entity("safety_entity") and self.entity("safety_entity").state=="on")
        return checks

    async def refresh_forecasts(self):
        if not self.config.get("forecast_enabled",False) or not self.weather_entities():return
        now=dt_util.utcnow().timestamp()
        if now-self._forecast_checked_at<60:return
        self._forecast_checked_at=now
        try:
            async with asyncio.timeout(10):
                data=await self.hass.services.async_call("weather","get_forecasts",{"entity_id":self.weather_entities(),"type":"hourly"},blocking=True,return_response=True)
            if not isinstance(data,dict):raise ValueError("Invalid forecast response")
            self._forecasts={entity:{"at":now,"forecast":data.get(entity,{}).get("forecast")} for entity in self.weather_entities()}
        except Exception:
            self._forecasts={}

    def weather_safe(self):
        entities=self.weather_entities()
        if not entities:return True
        now=dt_util.utcnow().timestamp()
        tolerate=bool(self.config.get("light_rain_tolerance",False) and self.state.job_token and self._dry_launch_token==self.state.job_token)
        for entity in entities:
            weather=self.hass.states.get(entity)
            if not self.fresh(weather,self.config.get("weather_max_age",1800)):return None
            safe=weather_condition(weather.state,weather.attributes,self.config.get("wind_limit_mps",10),self.config.get("minimum_temperature_c",5),tolerate)
            if safe is not True:return safe
            if self.config.get("forecast_enabled",False):
                cached=self._forecasts.get(entity,{})
                if not 0<=now-cached.get("at",0)<=self.config.get("weather_max_age",1800):return None
                safe=forecast_safe(cached.get("forecast"),weather.attributes,now,self.config.get("forecast_horizon_hours",6),self.config.get("forecast_probability_threshold",50),self.config.get("wind_limit_mps",10),self.config.get("minimum_temperature_c",5))
                if safe is not True:return safe
        return True

    def motion_evidence(self):
        """Fresh GPS + odometer + RTK; a state label alone never proves movement."""
        tracker=self.entity("tracker_entity"); mileage=self.entity("mileage_entity"); rtk=self.entity("rtk_entity")
        if not all(self.fresh(item,min(90,self.config.get("freshness_seconds",120))) for item in (tracker,mileage,rtk)):
            self._motion_anchor=None; self._travel_anchor=None; self._motion_key=None
            return False,0,False
        if rtk.state.lower() not in {"fix","rtk_fix"}:
            self._motion_anchor=None; self._travel_anchor=None; self._motion_key=None
            return False,0,False
        try:
            lat=float(tracker.attributes["latitude"]); lon=float(tracker.attributes["longitude"])
            distance=mileage_m(mileage.state,mileage.attributes.get("unit_of_measurement"))
            if not math.isfinite(lat) or not math.isfinite(lon) or not -90<lat<90 or not -180<lon<180 or not lat or not lon or distance is None:
                raise ValueError("Invalid positioning evidence")
        except (ValueError,TypeError,KeyError):return False,0,False
        report=min(item.last_reported.timestamp() for item in (tracker,mileage,rtk))
        current=(lat,lon,distance,self.number("progress_entity"),self.number("blade_time_entity"))
        key=(report,current)
        if key==self._motion_key:return self._motion_result,report,True
        moving=False
        self._travel_moving=False
        if self._travel_anchor is not None:
            self._travel_moving=distance_m(self._travel_anchor[:2],current[:2])>=5 or distance-self._travel_anchor[2]>=10
        if self._travel_anchor is None or self._travel_moving:self._travel_anchor=current[:3]
        if self._motion_anchor is not None:
            old=self._motion_anchor
            moving=self._travel_moving or current[3]>old[3] or current[4]>old[4]
            if distance<old[2] or current[4]<old[4]:
                self._motion_anchor=current
                return False,0,False
        if moving or self._motion_anchor is None:self._motion_anchor=current
        if moving:self._motion_at=report
        self._motion_key=key; self._motion_result=moving
        return moving,report,True

    def fault_evidence(self,health):
        if health is None or health.state not in CLEAR_HEALTH:return None,False,False
        code=self.entity("recent_fault_code_entity"); stamp=self.entity("recent_fault_time_entity")
        if not code and not stamp:return None,True,False
        if not self.fresh(code) or not self.fresh(stamp):return None,False,False
        at=event_timestamp(stamp.state); now=dt_util.utcnow().timestamp()
        scoped=bool(self.state.job_token and at>=getattr(self.state,"last_launch_at",self.state.last_dispatch_at) and 0<=now-at<=900)
        if not scoped:return None,True,False
        return code.state,code.state in (RECOVERABLE_CODES | {"0","0.0","none","clear"}),code.state in RECOVERABLE_CODES

    def learn_recharge(self,obs):
        if not self.state.job_token or not obs.working:return
        sample=(self.state.job_token,obs.progress,obs.battery,self.number("blade_time_entity"))
        if self._burn_sample is None or self._burn_sample[0]!=sample[0]:
            self._burn_sample=sample;return
        old=self._burn_sample
        progress=sample[1]-old[1]; used=old[2]-sample[2]
        if progress>=10 and used>0 and sample[3]>old[3]:
            rate=used/progress
            if 0<rate<=2:self._burn_rates[self.state.active_zone]=rate
            self._burn_sample=sample

    async def request_telemetry(self):
        """Bounded background refresh for owned work; never starts a report stream."""
        try:
            async with asyncio.timeout(10):
                await self.hass.services.async_call("homeassistant","update_entity",{"entity_id":[self.config[k] for k in DEVICE_TELEMETRY if self.config.get(k)]},blocking=True)
        except Exception:pass

    def observation(self):
        now=dt_util.utcnow().timestamp(); mower=self.entity("mower_entity"); activity=self.entity("activity_entity")
        blade_state=self.entity("blade_time_entity"); progress_state=self.entity("progress_entity")
        blade=self.number("blade_time_entity")
        reported=blade_state.last_reported.timestamp() if blade_state else 0
        if self.fresh(blade_state) and reported>self._last_blade_reported:
            if self._last_blade is not None and blade>self._last_blade:
                self._cutting_proof_at=reported
            if blade>=0:self._last_blade=blade
            self._last_blade_reported=reported
        # A proof belongs to a sensor report, never to a 60-second boolean latch.
        # Progress must be reported no earlier than that proof, after this job's
        # dispatch. A stale 100% left over from a previous job cannot complete it.
        progress_at=progress_state.last_reported.timestamp() if progress_state else 0
        cutting_evidence=bool(self.state.last_dispatch_at < self._cutting_proof_at <= progress_at
                              and 0 <= now-self._cutting_proof_at <= 120)
        working=bool(mower and mower.state=="mowing" and activity and activity.state=="MODE_WORKING" and cutting_evidence)
        r=self.entity("rain_entity"); safety=self.entity("safety_entity"); p=self.entity("person_entity"); error=self.entity("error_entity")
        code,fault_safe,fault_recoverable=self.fault_evidence(error)
        moving,motion_at,motion_valid=self.motion_evidence()
        health_clear=bool(error and error.state in CLEAR_HEALTH)
        environmental_health=bool(error and error.state in {"rain","rain_protection","low_battery","non_working_hours","night_protection"})
        errors=None if health_clear or environmental_health else "device_error"
        if not fault_safe and health_clear:errors="critical_or_unavailable_fault"
        if r and r.state=="on":self._last_wet=now
        rain=(r.state=="on" if r and r.state in {"on","off"} else None)
        if environmental_health and error.state in {"rain","rain_protection"}:rain=True
        if rain is False and self._last_wet and now-self._last_wet<self.config.get("rain_dry_minutes",30)*60:rain=True
        if working and rain is False and self.weather_safe() is True:self._dry_launch_token=self.state.job_token
        native_mode=activity.state if activity else "unavailable"
        recoverable=bool((self.state.job_token or self.state.pending_command=="dock") and health_clear and fault_safe and motion_valid and
            native_mode in {"MODE_PAUSE","MODE_READY","MODE_WORKING","MODE_RETURNING","MODE_CHARGING_PAUSE"} and
            (fault_recoverable or native_mode in {"MODE_PAUSE","MODE_READY","MODE_RETURNING","MODE_CHARGING_PAUSE"} or (native_mode=="MODE_WORKING" and not working)))
        if errors is not None:
            key=(errors,code)
            if key!=self._last_fault_key:
                self._fault_journal.append({"at":now,"category":errors,"code":code if isinstance(code,str) and code.isdigit() and len(code)<=6 else None})
                self._fault_journal=self._fault_journal[-20:]
            self._last_fault_key=key
        else:self._last_fault_key=None
        checks=self.preflight()
        telemetry_ok=checks["telemetry_fresh"] and checks["battery_and_progress_valid"]
        settings=self.settings();ids=tuple(a for z in settings.zones for a in z.area_ids)
        revision=hashlib.sha256(json.dumps({"areas":sorted(ids),"revision":self.native_map_revision()},sort_keys=True).encode()).hexdigest()
        charging=self.entity("charging_entity")
        if charging and charging.state=="on":self._dry_launch_token=None
        # Availability-based presence/rain/safety inputs may legitimately retain
        # their state for days. Device telemetry itself must be freshly reported.
        # Use progress's report timestamp to deduplicate progress/completion samples.
        timestamp=progress_at if telemetry_ok else 0
        return Observation(timestamp=timestamp,mower_state=mower.state if mower else "unavailable",battery=self.number("battery_entity"),progress=self.number("progress_entity"),charging=bool(charging and charging.state=="on"),working=working,safe=bool(safety and safety.state=="on" and telemetry_ok and errors is None and native_mode not in {"MODE_LOCK","MODE_UPDATING"}),home=bool(p and p.state=="home"),rain=rain,weather_ok=self.weather_safe(),map_revision=revision,area_ids=ids,error=errors,moving=(moving or working),recoverable=recoverable,ready=native_mode=="MODE_READY",can_resume=native_mode=="MODE_PAUSE",motion_timestamp=motion_at if motion_valid else 0,travel_moving=self._travel_moving if motion_valid else None,completed=bool(cutting_evidence and self.state.seen_work and self.number("progress_entity")>=100))

    def final_start_gate(self,intent,obs):
        return self.final_motion_gate(intent,obs)

    def final_motion_gate(self,intent,obs):
        """Recheck critical inputs after durable save, immediately before dispatch."""
        checks=self.preflight()
        if not all(checks.get(key,False) for key in COMPATIBILITY_CHECKS):return False
        settings=self.settings(); now=dt_util.now()
        if not self.armed or self.hold or not obs.safe or not obs.home or obs.rain is not False or obs.weather_ok is not True:return False
        if not 0 <= now.timestamp()-obs.timestamp <= settings.freshness_seconds:return False
        if now.weekday() not in settings.weekdays or now.month not in settings.season_months or now.date().isoformat() in settings.excluded_dates or not settings.window_start <= now.strftime("%H:%M:%S") < settings.window_end:return False
        if intent.kind=="cancel":
            return bool((self.state.handoff_ready or self.state.active_zone) and obs.battery>settings.reserve_battery and not obs.error)
        if intent.kind=="resume":
            zone=next((z for z in settings.zones if z.id==self.state.active_zone),None)
            return bool(zone and (not zone.not_before or now.date().isoformat()>=zone.not_before) and (not settings.eligible_groups or zone.group in settings.eligible_groups) and settings.auto_recovery and obs.can_resume and obs.recoverable and not obs.moving and
                self.state.signature==route_signature(zone,obs.map_revision,self.state.frozen_profile) and
                obs.battery>=zone.handoff_battery and obs.battery>settings.reserve_battery and
                zone.profile(self.state.angle_indices.get(zone.id,0))==self.state.frozen_profile and self.state.job_token==intent.data.get("job_token"))
        zone=next((z for z in settings.zones if z.id==intent.data["zone_id"]),None)
        if zone and ((zone.not_before and now.date().isoformat()<zone.not_before) or (settings.eligible_groups and zone.group not in settings.eligible_groups)):return False
        if zone is None or self.state.job_token!=intent.data["job_token"] or self.state.active_zone!=zone.id:return False
        if list(zone.area_ids)!=intent.data["area_ids"] or self.state.signature!=route_signature(zone,obs.map_revision,intent.data["profile"]):return False
        if zone.profile(self.state.angle_indices.get(zone.id,0))!=intent.data["profile"]:return False
        if obs.mower_state=="docked" and obs.charging:
            floor=settings.resume_battery if intent.data["start_progress"]>0 else zone.min_start_battery
        elif intent.data.get("recovery") and settings.auto_recovery and obs.recoverable and obs.ready and not obs.moving:
            floor=zone.handoff_battery
        elif intent.data.get("in_place_handoff") and settings.allow_handoff and obs.ready and obs.mower_state in {"idle","paused","mowing"}:
            floor=zone.handoff_battery
        else:return False
        return obs.battery>=floor and obs.battery>settings.reserve_battery

    async def async_evaluate(self):
        async with self._lock:
            if self._stopped:return
            await self.refresh_map_identity()
            await self.refresh_forecasts()
            checks=self.preflight()
            if not all(checks.get(key,False) for key in COMPATIBILITY_CHECKS):
                self.reason="Not ready: "+", ".join(k.replace("_"," ") for k in COMPATIBILITY_CHECKS if not checks.get(k,False))+"."
                self.next_step="Correct the failed readiness checks; no new work will start."
                self.publish();return
            obs=self.observation(); now=dt_util.now()
            if self.armed and self.state.job_token and now.timestamp()-self._telemetry_requested_at>=60:
                self._telemetry_requested_at=now.timestamp()
                self.entry.async_create_background_task(self.hass,self.request_telemetry(),"Mower owned telemetry refresh")
            self.learn_recharge(obs)
            if not self.armed:
                preview=tick(self.settings(),self.state,obs,now,enabled=True,hold=False)
                self.reason="Observation only. "+preview.reason
                self.next_step="Release Hold new work, confirm setup, then enable Automatic control when ready."
                self.publish();return
            previous_state=State.from_dict(self.state.to_dict())
            before=self.state.phase
            before_reason=self.reason
            decision=tick(self.settings(),self.state,obs,now,enabled=True,hold=self.hold)
            self.state=decision.state; self.reason=decision.reason
            if previous_state.attention_code and not self.state.attention_code and (obs.working or obs.charging):
                self.entry.async_create_background_task(self.hass,self.notifier.async_clear_attention(),"Clear recovered mower notice")
            self.next_step="The controller will reevaluate when telemetry or eligibility changes."
            if self.state.seen_work:self.evidence["launch_observed"]=True
            if self.state.completed_dates:self.evidence["completion_observed"]=True
            if obs.charging and self.state.active_zone:self.evidence["charging_observed"]=True
            await self.save()
            # Persisted intents are never replayed on restart. A failed/uncertain call
            # leaves the pending state for telemetry reconciliation, not a retry loop.
            for intent in decision.intents:
                if intent.kind=="notify":
                    self.notify("complete" if intent.data.get("event")=="completed" else intent.data.get("event","attention"),intent.data.get("message",self.reason));continue
                if intent.kind in {"start","resume","cancel"}:await self.refresh_map_identity()
                fresh=self.observation()
                if not self.armed or not fresh.safe:
                    self.state=previous_state
                    await self.save()
                    self.reason="Command withheld because readiness changed; saved work is retained.";break
                if intent.kind in {"start","resume","cancel"}:
                    if not self.final_motion_gate(intent,fresh):
                        self.state=previous_state
                        self.state.recovery_candidate_at=0
                        self.state.recovery_last_sample_at=0
                        self.state.recovery_candidate_samples=0
                        if fresh.moving:self.state.stationary_since=0
                        await self.save()
                        self.reason="Start withheld because an operating rule, map, battery or ownership changed; saved work is retained.";break
                if intent.kind in {"dock","cancel_return"}:
                    native_mode=self.entity("activity_entity").state if self.entity("activity_entity") else None
                    expected=(native_mode=="MODE_RETURNING") if intent.kind=="cancel_return" else (native_mode in {"MODE_WORKING","MODE_PAUSE","MODE_READY"})
                    recovery_valid=True
                    if intent.kind=="cancel_return":
                        recovery_valid=bool(not self.hold and fresh.recoverable and not fresh.moving and fresh.motion_timestamp and 0<=dt_util.now().timestamp()-fresh.motion_timestamp<=min(90,self.settings().freshness_seconds))
                    elif previous_state.pending_command=="cancel_return":
                        recovery_valid=not self.hold
                    if not expected or not recovery_valid or fresh.charging or not self.fresh(self.entity("activity_entity")):
                        self.state=previous_state
                        self.state.recovery_candidate_at=0
                        self.state.recovery_last_sample_at=0
                        self.state.recovery_candidate_samples=0
                        await self.save()
                        self.reason="Return command withheld because native activity changed or recovery evidence changed; waiting for fresh telemetry."
                        break
                try:await self.dispatch(intent)
                except Exception:
                    self.reason="Command outcome is uncertain. Waiting for telemetry; no duplicate command will be sent."
                    self.notify("attention",self.reason)
            if before!=self.state.phase and not any(i.kind=="notify" for i in decision.intents):
                event={"starting":"resumed" if self.state.checkpoint else "started","charging":"charging","returning":"charging","final_return":"charging","paused":"hold"}.get(self.state.phase)
                if event:self.notify(event,self.reason)
            elif self.reason!=before_reason and not any(i.kind=="notify" for i in decision.intents) and self.reason.startswith(("Waiting for", "Manual hold", "Rain protection", "Weather protection")):
                self.notify("hold",self.reason)
            self.publish()

    def notify(self,event,message):
        # Notifications are not on the mower command's critical path.
        self.entry.async_create_background_task(self.hass,self.notifier.async_send(event,message,urgent=(event=="attention")),"Mower notification")

    async def dispatch(self,intent):
        if intent.kind=="cancel_return":
            await self.hass.services.async_call("lawn_mower","pause",{"entity_id":self.config["mower_entity"]},blocking=True);return
        if intent.kind=="resume":
            await self.hass.services.async_call("lawn_mower","start_mowing",{"entity_id":self.config["mower_entity"]},blocking=True);return
        if intent.kind=="cancel":
            await self.hass.services.async_call("mammotion","cancel_job",{"entity_id":self.config["mower_entity"]},blocking=True);return
        if intent.kind=="dock":
            await self.hass.services.async_call("lawn_mower","dock",{"entity_id":self.config["mower_entity"]},blocking=True);return
        self._dry_launch_token=None
        z=next(z for z in self.config["zones"] if z["id"]==intent.data["zone_id"])
        p=intent.data["profile"]
        data={"entity_id":self.config["mower_entity"],"areas":z["area_entities"],"is_mow":True,"is_dump":False,"is_edge":False,"modify":False,"plan_only":False,"toward":p["angle"],"toward_mode":0,"channel_width":p["spacing_cm"],"mowing_laps":p["perimeter_laps"],"channel_mode":p["cutting_path_mode"],"border_mode":p["mow_order"],"obstacle_laps":p["obstacle_laps"],"start_progress":intent.data["start_progress"]}
        for key in ("blade_height","speed"):
            if p.get(key) is not None:data[key]=p[key]
        await self.hass.services.async_call("mammotion","start_mow",data,blocking=True)

    def require_notification_confirmation(self):
        config=self.config.get("notifications",{})
        if (config.get("targets") or config.get("legacy_actions")) and not self.evidence["notification_received"]:
            raise HomeAssistantError("Send a test notification and confirm receipt before enabling control.")

    async def async_set_control(self,key,value):
        async with self._lock:
            if key=="armed" and value:
                await self.refresh_map_identity()
                self.require_notification_confirmation()
                if not self.evidence["setup_confirmed"] or not all(self.preflight().values()):raise HomeAssistantError("Complete setup confirmation and readiness checks first.")
                mower=self.entity("mower_entity")
                if not self.state.active_zone and mower.state!="docked":raise HomeAssistantError("Start with the mower docked; unowned work will not be adopted.")
            setattr(self,key,value);self.publish()
        await self.async_evaluate()

    async def async_button(self,key):
        # Evidence and runtime state use the same lock as evaluation and dispatch.
        # Notification delivery happens after persistence and outside that lock.
        send_test=False
        async with self._lock:
            if key=="notification_test":
                self.evidence["notification_test_requested"]=True
                self.evidence["notification_received"]=False
                send_test=True
            elif key=="notification_confirm":
                if not self.evidence["notification_test_requested"]:raise HomeAssistantError("Send a test notification first.")
                self.evidence["notification_received"]=True
            elif key=="commission":
                await self.refresh_map_identity()
                self.require_notification_confirmation()
                if not all(self.preflight().values()):raise HomeAssistantError("Resolve readiness checks before confirming setup.")
                self.evidence["setup_confirmed"]=True
            elif key=="reset_recovery":
                mower=self.entity("mower_entity")
                if self.armed or not mower or mower.state!="docked":raise HomeAssistantError("Disarm and dock the mower before resetting recovery after inspection.")
                self.state=reset_recovery(self.state)
            elif key!="preflight":
                raise HomeAssistantError("Unknown coordinator action.")
            await self.save()
        if send_test:
            await self.notifier.async_send("attention","Notification setup check. Confirm receipt in Home Assistant.",test=True)
        await self.async_evaluate()

    def status_value(self,key):
        if key=="status":return self.state.phase if self.armed else "observe"
        if key=="explanation":return self.reason[:255]
        if key=="checkpoint":return self.state.checkpoint
        if key=="readiness":return "ready" if all(self.preflight().values()) else "needs attention"
        if key=="commissioning":return "setup confirmed" if self.evidence["setup_confirmed"] else "setup incomplete"
        if key=="queue":return len(self.state.queue)
        if key=="retries":return self.state.retries
        return self.notifier.diagnostics().get("status","not tested")
