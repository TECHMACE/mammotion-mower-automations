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
    reserve_battery: int = 25
    resume_battery: int = 90
    max_retries: int = 3
    ack_timeout: int = 120
    freshness_seconds: int = 120
    charging_stable_seconds: int = 60
    recovery_cooldown: int = 120
    return_timeout: int = 1200
    allow_handoff: bool = False
    auto_recovery: bool = False
    rain_required: bool = True
    weather_required: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "zones", tuple(self.zones))
        object.__setattr__(self, "weekdays", tuple(self.weekdays))
        if not self.zones or len({z.id for z in self.zones}) != len(self.zones):
            raise ValueError("Supply areas with distinct stable ids")
        ids = [a for z in self.zones for a in z.area_ids]
        if len(set(ids)) != len(ids):
            raise ValueError("Native areas cannot belong to multiple logical areas")
        if any(type(getattr(self, key)) is not bool for key in ("allow_handoff", "auto_recovery", "rain_required", "weather_required")):
            raise ValueError("Policy switches must be booleans")
        if _clock(self.window_start) >= _clock(self.window_end):
            raise ValueError("Use an operating window within one local day")
        if not self.weekdays or any(type(d) is not int or d not in range(7) for d in self.weekdays):
            raise ValueError("Select at least one valid weekday")
        for value, low, high in ((self.reserve_battery, 15, 50), (self.resume_battery, 30, 100), (self.max_retries, 0, 3), (self.ack_timeout, 30, 600), (self.freshness_seconds, 10, 300), (self.charging_stable_seconds, 30, 600), (self.recovery_cooldown, 30, 1800), (self.return_timeout, 120, 7200)):
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
    last_observation_at: float = 0
    charging_since: float = 0
    was_charging: bool = False
    seen_work: bool = False
    start_checkpoint: float = 0
    generation: int = 0
    pending_command: str | None = None
    attention_code: str = ""
    handoff_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
            raise ValueError("Unsupported saved state version; motion must remain disarmed")
        if set(data) - cls.__dataclass_fields__.keys():
            raise ValueError("Unknown saved state fields")
        result = cls(**data)
        if result.phase not in PHASES or not isinstance(result.queue, list) or any(not isinstance(z, str) for z in result.queue) or len(set(result.queue)) != len(result.queue):
            raise ValueError("Invalid saved job state")
        for key in ("checkpoint", "start_checkpoint"):
            if not _number(getattr(result, key), 0, 100):
                raise ValueError("Invalid saved checkpoint")
        for key in ("retries", "return_retries", "generation"):
            if type(getattr(result, key)) is not int or getattr(result, key) < 0:
                raise ValueError("Invalid saved retry state")
        for key in ("last_dispatch_at", "last_observation_at", "charging_since"):
            if not _number(getattr(result, key), 0, 1e12):
                raise ValueError("Invalid saved timestamp")
        if not isinstance(result.frozen_profile, dict) or not isinstance(result.angle_indices, dict) or not isinstance(result.completed_dates, dict):
            raise ValueError("Invalid saved profile/history")
        if any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in result.angle_indices.items()):
            raise ValueError("Invalid angle history")
        for key, value in result.completed_dates.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("Invalid completion history")
            date.fromisoformat(value)
        if result.active_zone is not None and (not isinstance(result.active_zone, str) or not result.job_token or not result.signature):
            raise ValueError("Active work needs ownership and route identity")
        if result.pending_command not in (None, "start", "dock"):
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
    if new.active_zone or new.pending_command:
        new.phase = "reconciling"
    return new


def reset_recovery(state: State) -> State:
    """Explicit operator action only; never called by tick or progress observations."""
    new = _copy(state)
    new.retries = new.return_retries = 0
    if new.attention_code in {"recovery_exhausted", "return_exhausted"}:
        new.attention_code = ""
        new.phase = "paused" if new.active_zone else "idle"
    return new


def new_plan(settings: Settings, state: State, now: datetime) -> State:
    """Keep unfinished work first and append only due, non-completed areas."""
    new = _copy(state)
    for zone in settings.zones:
        previous = new.completed_dates.get(zone.id)
        due = previous is None or (now.date() - date.fromisoformat(previous)).days >= zone.interval_days
        if due and zone.id not in new.queue and zone.id != new.active_zone:
            new.queue.append(zone.id)
    return new


