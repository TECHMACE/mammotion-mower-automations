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
        except (ValueError,TypeError,KeyError,OSError):
            self.storage_error=True
            self.reason="Saved state could not be read. Automatic control is blocked; preserve storage for diagnosis."

    async def save(self):
        if self.storage_error: raise HomeAssistantError("Saved state needs repair; no command was sent.")
        try: await self.store.async_save({"state":self.state.to_dict(),"evidence":self.evidence})
        except Exception:
            self.storage_error=True; self.armed=False
            raise HomeAssistantError("Could not save job state; control is disarmed.") from None

    async def async_start(self):
        entities=[v for k,v in self.config.items() if k.endswith("_entity") and v]
        entities += [a for z in self.config.get("zones",[]) for a in z["area_entities"]]
        @callback
        def changed(event):
            if not self._stopped: self.entry.async_create_background_task(self.hass,self.async_evaluate(),"Mower decision")
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
    def fresh(self,state,seconds=120):
        if state is None or state.state in BAD:return False
        age=(dt_util.utcnow()-state.last_reported).total_seconds()
        return 0 <= age <= seconds
    def number(self,key):
        s=self.entity(key)
        try:
            value=float(s.state)
            return value if math.isfinite(value) else -1
        except (TypeError,ValueError,AttributeError):return -1

    def settings(self):
        zones=[]
        for z in self.config.get("zones",[]):
            ids=[]
            for entity_id in z["area_entities"]:
                s=self.hass.states.get(entity_id)
                ids.append(str(s.attributes.get("hash","missing")) if s else "missing")
            zones.append(Zone(id=z["id"],name=z["name"],area_ids=tuple(ids),angles=tuple(z["angles"]),spacing_cm=z["spacing_cm"],perimeter_laps=z["perimeter_laps"],interval_days=z["interval_days"],min_start_battery=z["minimum_battery"],handoff_battery=z["minimum_battery"],blade_height=z.get("blade_height"),speed=z.get("speed")))
        return Settings(zones=tuple(zones),window_start=self.config.get("start_time","09:00:00"),window_end=self.config.get("end_time","19:00:00"),reserve_battery=self.config.get("reserve_battery",25),resume_battery=self.config.get("resume_battery",85),allow_handoff=self.config.get("allow_handoff",False),auto_recovery=False,weather_required=bool(self.config.get("weather_entity")))

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
        checks["physical_safety_ready"]=bool(self.entity("safety_entity") and self.entity("safety_entity").state=="on")
        return checks

    def weather_safe(self):
        if not self.config.get("weather_entity"):return True
        w=self.entity("weather_entity")
        if not self.fresh(w,self.config.get("weather_max_age",1800)):return None
        if w.state in {"rainy","pouring","lightning","lightning-rainy","snowy","snowy-rainy","hail","exceptional"}:return False
        try:
            temp=float(w.attributes["temperature"]); wind=float(w.attributes["wind_speed"])
            tu=w.attributes.get("temperature_unit"); wu=w.attributes.get("wind_speed_unit")
            if tu=="°F":temp=(temp-32)*5/9
            elif tu!="°C":return None
            factors={"m/s":1,"km/h":1/3.6,"mph":0.44704,"kn":0.514444}
            if wu not in factors or not all(math.isfinite(x) for x in (temp,wind)):return None
            gust=float(w.attributes.get("wind_gust_speed",wind))
            if not math.isfinite(gust):return None
            return temp>0 and max(wind,gust)*factors[wu] <= self.config.get("wind_limit_mps",11.2)
        except (KeyError,TypeError,ValueError):return None

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
        errors=None if error and error.state in {"0","0.0","none","None","clear","normal"} else "device_error"
        checks=self.preflight()
        telemetry_ok=checks["telemetry_fresh"] and checks["battery_and_progress_valid"]
        settings=self.settings();ids=tuple(a for z in settings.zones for a in z.area_ids)
        revision=hashlib.sha256(json.dumps({"areas":sorted(ids),"revision":self.native_map_revision()},sort_keys=True).encode()).hexdigest()
        charging=self.entity("charging_entity")
        # Availability-based presence/rain/safety inputs may legitimately retain
        # their state for days. Device telemetry itself must be freshly reported.
        # Use progress's report timestamp to deduplicate progress/completion samples.
        timestamp=progress_at if telemetry_ok else 0
        return Observation(timestamp=timestamp,mower_state=mower.state if mower else "unavailable",battery=self.number("battery_entity"),progress=self.number("progress_entity"),charging=bool(charging and charging.state=="on"),working=working,safe=bool(safety and safety.state=="on" and telemetry_ok and errors is None),home=bool(p and p.state=="home"),rain=(r.state=="on" if r and r.state in {"on","off"} else None),weather_ok=self.weather_safe(),map_revision=revision,area_ids=ids,error=errors,moving=working,recoverable=False,completed=bool(cutting_evidence and self.state.seen_work and self.number("progress_entity")>=100))

    def final_start_gate(self,intent,obs):
        """Recheck critical inputs after durable save, immediately before dispatch."""
        checks=self.preflight()
        if not all(checks.get(key,False) for key in COMPATIBILITY_CHECKS):return False
        settings=self.settings(); now=dt_util.now()
        if not self.armed or self.hold or not obs.safe or not obs.home or obs.rain is not False or obs.weather_ok is not True:return False
        if not 0 <= now.timestamp()-obs.timestamp <= settings.freshness_seconds:return False
        if now.weekday() not in settings.weekdays or not settings.window_start <= now.strftime("%H:%M:%S") < settings.window_end:return False
        zone=next((z for z in settings.zones if z.id==intent.data["zone_id"]),None)
        if zone is None or self.state.job_token!=intent.data["job_token"] or self.state.active_zone!=zone.id:return False
        if list(zone.area_ids)!=intent.data["area_ids"] or self.state.signature!=route_signature(zone,obs.map_revision,intent.data["profile"]):return False
        if zone.profile(self.state.angle_indices.get(zone.id,0))!=intent.data["profile"]:return False
        if obs.mower_state=="docked" and obs.charging:
            floor=settings.resume_battery if intent.data["start_progress"]>0 else zone.min_start_battery
        elif intent.data.get("in_place_handoff") and settings.allow_handoff and obs.mower_state in {"idle","paused","mowing"}:
            floor=zone.handoff_battery
        else:return False
        return obs.battery>=floor and obs.battery>settings.reserve_battery

    async def async_evaluate(self):
        async with self._lock:
            if self._stopped:return
            await self.refresh_map_identity()
            checks=self.preflight()
            if not all(checks.get(key,False) for key in COMPATIBILITY_CHECKS):
                self.reason="Not ready: "+", ".join(k.replace("_"," ") for k in COMPATIBILITY_CHECKS if not checks.get(k,False))+"."
                self.next_step="Correct the failed readiness checks; no new work will start."
                self.publish();return
            obs=self.observation(); now=dt_util.now()
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
                if intent.kind=="start":await self.refresh_map_identity()
                fresh=self.observation()
                if not self.armed or not fresh.safe:
                    self.state=previous_state
                    await self.save()
                    self.reason="Command withheld because readiness changed; saved work is retained.";break
                if intent.kind=="start":
                    if not self.final_start_gate(intent,fresh):
                        self.state=previous_state
                        await self.save()
                        self.reason="Start withheld because an operating rule, map, battery or ownership changed; saved work is retained.";break
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
        if intent.kind=="dock":
            await self.hass.services.async_call("lawn_mower","dock",{"entity_id":self.config["mower_entity"]},blocking=True);return
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
