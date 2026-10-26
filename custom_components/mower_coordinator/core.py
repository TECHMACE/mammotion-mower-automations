"""Deterministic mower policy. No Home Assistant, networking, clocks or device I/O.

The host must serialize calls, durably save Decision.state BEFORE dispatching its
intents, and never replay intents from storage. ``working`` means fresh physical
cutting evidence, not just an accepted command. A strict observer host discards
all intents. ``enabled`` only arms starts; owned protective returns remain active.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, date, time
from hashlib import sha256
import json
from math import isfinite
from typing import Any

SCHEMA_VERSION = 1
PHASES = {"idle", "starting", "mowing", "returning", "charging", "paused", "attention", "quarantined", "final_return", "complete", "reconciling"}


def _number(value: Any, minimum: float, maximum: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and minimum <= value <= maximum


def _clock(value: str) -> time:
    result = time.fromisoformat(value)
    if result.tzinfo is not None:
        raise ValueError("Operating hours must be local clock times")
    return result


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    area_ids: tuple[str, ...]
    angles: tuple[int, ...] = (0, 90)
    spacing_cm: int = 11
    perimeter_laps: int = 2
    interval_days: int = 3
    min_start_battery: int = 90
    handoff_battery: int = 60
    blade_height: int | None = None
    speed: float | None = None
    cutting_path_mode: int = 0
    mow_order: int = 1
    obstacle_laps: int = 1
    not_before: str | None = None
    group: str = ""
    group_anchor: bool = False
    seasonal_intervals: dict[str, int] = field(default_factory=dict)
    stationary_return_seconds: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "area_ids", tuple(self.area_ids))
        object.__setattr__(self, "angles", tuple(self.angles))
        if not isinstance(self.id, str) or not self.id or not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Each area needs a stable id and a name")
        if not self.area_ids or len(set(self.area_ids)) != len(self.area_ids) or any(not isinstance(a, str) or not a for a in self.area_ids):
            raise ValueError("Native area identifiers must be nonempty and unique")
        if not self.angles or any(not _number(a, 0, 180) for a in self.angles):
            raise ValueError("Direction angles must be in 0–180 degrees")
        for label, value, lo, hi in (("spacing", self.spacing_cm, 8, 35), ("perimeter laps", self.perimeter_laps, 0, 4), ("interval", self.interval_days, 1, 365), ("starting battery", self.min_start_battery, 30, 100), ("handoff battery", self.handoff_battery, 30, 100), ("path mode", self.cutting_path_mode, 0, 3), ("mow order", self.mow_order, 0, 1), ("obstacle laps", self.obstacle_laps, 0, 4)):
            if not _number(value, lo, hi) or int(value) != value:
                raise ValueError(f"Invalid {label}")
        if self.not_before is not None: date.fromisoformat(self.not_before)
        if not isinstance(self.group,str): raise ValueError("Invalid group")
        if type(self.group_anchor) is not bool or (self.group_anchor and not self.group):raise ValueError("Group anchors need a named group")
        if not isinstance(self.seasonal_intervals,dict) or any(str(k) not in {str(m) for m in range(1,13)} or type(v) is not int or not 1<=v<=365 for k,v in self.seasonal_intervals.items()):raise ValueError("Invalid seasonal interval")
        if type(self.stationary_return_seconds) is not int or not 0<=self.stationary_return_seconds<=7200:raise ValueError("Invalid stationary deadline")
        if self.blade_height is not None and (not _number(self.blade_height, 20, 100) or int(self.blade_height) != self.blade_height):
            raise ValueError("Invalid cutting height")
        if self.speed is not None and not _number(self.speed, 0.1, 0.8):
            raise ValueError("Invalid cutting speed")

    def profile(self, angle_index: int) -> dict[str, Any]:
        return {"angle": self.angles[angle_index % len(self.angles)], "spacing_cm": self.spacing_cm,
                "perimeter_laps": self.perimeter_laps, "blade_height": self.blade_height,
                "speed": self.speed, "cutting_path_mode": self.cutting_path_mode,
                "mow_order": self.mow_order, "obstacle_laps": self.obstacle_laps}


@dataclass(frozen=True)
class Settings:
    zones: tuple[Zone, ...]
    window_start: str = "09:00"
    window_end: str = "19:00"
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)
    excluded_dates: tuple[str, ...] = ()
    season_months: tuple[int, ...] = tuple(range(1,13))
    eligible_groups: tuple[str, ...] = ()
    rest_days_between_plans: int = 0
    reserve_battery: int = 25
    resume_battery: int = 90
    max_retries: int = 3
    ack_timeout: int = 120
    freshness_seconds: int = 120
    charging_stable_seconds: int = 60
    contact_confirmation_seconds: int = 120
    contact_battery_gain: int = 2
    recovery_cooldown: int = 120
    recovery_observation_seconds: int = 120
    recovery_grace_seconds: int = 30
    return_timeout: int = 1200
    allow_handoff: bool = False
    auto_recovery: bool = False
    protect_unowned_work: bool = False
    rain_required: bool = True
    weather_required: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "zones", tuple(self.zones))
        object.__setattr__(self, "weekdays", tuple(self.weekdays))
        object.__setattr__(self,"excluded_dates",tuple(self.excluded_dates))
        object.__setattr__(self,"season_months",tuple(self.season_months))
        object.__setattr__(self,"eligible_groups",tuple(self.eligible_groups))
        for value in self.excluded_dates: date.fromisoformat(value)
        if type(self.rest_days_between_plans) is not int or not 0<=self.rest_days_between_plans<=30:raise ValueError("Invalid rest days")
        if not self.season_months or any(type(m) is not int or m not in range(1,13) for m in self.season_months):raise ValueError("Invalid season")
        if any(not isinstance(g,str) or not g for g in self.eligible_groups):raise ValueError("Invalid eligible groups")
        if not self.zones or len({z.id for z in self.zones}) != len(self.zones):
            raise ValueError("Supply areas with distinct stable ids")
        ids = [a for z in self.zones for a in z.area_ids]
        if len(set(ids)) != len(ids):
            raise ValueError("Native areas cannot belong to multiple logical areas")
        if any(type(getattr(self, key)) is not bool for key in ("allow_handoff", "auto_recovery", "protect_unowned_work", "rain_required", "weather_required")):
            raise ValueError("Policy switches must be booleans")
        if _clock(self.window_start) >= _clock(self.window_end):
            raise ValueError("Use an operating window within one local day")
        if not self.weekdays or any(type(d) is not int or d not in range(7) for d in self.weekdays):
            raise ValueError("Select at least one valid weekday")
        for value, low, high in ((self.reserve_battery, 15, 50), (self.resume_battery, 30, 100), (self.max_retries, 0, 3), (self.ack_timeout, 30, 600), (self.freshness_seconds, 10, 300), (self.charging_stable_seconds, 30, 600), (self.recovery_cooldown, 30, 1800), (self.return_timeout, 120, 7200), (self.recovery_observation_seconds, 30, 600), (self.recovery_grace_seconds, 15, 120), (self.contact_confirmation_seconds, 60, 600), (self.contact_battery_gain, 1, 5)):
            if not _number(value, low, high) or int(value) != value:
                raise ValueError("Invalid safety threshold")
        if self.resume_battery <= self.reserve_battery or any(min(z.min_start_battery, z.handoff_battery) <= self.reserve_battery for z in self.zones):
            raise ValueError("Departure thresholds must exceed return reserve")


@dataclass(frozen=True)
class Observation:
    timestamp: float
    mower_state: str
    battery: float
    progress: float
    charging: bool
    working: bool
    safe: bool
    home: bool
    rain: bool | None
    weather_ok: bool | None
    map_revision: str
    area_ids: tuple[str, ...]
    error: str | None = None
    moving: bool = False
    recoverable: bool = False
    completed: bool = False
    ready: bool = True
    can_resume: bool = True
    motion_timestamp: float | None = None
    travel_moving: bool | None = None


@dataclass
class State:
    version: int = SCHEMA_VERSION
    phase: str = "idle"
    queue: list[str] = field(default_factory=list)
    active_zone: str | None = None
    job_token: str | None = None
    checkpoint: float = 0
    signature: str = ""
    frozen_profile: dict[str, Any] = field(default_factory=dict)
    angle_indices: dict[str, int] = field(default_factory=dict)
    completed_dates: dict[str, str] = field(default_factory=dict)
    retries: int = 0
    return_retries: int = 0
    last_dispatch_at: float = 0
    last_launch_at: float = 0
    last_observation_at: float = 0
    charging_since: float = 0
    was_charging: bool = False
    seen_work: bool = False
    start_checkpoint: float = 0
    generation: int = 0
    pending_command: str | None = None
    attention_code: str = ""
    handoff_ready: bool = False
    recovery_candidate_at: float = 0
    recovery_candidate_progress: float = 0
    recovery_last_sample_at: float = 0
    recovery_candidate_samples: int = 0
    stationary_since: float = 0
    charging_baseline_battery: float = 0
    contact_retry_used: bool = False
    last_plan_completed: str | None = None
    unowned_guard: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
            raise ValueError("Unsupported saved state version; motion must remain disarmed")
        if set(data) - cls.__dataclass_fields__.keys():
            raise ValueError("Unknown saved state fields")
        result = cls(**data)
        if type(result.unowned_guard) is not bool:raise ValueError("Invalid unowned guard")
        if result.phase not in PHASES or not isinstance(result.queue, list) or any(not isinstance(z, str) for z in result.queue) or len(set(result.queue)) != len(result.queue):
            raise ValueError("Invalid saved job state")
        for key in ("checkpoint", "start_checkpoint", "recovery_candidate_progress", "charging_baseline_battery"):
            if not _number(getattr(result, key), 0, 100):
                raise ValueError("Invalid saved checkpoint")
        for key in ("retries", "return_retries", "generation", "recovery_candidate_samples"):
            if type(getattr(result, key)) is not int or getattr(result, key) < 0:
                raise ValueError("Invalid saved retry state")
        for key in ("last_dispatch_at", "last_launch_at", "last_observation_at", "charging_since", "recovery_candidate_at", "recovery_last_sample_at", "stationary_since"):
            if not _number(getattr(result, key), 0, 1e12):
                raise ValueError("Invalid saved timestamp")
        if not isinstance(result.frozen_profile, dict) or not isinstance(result.angle_indices, dict) or not isinstance(result.completed_dates, dict):
            raise ValueError("Invalid saved profile/history")
        if any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in result.angle_indices.items()):
            raise ValueError("Invalid angle history")
        if result.last_plan_completed is not None:date.fromisoformat(result.last_plan_completed)
        for key, value in result.completed_dates.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("Invalid completion history")
            date.fromisoformat(value)
        if result.active_zone is not None and (not isinstance(result.active_zone, str) or not result.job_token or not result.signature):
            raise ValueError("Active work needs ownership and route identity")
        if result.pending_command not in (None, "start", "resume", "cancel", "cancel_return", "dock"):
            raise ValueError("Invalid pending command")
        return result


@dataclass(frozen=True)
class Intent:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    state: State
    intents: tuple[Intent, ...]
    reason: str


def route_signature(zone: Zone, map_revision: str, profile: dict[str, Any]) -> str:
    return sha256(json.dumps({"zone": zone.id, "map": map_revision, "areas": list(zone.area_ids), "profile": profile}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _copy(state: State) -> State:
    return State.from_dict(json.loads(json.dumps(state.to_dict(), allow_nan=False)))


def reconcile_restart(state: State) -> State:
    """Preserve intent and budget; reconciling must not replay uncertain commands."""
    new = _copy(state)
    new.recovery_candidate_at = new.recovery_last_sample_at = 0
    new.recovery_candidate_samples = 0
    if new.active_zone or new.pending_command:
        new.phase = "reconciling"
    return new


def reset_recovery(state: State) -> State:
    """Explicit operator action only; never called by tick or progress observations."""
    new = _copy(state)
    new.retries = new.return_retries = 0
    new.contact_retry_used = False
    new.unowned_guard = False
    new.recovery_candidate_at = new.recovery_last_sample_at = 0
    new.recovery_candidate_samples = 0
    if new.attention_code in {"recovery_exhausted", "return_exhausted"}:
        new.attention_code = ""
        new.phase = "paused" if new.active_zone else "idle"
    return new


def new_plan(settings: Settings, state: State, now: datetime) -> State:
    """Retain unfinished work; schedule overdue groups and standalone areas."""
    new = _copy(state)
    if not new.active_zone and not new.queue and new.last_plan_completed:
        if (now.date()-date.fromisoformat(new.last_plan_completed)).days<=settings.rest_days_between_plans:
            return new
    def overdue(zone: Zone) -> float:
        previous=new.completed_dates.get(zone.id)
        if previous is None:return float("inf")
        return (now.date()-date.fromisoformat(previous)).days-zone.seasonal_intervals.get(str(now.month),zone.interval_days)
    def due(zone: Zone) -> bool:
        return _zone_eligible(settings,zone,now) and overdue(zone)>=0
    grouped={}
    for zone in settings.zones:
        if zone.group:grouped.setdefault(zone.group,[]).append(zone)
    enabled_groups={name for name,members in grouped.items()
                    if any(due(z) for z in members if z.group_anchor)}
    anchored_groups={name for name,members in grouped.items() if any(z.group_anchor for z in members)}
    candidates=[]
    for order,zone in enumerate(settings.zones):
        if not _zone_eligible(settings,zone,now) or zone.id in new.queue or zone.id==new.active_zone:continue
        if zone.group in anchored_groups:
            eligible=zone.group in enabled_groups and new.completed_dates.get(zone.id)!=now.date().isoformat()
        else:
            eligible=due(zone)
        if eligible:candidates.append((zone,order))
    candidates.sort(key=lambda pair:(-overdue(pair[0]),pair[1]))
    new.queue.extend(zone.id for zone,_ in candidates)
    return new


def _zone_eligible(settings: Settings, zone: Zone, now: datetime) -> bool:
    return (not zone.not_before or now.date()>=date.fromisoformat(zone.not_before)) and (not settings.eligible_groups or zone.group in settings.eligible_groups)


def _window(settings: Settings, now: datetime) -> bool:
    return now.date().isoformat() not in settings.excluded_dates and now.month in settings.season_months and now.weekday() in settings.weekdays and _clock(settings.window_start) <= now.time().replace(tzinfo=None) < _clock(settings.window_end)


def _hold_reason(settings: Settings, obs: Observation, now: datetime, enabled: bool, hold: bool) -> str:
    if not enabled:
        return "Automatic starts are disarmed."
    if hold:
        return "Manual hold is on."
    if not obs.home:
        return "Waiting for the operator to be home."
    if not _window(settings, now):
        return "Waiting for the allowed mowing window."
    if obs.rain is True:
        return "Waiting for dry conditions."
    if settings.rain_required and obs.rain is None:
        return "Rain protection is unavailable."
    if settings.weather_required and obs.weather_ok is not True:
        return "Weather protection is unavailable or conditions are unsuitable."
    return ""


def tick(settings: Settings, state: State, obs: Observation, now: datetime, enabled: bool = False, hold: bool = True) -> Decision:
    """Advance at most one physical intent. Caller owns persistence and execution.

    ``now`` must be timezone-aware in the installation's configured timezone.
    Map identity covers the adapter's native area hashes; label changes do not
    invalidate work. Any unknown sensor or physical safety error fails closed.
    """
    if now.tzinfo is None:
        raise ValueError("Provide timezone-aware installation time")
    new = _copy(state)
    instant = now.timestamp()

    def result(reason: str, *intents: Intent) -> Decision:
        return Decision(new, tuple(intents), reason)

    def attention(code: str, reason: str) -> Decision:
        changed = new.attention_code != code
        new.attention_code = code
        new.phase = "quarantined" if code == "route_changed" else "attention"
        return result(reason, *([Intent("notify", {"event": "attention", "message": reason})] if changed else []))

    def reset_candidate() -> None:
        new.recovery_candidate_at = new.recovery_last_sample_at = 0
        new.recovery_candidate_samples = 0

    def recovery_ready(contact: bool = False) -> bool:
        # A recoverable error is merely a candidate, never proof of obstruction.
        # The adapter supplies fresh physical GPS/mileage movement evidence.
        if obs.moving or obs.working or (not obs.recoverable and not contact):
            reset_candidate()
            return False
        if new.recovery_candidate_at and obs.progress > new.recovery_candidate_progress:
            reset_candidate()
            return False
        if new.recovery_last_sample_at and instant-new.recovery_last_sample_at>settings.freshness_seconds:
            reset_candidate()
        if not new.recovery_candidate_at:
            new.recovery_candidate_at = instant
            new.recovery_candidate_progress = obs.progress
            new.recovery_candidate_samples = 1
            new.recovery_last_sample_at = obs.timestamp
            return False
        if obs.timestamp > new.recovery_last_sample_at:
            new.recovery_candidate_samples += 1
            new.recovery_last_sample_at = obs.timestamp
        motion_at=obs.timestamp if obs.motion_timestamp is None else obs.motion_timestamp
        return (_number(motion_at,0,1e12) and new.recovery_candidate_at < motion_at <= instant+5
                and instant-motion_at<=settings.freshness_seconds
                and new.recovery_candidate_samples >= 2
                and instant - new.recovery_candidate_at >= settings.recovery_observation_seconds + settings.recovery_grace_seconds
                and instant - new.last_dispatch_at >= settings.recovery_cooldown)

    def dock(reason: str, retry: bool = False) -> Decision:
        if retry:
            if new.return_retries >= settings.max_retries:
                return attention("return_exhausted", "Return recovery attempts are exhausted; inspect the mower.")
            new.return_retries += 1
        reset_candidate()
        new.phase = "returning" if new.active_zone else "final_return"
        new.pending_command = "cancel_return" if obs.mower_state=="returning" and retry else "dock"
        new.last_dispatch_at = instant
        new.handoff_ready = False
        if obs.mower_state=="returning":
            if retry:return result("Canceling the stalled native return once before a guarded redock.",Intent("cancel_return",{"job_token":new.job_token,"reason":reason}))
            return result("The native mower is already returning; monitoring charging without toggling its return command.")
        return result(reason, Intent("dock", {"job_token": new.job_token, "reason": reason}))

    if not _number(obs.timestamp, 0, 1e12) or obs.timestamp > instant + 5 or instant - obs.timestamp > settings.freshness_seconds:
        return result("Waiting for fresh mower telemetry.")
    if not _number(obs.battery, 0, 100) or not _number(obs.progress, 0, 100):
        return result("Battery or progress telemetry is invalid.")
    if any(type(getattr(obs, key)) is not bool for key in ("charging", "working", "safe", "home", "moving", "recoverable", "completed", "ready", "can_resume")) or (obs.rain is not None and type(obs.rain) is not bool) or (obs.weather_ok is not None and type(obs.weather_ok) is not bool):
        return result("Safety telemetry is invalid.")
    if obs.mower_state not in {"docked", "mowing", "paused", "idle", "returning", "error"}:
        return result("Mower state is unavailable or unsupported.")
    if obs.timestamp < new.last_observation_at:
        return result("Ignoring out-of-order mower telemetry.")
    observation_gap=instant-new.last_observation_at>settings.freshness_seconds
    fresh_sample = obs.timestamp > new.last_observation_at
    new.last_observation_at = obs.timestamp
    contact_candidate=new.pending_command=="dock" and obs.mower_state in {"docked","idle"} and not obs.charging
    if obs.moving or obs.working or (not obs.recoverable and not contact_candidate):
        reset_candidate()
    travel_at=obs.timestamp if obs.motion_timestamp is None else obs.motion_timestamp
    travel_valid=(obs.travel_moving is None or type(obs.travel_moving) is bool) and _number(travel_at,0,1e12) and 0<=instant-travel_at<=settings.freshness_seconds
    travel_moving=(obs.moving or obs.working) if obs.travel_moving is None else obs.travel_moving
    if not travel_valid or travel_moving or observation_gap:
        new.stationary_since=0
    if travel_valid and not travel_moving and new.active_zone and not new.stationary_since:
        new.stationary_since=instant
    if not obs.safe:
        reset_candidate()
        return attention("physical_safety", "A physical safety condition needs attention; no movement will be requested.")
    if obs.error and not obs.recoverable:
        reset_candidate()
        return attention("unknown_error", "The mower reports an unsupported error; inspect it before continuing.")
    if not isinstance(obs.map_revision, str) or not obs.map_revision:
        return result("Waiting for a valid mower map.")
    if not isinstance(obs.area_ids, (tuple, list)) or any(not isinstance(a, str) or not a for a in obs.area_ids):
        return result("Native area telemetry is invalid.")
    zone_map = {zone.id: zone for zone in settings.zones}
    available = set(obs.area_ids)
    if new.active_zone:
        zone = zone_map.get(new.active_zone)
        if zone is None or not set(zone.area_ids) <= available or (new.frozen_profile != zone.profile(new.angle_indices.get(zone.id, 0)) or new.signature != route_signature(zone, obs.map_revision, new.frozen_profile)):
            return attention("route_changed", "The map or cutting profile changed. Saved work is preserved but cannot be resumed.")
    elif any(q not in zone_map for q in new.queue):
        return attention("route_changed", "A queued area was removed. Resolve the saved plan before continuing.")
    if new.phase == "quarantined":
        return result("Saved work is quarantined; review the changed map or profile.")
    if obs.charging and not new.was_charging:
        new.charging_since = instant  # First observed charging, independent of progress age.
        new.charging_baseline_battery = obs.battery
    new.was_charging = obs.charging
    at_dock = obs.mower_state == "docked" and obs.charging
    charging_stable = at_dock and instant - new.charging_since >= settings.charging_stable_seconds
    contact_confirmed = (charging_stable and instant-new.charging_since>=settings.contact_confirmation_seconds and (obs.battery>=100 or obs.battery-new.charging_baseline_battery>=settings.contact_battery_gain))
    # A start is acknowledged only by physical cutting evidence newer than dispatch.
    cutting_proven = new.active_zone and obs.working and obs.mower_state == "mowing" and obs.timestamp > new.last_dispatch_at
    if cutting_proven:
        if new.pending_command not in {"dock","cancel","cancel_return"}:
            new.pending_command = None
            new.phase = "mowing"
            new.attention_code = ""
        if fresh_sample and new.start_checkpoint <= obs.progress < 100:
            new.seen_work = True
        if new.seen_work:
            new.checkpoint = max(new.checkpoint, min(obs.progress, 99))
    # Completion requires a previously observed cutting sample in this owner session.
    if new.active_zone and new.pending_command not in {"dock","cancel","cancel_return"} and new.seen_work and fresh_sample and obs.timestamp > new.last_dispatch_at and ((obs.progress >= 100 and obs.working) or obs.completed):
        finished = new.active_zone
        name = zone_map[finished].name
        new.completed_dates[finished] = now.date().isoformat()
        new.angle_indices[finished] = new.angle_indices.get(finished, 0) + 1
        new.queue = [z for z in new.queue if z != finished]
        new.active_zone = new.job_token = None
        new.checkpoint = new.start_checkpoint = 0
        new.signature = ""
        new.frozen_profile = {}
        new.pending_command = None
        new.seen_work = False
        new.phase = "idle" if new.queue else "complete"
        if not new.queue:new.last_plan_completed=now.date().isoformat()
        new.handoff_ready = not at_dock and obs.mower_state in {"idle", "paused", "mowing", "returning"}
        return result(f"{name} completed; {'next area is queued' if new.queue else 'all queued work is complete'}.", Intent("notify", {"event": "completed", "message": f"{name} completed."}))
    # A previous request is never blindly repeated after a crash or a late ack.
    if new.pending_command in {"start", "resume"}:
        if not at_dock and (obs.battery <= settings.reserve_battery or not obs.home or not _window(settings, now) or not _zone_eligible(settings,zone_map[new.active_zone],now) or obs.rain is True or (settings.rain_required and obs.rain is None) or (settings.weather_required and obs.weather_ok is not True)):
            return dock("Conditions changed while awaiting launch acknowledgement; returning with saved work.")
        if instant - new.last_dispatch_at < settings.ack_timeout:
            return result("Start requested. Waiting for fresh physical activity; no duplicate start will be sent.")
        if not cutting_proven:
            if charging_stable and new.charging_since > new.last_dispatch_at:
                new.pending_command = None
                new.phase = "charging"
            elif (new.pending_command=="resume" or new.retries>0) and new.seen_work and obs.recoverable and settings.auto_recovery:
                if hold:
                    reset_candidate()
                    return result("Manual hold canceled automatic resume recovery.")
                if not recovery_ready():return result("Resume is unconfirmed; observing late physical telemetry before safe return fallback.")
                return dock("Native resume was not confirmed; returning with the saved checkpoint for a controlled restart.",retry=True)
            else:
                return attention("start_unconfirmed", "Start could not be confirmed. Saved work is retained; inspect the mower or await a new charging session.")
    if new.pending_command == "cancel":
        if obs.ready and obs.mower_state in {"idle","paused","docked"}:
            new.pending_command=None
        elif instant-new.last_dispatch_at>=settings.ack_timeout:
            return attention("cancel_unconfirmed","The previous task did not settle to ready; no new area will be dispatched.")
        else:
            return result("Cancel requested; waiting for the native task to settle to ready.")
    if new.pending_command == "cancel_return":
        if at_dock:
            # Cancellation may lose a race with arriving at the charger.
            new.pending_command="dock"
        elif hold:
            return result("Manual hold prevents the second stage of return recovery.")
        elif (obs.timestamp>new.last_dispatch_at and obs.mower_state in {"idle","paused"}
                and (obs.ready or obs.can_resume)):
            return dock("Native return is stopped and ready; issuing the single guarded redock.")
        elif instant-new.last_dispatch_at>=settings.ack_timeout:
            return attention("return_cancel_unconfirmed","Return cancellation did not settle to ready or paused; no dock toggle will be sent.")
        else:
            return result("Return cancellation requested; waiting for fresh ready or paused telemetry before redocking.")
    if new.pending_command == "dock":
        if at_dock:
            if not contact_confirmed:
                if instant-new.charging_since>=settings.return_timeout:
                    return attention("slow_charging","Charging contact has not produced the required sustained battery gain; inspect the contacts.")
                return result("Confirming sustained charging contact and battery gain.")
            new.pending_command = None
            new.phase = "charging" if new.active_zone else "complete"
            new.attention_code = ""
        elif obs.mower_state == "returning":
            if settings.auto_recovery and obs.recoverable and not obs.moving and not hold and instant-new.last_dispatch_at>=settings.ack_timeout:
                if new.return_retries>=settings.max_retries:
                    return attention("return_exhausted","Return recovery attempts are exhausted; inspect the mower.")
                if recovery_ready():
                    return dock("Return status is unchanged but physical movement stopped; retrying within the remaining budget.",retry=True)
            elif hold:
                reset_candidate()
            if instant - new.last_dispatch_at >= settings.return_timeout:
                return attention("return_timeout", "The mower has not confirmed charging within the return window; inspect its position and charger.")
            return result("Returning to the charger; waiting for charging contact.")
        elif instant - new.last_dispatch_at < settings.ack_timeout:
            return result("Return requested; waiting for the mower to reach the charger.")
        elif contact_candidate and settings.auto_recovery:
            if hold:return result("Manual hold canceled charger contact recovery; inspect the contacts.")
            if new.contact_retry_used:return attention("charging_contact","One charger contact retry was already used; inspect the contacts.")
            if not recovery_ready(contact=True):return result("Observing absent charger contact before one bounded redock attempt.")
            new.contact_retry_used=True
            return dock("Charging contact is absent; making one bounded redock attempt.",retry=True)
        elif obs.recoverable and settings.auto_recovery:
            if obs.moving:return result("Physical movement was observed; return recovery is deferred.")
            if hold:
                reset_candidate()
                return result("Manual hold canceled automatic return recovery.")
            if new.return_retries >= settings.max_retries:
                return attention("return_exhausted", "Return recovery attempts are exhausted; inspect the mower.")
            if not recovery_ready():
                return result("Observing a return interruption and allowing delayed movement telemetry before retrying.")
            return dock("Retrying a recoverable return interruption within the remaining budget.", retry=True)
        else:
            return attention("return_unconfirmed", "Charging was not confirmed after returning; inspect the mower and charger.")
    # Explicit opt-in protects external work without claiming its task/checkpoint.
    # Once protected, planning remains blocked until operator inspection/reset.
    if new.unowned_guard:
        return result("External work was protected. Inspect its native checkpoint, then disarm and reset while docked before coordinator planning can continue.")
    if not new.active_zone and not new.handoff_ready and obs.mower_state=="mowing" and enabled and settings.protect_unowned_work:
        if (obs.battery<=settings.reserve_battery or not obs.home or not _window(settings,now)
                or obs.rain is True or (settings.rain_required and obs.rain is None)
                or (settings.weather_required and obs.weather_ok is not True)):
            new.unowned_guard=True
            return dock("Protecting external mowing by returning to charge; its checkpoint will not be adopted or restarted.")
    # Safety return remains independent of start-arm and schedule holds.
    if new.active_zone and not at_dock and obs.mower_state != "returning":
        protective_reason = ""
        if obs.battery <= settings.reserve_battery:
            protective_reason = "Returning to preserve the battery reserve; unfinished work is saved."
        elif obs.rain is True or (settings.rain_required and obs.rain is None):
            protective_reason = "Returning because rain protection is active or unavailable; unfinished work is saved."
        elif settings.weather_required and obs.weather_ok is not True:
            protective_reason = "Returning because weather protection requires a hold; unfinished work is saved."
        elif not obs.home:
            protective_reason = "Returning because the operator is away; unfinished work is saved."
        elif not _window(settings, now) or not _zone_eligible(settings,zone_map[new.active_zone],now):
            protective_reason = "Returning because the mowing window ended; unfinished work is saved."
        zone=zone_map[new.active_zone]
        if not protective_reason and zone.stationary_return_seconds and new.stationary_since and instant-new.stationary_since>=zone.stationary_return_seconds:
            protective_reason="The area's stationary deadline expired; returning with unfinished work saved."
        if protective_reason:
            return dock(protective_reason)
    if new.active_zone and obs.mower_state == "returning":
        # Observe a native autonomous return as owned work, without reissuing it.
        new.phase = "returning"
        new.pending_command="dock"
        new.last_dispatch_at=instant
        reset_candidate()
        return result("The mower is returning; tracking charging and bounded return recovery.")
    if new.active_zone and cutting_proven:
        return result(f"Mowing {zone_map[new.active_zone].name}; saved progress {new.checkpoint:g}%.")
    if new.active_zone and at_dock:
        new.phase = "charging"
    if not new.active_zone and new.phase == "complete" and not at_dock and obs.mower_state != "returning":
        return dock("All queued work is complete; returning to charge.")
    if not new.active_zone and obs.mower_state == "returning" and not new.handoff_ready:
        return result("Waiting for the mower to finish returning.")
    if not new.active_zone and obs.mower_state == "mowing" and not new.handoff_ready:
        return result("Another job is active; this coordinator will not take ownership.")
    reason = _hold_reason(settings, obs, now, enabled, hold)
    if reason:
        reset_candidate()
        if new.handoff_ready and not at_dock:
            return dock("The next area must wait: " + reason)
        return result(reason)
    if obs.error and not (new.active_zone and settings.auto_recovery and obs.recoverable):
        return result("Resolve the reported mower error before starting a new job.")
    if new.active_zone:
        zone = zone_map[new.active_zone]
        if not _zone_eligible(settings,zone,now):return result("The saved area is not eligible under its date or group rules.")
        if at_dock:
            if not contact_confirmed:
                if instant-new.charging_since>=settings.return_timeout:return attention("slow_charging","Charging has not produced sustained battery gain; inspect the contacts.")
                return result("Waiting for sustained charging contact and battery gain before continuing.")
            if obs.battery < max(settings.resume_battery, settings.reserve_battery + 1):
                return result(f"Charging to {settings.resume_battery}% before continuing {zone.name} from {new.checkpoint:g}%.")
            if new.charging_since <= (new.last_launch_at or new.last_dispatch_at):
                return result("Waiting for a new confirmed charging session; the previous start will not be repeated.")
        elif obs.mower_state=="mowing":
            # MODE_WORKING is only a label. A verified stationary obstruction
            # receives a bounded return fallback, never an unsafe native resume.
            if not settings.auto_recovery or not obs.recoverable or obs.moving:
                return result("Waiting for physical cutting or a verified recoverable obstruction.")
            if new.retries>=settings.max_retries:
                return attention("recovery_exhausted","Stationary mowing recovery attempts are exhausted; inspect the mower.")
            if not recovery_ready():
                return result("Observing stationary mowing status and allowing delayed physical telemetry.")
            new.retries+=1
            return dock("Mowing status has no physical movement after observation; returning with the saved checkpoint for a controlled restart.")
        elif obs.mower_state in {"paused", "idle", "error"}:
            new.phase = "paused"
            if not settings.auto_recovery or not obs.recoverable:
                return result("Mowing is paused; automatic recovery is not enabled for this condition.")
            if obs.battery < zone.handoff_battery:
                return dock("Insufficient battery for recovery; returning with the saved checkpoint.")
            if instant - new.last_dispatch_at < settings.recovery_cooldown:
                return result("Waiting for the recovery cooldown.")
            if obs.moving:return result("Physical movement was observed; in-place recovery is deferred.")
            if new.retries >= settings.max_retries:
                return attention("recovery_exhausted", "Recovery attempts are exhausted; inspect the mower before resetting recovery.")
            if not recovery_ready():
                return result("Observing the stopped mower and allowing delayed movement telemetry before recovery.")
            if not obs.can_resume and not obs.ready:return result("Waiting for native ready or resumable paused state.")
            new.retries += 1
            reset_candidate()
            new.phase="starting"
            new.pending_command="resume" if obs.can_resume else "start"
            new.last_dispatch_at=instant
            new.last_launch_at=instant
            new.start_checkpoint=new.checkpoint
            return result(f"Continuing {zone.name} in place with the saved route.",Intent("resume" if obs.can_resume else "start",{"zone_id":zone.id,"job_token":new.job_token,"profile":dict(new.frozen_profile),"start_progress":new.checkpoint,"area_ids":list(zone.area_ids),"recovery":True,"in_place_handoff":False}))
        else:
            return result("Waiting for a safe state before continuing saved work.")
    else:
        new = new_plan(settings, new, now)
        if not new.queue:
            return result("The plan rest period is active or no eligible areas are due for mowing.")
        eligible=[z for z in new.queue if _zone_eligible(settings,zone_map[z],now)]
        if not eligible:return result("Queued areas are waiting for their date or group eligibility.")
        zone = zone_map[eligible[0]]
        if not set(zone.area_ids) <= available:
            return result(f"Native areas for {zone.name} are unavailable.")
        if not at_dock:
            if not (settings.allow_handoff and new.handoff_ready and obs.mower_state in {"idle", "paused", "mowing", "returning"} and obs.battery >= zone.handoff_battery):
                if new.handoff_ready:
                    return dock("Returning before the next area; charger-free handoff is not eligible.")
                return result("A fresh job starts only from confirmed charging at the dock.")
        elif not charging_stable:
            return result("Waiting for sustained charging contact before starting.")
        elif obs.battery < zone.min_start_battery:
            return result(f"Charging to {zone.min_start_battery}% before starting {zone.name}.")
        if not obs.ready:
            new.pending_command="cancel"
            new.last_dispatch_at=instant
            return result("Settling the completed native task before starting the next area.",Intent("cancel",{"job_token":new.job_token,"reason":"handoff"}))
        new.generation += 1
        new.active_zone = zone.id
        new.job_token = f"{zone.id}:{new.generation}:{int(instant)}"
        new.frozen_profile = zone.profile(new.angle_indices.get(zone.id, 0))
        new.signature = route_signature(zone, obs.map_revision, new.frozen_profile)
        new.checkpoint = 0
        new.seen_work = False
    if not obs.ready:
        new.pending_command="cancel"
        new.last_dispatch_at=instant
        return result("Settling the native task before restarting the saved route.",Intent("cancel",{"job_token":new.job_token,"reason":"checkpoint_restart"}))
    reset_candidate()
    new.phase = "starting"
    new.pending_command = "start"
    new.last_dispatch_at = instant
    new.last_launch_at = instant
    new.start_checkpoint = new.checkpoint
    new.handoff_ready = False
    new.attention_code = ""
    return result(f"Starting {zone.name}" + (f" from saved progress {new.checkpoint:g}%." if new.checkpoint else "."), Intent("start", {"zone_id": zone.id, "area_ids": list(zone.area_ids), "profile": dict(new.frozen_profile), "start_progress": new.checkpoint, "job_token": new.job_token, "in_place_handoff": not at_dock}))