def _window(settings: Settings, now: datetime) -> bool:
    return now.weekday() in settings.weekdays and _clock(settings.window_start) <= now.time().replace(tzinfo=None) < _clock(settings.window_end)


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

    def dock(reason: str, retry: bool = False) -> Decision:
        if retry:
            if new.return_retries >= settings.max_retries:
                return attention("return_exhausted", "Return recovery attempts are exhausted; inspect the mower.")
            new.return_retries += 1
        new.phase = "returning" if new.active_zone else "final_return"
        new.pending_command = "dock"
        new.last_dispatch_at = instant
        new.handoff_ready = False
        return result(reason, Intent("dock", {"job_token": new.job_token, "reason": reason}))

    if not _number(obs.timestamp, 0, 1e12) or obs.timestamp > instant + 5 or instant - obs.timestamp > settings.freshness_seconds:
        return result("Waiting for fresh mower telemetry.")
    if not _number(obs.battery, 0, 100) or not _number(obs.progress, 0, 100):
        return result("Battery or progress telemetry is invalid.")
    if any(type(getattr(obs, key)) is not bool for key in ("charging", "working", "safe", "home", "moving", "recoverable", "completed")) or (obs.rain is not None and type(obs.rain) is not bool) or (obs.weather_ok is not None and type(obs.weather_ok) is not bool):
        return result("Safety telemetry is invalid.")
    if obs.mower_state not in {"docked", "mowing", "paused", "idle", "returning", "error"}:
        return result("Mower state is unavailable or unsupported.")
    if obs.timestamp < new.last_observation_at:
        return result("Ignoring out-of-order mower telemetry.")
    fresh_sample = obs.timestamp > new.last_observation_at
    new.last_observation_at = obs.timestamp
    if not obs.safe:
        return attention("physical_safety", "A physical safety condition needs attention; no movement will be requested.")
    if obs.error and not obs.recoverable:
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
    new.was_charging = obs.charging
    at_dock = obs.mower_state == "docked" and obs.charging
    charging_stable = at_dock and instant - new.charging_since >= settings.charging_stable_seconds
    # A start is acknowledged only by physical cutting evidence newer than dispatch.
    cutting_proven = new.active_zone and obs.working and obs.mower_state == "mowing" and obs.timestamp > new.last_dispatch_at
    if cutting_proven:
        new.pending_command = None
        new.phase = "mowing"
        new.attention_code = ""
        if fresh_sample and new.start_checkpoint <= obs.progress < 100:
            new.seen_work = True
        if new.seen_work:
            new.checkpoint = max(new.checkpoint, min(obs.progress, 99))
    # Completion requires a previously observed cutting sample in this owner session.
    if new.active_zone and new.seen_work and fresh_sample and obs.timestamp > new.last_dispatch_at and ((obs.progress >= 100 and obs.working) or obs.completed):
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
        new.handoff_ready = not at_dock and obs.mower_state in {"idle", "paused", "mowing"}
        return result(f"{name} completed; {'next area is queued' if new.queue else 'all queued work is complete'}.", Intent("notify", {"event": "completed", "message": f"{name} completed."}))
    # A previous request is never blindly repeated after a crash or a late ack.
    if new.pending_command == "start":
        if not at_dock and (obs.battery <= settings.reserve_battery or not obs.home or not _window(settings, now) or obs.rain is True or (settings.rain_required and obs.rain is None) or (settings.weather_required and obs.weather_ok is not True)):
            return dock("Conditions changed while awaiting launch acknowledgement; returning with saved work.")
        if instant - new.last_dispatch_at < settings.ack_timeout:
            return result("Start requested. Waiting for fresh physical activity; no duplicate start will be sent.")
        if not cutting_proven:
            if charging_stable and new.charging_since > new.last_dispatch_at:
                new.pending_command = None
                new.phase = "charging"
            else:
                return attention("start_unconfirmed", "Start could not be confirmed. Saved work is retained; inspect the mower or await a new charging session.")
    if new.pending_command == "dock":
        if at_dock:
            new.pending_command = None
            new.phase = "charging" if new.active_zone else "complete"
            new.attention_code = ""
        elif obs.mower_state == "returning":
            if instant - new.last_dispatch_at >= settings.return_timeout:
                return attention("return_timeout", "The mower has not confirmed charging within the return window; inspect its position and charger.")
            return result("Returning to the charger; waiting for charging contact.")
        elif instant - new.last_dispatch_at < settings.ack_timeout:
            return result("Return requested; waiting for the mower to reach the charger.")
        elif obs.recoverable and settings.auto_recovery and instant - new.last_dispatch_at >= settings.recovery_cooldown:
            return dock("Retrying a recoverable return interruption within the remaining budget.", retry=True)
        else:
            return attention("return_unconfirmed", "Charging was not confirmed after returning; inspect the mower and charger.")
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
        elif not _window(settings, now):
            protective_reason = "Returning because the mowing window ended; unfinished work is saved."
        if protective_reason:
            return dock(protective_reason)
    if new.active_zone and obs.mower_state == "returning":
        new.phase = "returning"
        return result("The mower is returning; waiting for charging before continuing saved work.")
    if new.active_zone and cutting_proven:
        return result(f"Mowing {zone_map[new.active_zone].name}; saved progress {new.checkpoint:g}%.")
    if new.active_zone and at_dock:
        new.phase = "charging"
    if not new.active_zone and new.phase == "complete" and not at_dock and obs.mower_state != "returning":
        return dock("All queued work is complete; returning to charge.")
    if not new.active_zone and obs.mower_state == "returning":
        return result("Waiting for the mower to finish returning.")
    if not new.active_zone and obs.mower_state == "mowing" and not new.handoff_ready:
        return result("Another job is active; this coordinator will not take ownership.")
    reason = _hold_reason(settings, obs, now, enabled, hold)
    if reason:
        return result(reason)
    if obs.error and not (new.active_zone and settings.auto_recovery and obs.recoverable):
        return result("Resolve the reported mower error before starting a new job.")
    if new.active_zone:
        zone = zone_map[new.active_zone]
        if at_dock:
            if not charging_stable:
                return result("Waiting for sustained charging contact before continuing.")
            if obs.battery < max(settings.resume_battery, settings.reserve_battery + 1):
                return result(f"Charging to {settings.resume_battery}% before continuing {zone.name} from {new.checkpoint:g}%.")
            if new.charging_since <= new.last_dispatch_at:
                return result("Waiting for a new confirmed charging session; the previous start will not be repeated.")
        elif obs.mower_state in {"paused", "idle", "error"}:
            new.phase = "paused"
            if not settings.auto_recovery or not obs.recoverable:
                return result("Mowing is paused; automatic recovery is not enabled for this condition.")
            if obs.battery < zone.handoff_battery:
                return dock("Insufficient battery for recovery; returning with the saved checkpoint.")
            if instant - new.last_dispatch_at < settings.recovery_cooldown:
                return result("Waiting for the recovery cooldown.")
            if new.retries >= settings.max_retries:
                return attention("recovery_exhausted", "Recovery attempts are exhausted; inspect the mower before resetting recovery.")
            new.retries += 1
        else:
            return result("Waiting for a safe state before continuing saved work.")
    else:
        new = new_plan(settings, new, now)
        if not new.queue:
            return result("No areas are due for mowing.")
        zone = zone_map[new.queue[0]]
        if not set(zone.area_ids) <= available:
            return result(f"Native areas for {zone.name} are unavailable.")
        if not at_dock:
            if not (settings.allow_handoff and new.handoff_ready and obs.mower_state in {"idle", "paused", "mowing"} and obs.battery >= zone.handoff_battery):
                if new.handoff_ready:
                    return dock("Returning before the next area; charger-free handoff is not eligible.")
                return result("A fresh job starts only from confirmed charging at the dock.")
        elif not charging_stable:
            return result("Waiting for sustained charging contact before starting.")
        elif obs.battery < zone.min_start_battery:
            return result(f"Charging to {zone.min_start_battery}% before starting {zone.name}.")
        new.generation += 1
        new.active_zone = zone.id
        new.job_token = f"{zone.id}:{new.generation}:{int(instant)}"
        new.frozen_profile = zone.profile(new.angle_indices.get(zone.id, 0))
        new.signature = route_signature(zone, obs.map_revision, new.frozen_profile)
        new.checkpoint = 0
        new.seen_work = False
    new.phase = "starting"
    new.pending_command = "start"
    new.last_dispatch_at = instant
    new.start_checkpoint = new.checkpoint
    new.handoff_ready = False
    new.attention_code = ""
    return result(f"Starting {zone.name}" + (f" from saved progress {new.checkpoint:g}%." if new.checkpoint else "."), Intent("start", {"zone_id": zone.id, "area_ids": list(zone.area_ids), "profile": dict(new.frozen_profile), "start_progress": new.checkpoint, "job_token": new.job_token, "in_place_handoff": not at_dock}))
