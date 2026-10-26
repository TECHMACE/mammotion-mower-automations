"""Guided local setup. Reads HA state only; never moves a mower or sends a message."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, time
import math
from typing import Any
from uuid import uuid4

import probatio as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from .notifications import validate_config as validate_notifications

DOMAIN = "mower_coordinator"
BINDINGS = {
    "battery_entity": "sensor", "progress_entity": "sensor",
    "charging_entity": "binary_sensor", "activity_entity": "sensor",
    "error_entity": "sensor", "rain_entity": "binary_sensor",
    "person_entity": "person", "weather_entity": "weather",
    "tracker_entity": "device_tracker", "blade_time_entity": "sensor",
    "safety_entity": "binary_sensor",
    "mileage_entity": "sensor", "rtk_entity": "sensor",
    "recent_fault_code_entity": "sensor", "recent_fault_time_entity": "sensor",
}
REQUIRED_BINDINGS = {"battery_entity", "progress_entity", "charging_entity", "activity_entity", "error_entity"}
RECOVERY_NUMBERS = {
    "contact_confirmation_seconds": (120, 60, 600),
    "contact_battery_gain": (2, 1, 5),
    "charging_stable_seconds": (60, 30, 600),
    "return_timeout": (1200, 120, 7200),
    "freshness_seconds": (120, 30, 300),
    "max_retries": (2, 1, 3),
    "recovery_cooldown": (120, 30, 1800),
    "ack_timeout": (120, 30, 600),
    "handoff_minimum_battery": (60, 30, 100),
    "recovery_observation_seconds": (120, 30, 600),
    "recovery_grace_seconds": (30, 15, 120),
}
EVENTS = ["attention", "complete", "charging", "resumed", "started", "hold"]


def _number(minimum: float, maximum: float, step: float = 1):
    return selector.NumberSelector({"min": minimum, "max": maximum, "step": step, "mode": "box"})


def _entity(domain: str | list[str], multiple: bool = False):
    return selector.EntitySelector({"domain": domain, "multiple": multiple})


def _finite_number(value: Any, minimum: float, maximum: float, integer: bool = False):
    if isinstance(value, bool):
        raise ValueError("invalid_number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError("invalid_number")
    if integer and int(result) != result:
        raise ValueError("invalid_number")
    return int(result) if integer else result


def validate_zone(data: dict, other_zones: list[dict], zone_id: str | None = None) -> dict:
    """Validate immutable identity and configurable profile, without HA access."""
    name = data.get("name", "")
    name = name.strip() if isinstance(name, str) else ""
    members = data.get("area_entities", [])
    if not name or len(name) > 80 or not isinstance(members, list) or not members:
        raise ValueError("invalid_zone")
    if any(not isinstance(x, str) or not x.startswith("switch.") for x in members) or len(set(members)) != len(members):
        raise ValueError("invalid_zone")
    for zone in other_zones:
        if zone["id"] != zone_id and set(members) & set(zone["area_entities"]):
            raise ValueError("overlapping_areas")
    try:
        raw = data.get("angles", "0,90")
        angles = raw.split(",") if isinstance(raw, str) else raw
        if not isinstance(angles, list) or not 1 <= len(angles) <= 12:
            raise ValueError
        angles = [_finite_number(x, 0, 180, True) for x in angles]
    except (TypeError, ValueError):
        raise ValueError("invalid_angles") from None
    result = {
        "id": zone_id or uuid4().hex,
        "name": name,
        "area_entities": members,
        "angles": angles,
        "spacing_cm": _finite_number(data.get("spacing_cm", 11), 8, 35, True),
        "perimeter_laps": _finite_number(data.get("perimeter_laps", 2), 0, 4, True),
        "interval_days": _finite_number(data.get("interval_days", 3), 1, 60, True),
        "minimum_battery": _finite_number(data.get("minimum_battery", 80), 30, 100, True),
    }
    for key, lo, hi in (("blade_height", 20, 100), ("speed", 0.2, 0.8)):
        if key in data and data[key] not in (None, ""):
            result[key] = _finite_number(data[key], lo, hi, key == "blade_height")
    for key, default, high in (("cutting_path_mode", 0, 3), ("mow_order", 1, 1), ("obstacle_laps", 1, 4)):
        result[key] = _finite_number(data.get(key, default), 0, high, True)
    result["not_before"] = date.fromisoformat(data["not_before"]).isoformat() if data.get("not_before") else None
    group = data.get("group", "")
    if not isinstance(group, str) or len(group) > 80:
        raise ValueError("invalid_zone")
    result["group"] = group.strip()
    anchor = data.get("group_anchor", False)
    if type(anchor) is not bool or (anchor and not result["group"]):
        raise ValueError("invalid_zone")
    result["group_anchor"] = anchor
    result["stationary_return_seconds"] = _finite_number(data.get("stationary_return_seconds", 0), 0, 7200, True)
    seasonal = data.get("seasonal_intervals", {})
    if not isinstance(seasonal, dict) or any(str(m) not in {str(n) for n in range(1, 13)} for m in seasonal):
        raise ValueError("invalid_zone")
    result["seasonal_intervals"] = {str(m): _finite_number(days, 1, 365, True) for m, days in seasonal.items()}
    return result


class WizardSteps:
    """Shared, validated setup steps for initial and subsequent configuration."""

    _settings: dict
    _editing: bool = False
    _zone_id: str | None = None

    def _schema_bindings(self):
        fields = {}
        for key, domain in BINDINGS.items():
            marker = vol.Required if key in REQUIRED_BINDINGS else vol.Optional
            opts = {"default": self._settings[key]} if self._settings.get(key) else {}
            fields[marker(key, **opts)] = _entity(["binary_sensor", "input_boolean"] if key == "safety_entity" else domain)
        return vol.Schema(fields)

    def _same_device(self, entity_id: str) -> bool:
        expected = self._settings.get("device_id")
        item = er.async_get(self.hass).async_get(entity_id)
        # Simulator and template entities may have no registry device. Runtime
        # preflight must still verify capabilities before enabling control.
        return not expected or (item is not None and item.device_id == expected)

    def _binding_errors(self, data):
        errors = {}
        for key, domain in BINDINGS.items():
            entity_id = data.get(key)
            if not entity_id:
                if key in REQUIRED_BINDINGS:
                    errors[key] = "missing_entity"
                continue
            domains = ("binary_sensor", "input_boolean") if key == "safety_entity" else (domain,)
            if not isinstance(entity_id, str) or entity_id.partition(".")[0] not in domains or self.hass.states.get(entity_id) is None:
                errors[key] = "missing_entity"
            elif key not in {"person_entity", "weather_entity", "rain_entity", "safety_entity"} and not self._same_device(entity_id):
                errors[key] = "wrong_device"
        selected = [data[k] for k in REQUIRED_BINDINGS if data.get(k)]
        if bool(data.get("recent_fault_code_entity")) != bool(data.get("recent_fault_time_entity")):
            errors["base"] = "fault_pair_required"
        if len(selected) != len(set(selected)):
            errors["base"] = "duplicate_binding"
        return errors

    async def async_step_bindings(self, user_input=None):
        errors = {}
        if user_input is not None:
            errors = self._binding_errors(user_input)
            if not errors:
                # Options overlay the original entry data. Keep explicit empty
                # values so clearing a selector cannot restore its old binding.
                self._settings.update({key: user_input.get(key) or "" for key in BINDINGS})
                return await self._after_step("zone")
        return self.async_show_form(step_id="bindings", data_schema=self._schema_bindings(), errors=errors)

    def _zone_schema(self):
        current = next((z for z in self._settings.get("zones", []) if z["id"] == self._zone_id), {})
        fields = {
            vol.Required("name", default=current.get("name", "Lawn")): selector.TextSelector(),
            vol.Required("area_entities", default=current.get("area_entities", [])): _entity("switch", True),
            vol.Required("angles", default=",".join(str(x) for x in current.get("angles", [0, 90]))): selector.TextSelector(),
            vol.Required("spacing_cm", default=current.get("spacing_cm", 11)): _number(8, 35),
            vol.Required("perimeter_laps", default=current.get("perimeter_laps", 2)): _number(0, 4),
            vol.Required("interval_days", default=current.get("interval_days", 3)): _number(1, 60),
            vol.Required("minimum_battery", default=current.get("minimum_battery", 80)): _number(30, 100),
        }
        for key, lo, hi, step in (("blade_height", 20, 100, 1), ("speed", .2, .8, .1)):
            opts = {"default": current[key]} if key in current else {}
            fields[vol.Optional(key, **opts)] = _number(lo, hi, step)
        for key, default, high in (("cutting_path_mode", 0, 3), ("mow_order", 1, 1), ("obstacle_laps", 1, 4)):
            fields[vol.Required(key, default=current.get(key, default))] = _number(0, high)
        fields[vol.Optional("not_before", **({"default": current["not_before"]} if current.get("not_before") else {}))] = selector.DateSelector()
        fields[vol.Optional("group", default=current.get("group", ""))] = selector.TextSelector()
        fields[vol.Required("group_anchor", default=current.get("group_anchor", False))] = selector.BooleanSelector()
        fields[vol.Optional("stationary_return_seconds", default=current.get("stationary_return_seconds", 0))] = _number(0, 7200)
        fields[vol.Optional("seasonal_intervals", default=current.get("seasonal_intervals", {}))] = selector.ObjectSelector()
        return vol.Schema(fields)

    async def async_step_zone(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                zone = validate_zone(user_input, self._settings.get("zones", []), self._zone_id)
                if zone["minimum_battery"] <= self._settings.get("reserve_battery", 25):
                    raise ValueError("invalid_battery")
                for entity_id in zone["area_entities"]:
                    state = self.hass.states.get(entity_id)
                    if state is None:
                        raise ValueError("missing_entity")
                    native_hash = state.attributes.get("hash")
                    if isinstance(native_hash, bool) or not str(native_hash).isdigit() or int(native_hash) <= 0:
                        raise ValueError("invalid_area_hash")
                    if not self._same_device(entity_id):
                        raise ValueError("wrong_device")
                zones = list(self._settings.get("zones", []))
                if self._zone_id is None:
                    zones.append(zone)
                else:
                    zones = [zone if z["id"] == self._zone_id else z for z in zones]
                self._settings["zones"] = zones
                self._zone_id = None
                return await self._after_step("more_areas")
            except (ValueError, TypeError) as exc:
                key = str(exc)
                errors["base"] = key if key in {"invalid_zone", "overlapping_areas", "invalid_angles", "invalid_number", "missing_entity", "invalid_area_hash", "wrong_device", "invalid_battery"} else "invalid_zone"
        return self.async_show_form(step_id="zone", data_schema=self._zone_schema(), errors=errors)

    async def async_step_more_areas(self, user_input=None):
        if user_input is not None:
            return await (self.async_step_zone() if user_input.get("add_another") else self.async_step_rules())
        return self.async_show_form(step_id="more_areas", data_schema=vol.Schema({vol.Required("add_another", default=False): selector.BooleanSelector()}), description_placeholders={"count": str(len(self._settings["zones"]))})

    async def async_step_rules(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                start, end = time.fromisoformat(user_input["start_time"]), time.fromisoformat(user_input["end_time"])
                if start >= end:
                    raise ValueError("invalid_window")
                reserve = _finite_number(user_input["reserve_battery"], 15, 50, True)
                resume = _finite_number(user_input["resume_battery"], 50, 100, True)
                if resume <= reserve or any(z["minimum_battery"] <= reserve for z in self._settings.get("zones", [])):
                    raise ValueError("invalid_battery")
                update = {"start_time": start.isoformat(), "end_time": end.isoformat(), "reserve_battery": reserve, "resume_battery": resume,
                          "weather_max_age": _finite_number(user_input.get("weather_max_age", 1800), 60, 7200, True),
                          "wind_limit_mps": _finite_number(user_input.get("wind_limit_mps", 10), 1, 20)}
                for key, (fallback, minimum, maximum) in RECOVERY_NUMBERS.items():
                    update[key] = _finite_number(user_input.get(key, self._settings.get(key, fallback)), minimum, maximum, True)
                if update["handoff_minimum_battery"] <= reserve:
                    raise ValueError("invalid_battery")
                for key in ("auto_recovery", "allow_handoff", "protect_unowned_work"):
                    value = user_input.get(key, self._settings.get(key, key != "protect_unowned_work"))
                    if type(value) is not bool:
                        raise ValueError("invalid_number")
                    update[key] = value
                self._settings.update(update)
                return await self._after_step("advanced")
            except (ValueError, TypeError, KeyError) as exc:
                errors["base"] = str(exc) if str(exc) in {"invalid_window", "invalid_battery", "invalid_number"} else "invalid_window"
        defaults = {"start_time": "09:00:00", "end_time": "19:00:00", "reserve_battery": 25, "resume_battery": 85, "weather_max_age": 1800, "wind_limit_mps": 10}
        fields = {}
        for key, fallback in defaults.items():
            value = self._settings.get(key, fallback)
            kind = selector.TimeSelector() if key.endswith("time") else {"reserve_battery": _number(15, 50), "resume_battery": _number(50, 100), "weather_max_age": _number(60, 7200), "wind_limit_mps": _number(1, 20, .1)}[key]
            fields[vol.Required(key, default=value)] = kind
        for key, (fallback, minimum, maximum) in RECOVERY_NUMBERS.items():
            fields[vol.Required(key, default=self._settings.get(key, fallback))] = _number(minimum, maximum)
        for key in ("auto_recovery", "allow_handoff", "protect_unowned_work"):
            fields[vol.Required(key, default=self._settings.get(key, key != "protect_unowned_work"))] = selector.BooleanSelector()
        return self.async_show_form(step_id="rules", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_advanced(self, user_input=None):
        if user_input is not None:
            return await self.async_step_calendar() if user_input.get("configure_advanced") else await self.async_step_notifications()
        return self.async_show_form(step_id="advanced", data_schema=vol.Schema({vol.Required("configure_advanced", default=False): selector.BooleanSelector()}))

    async def async_step_calendar(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                weekdays = [_finite_number(v, 0, 6, True) for v in user_input.get("weekdays", list(range(7)))]
                months = [_finite_number(v, 1, 12, True) for v in user_input.get("season_months", list(range(1, 13)))]
                if not weekdays or not months:
                    raise ValueError("invalid_calendar")
                raw_dates = user_input.get("excluded_dates", "")
                dates = [date.fromisoformat(v.strip()).isoformat() for v in raw_dates.split(",") if v.strip()]
                groups = user_input.get("eligible_groups", [])
                known = {z.get("group") for z in self._settings.get("zones", []) if z.get("group")}
                if not isinstance(groups, list) or any(g not in known for g in groups):
                    raise ValueError("invalid_calendar")
                rest = _finite_number(user_input.get("rest_days_between_plans", self._settings.get("rest_days_between_plans", 0)), 0, 30, True)
                self._settings.update(weekdays=sorted(set(weekdays)), season_months=sorted(set(months)), excluded_dates=sorted(set(dates)), eligible_groups=groups, rest_days_between_plans=rest)
                return await self._after_step("safety_weather")
            except (ValueError, TypeError, AttributeError):
                errors["base"] = "invalid_calendar"
        fields = {
            vol.Required("weekdays", default=[str(n) for n in self._settings.get("weekdays", range(7))]): selector.SelectSelector({"options": [{"value": str(i), "label": day} for i, day in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))], "multiple": True}),
            vol.Required("season_months", default=[str(n) for n in self._settings.get("season_months", range(1, 13))]): selector.SelectSelector({"options": [str(n) for n in range(1, 13)], "multiple": True}),
            vol.Optional("excluded_dates", default=",".join(self._settings.get("excluded_dates", []))): selector.TextSelector(),
            vol.Required("rest_days_between_plans", default=self._settings.get("rest_days_between_plans", 0)): _number(0, 30),
        }
        groups = sorted({z["group"] for z in self._settings.get("zones", []) if z.get("group")})
        if groups:
            fields[vol.Optional("eligible_groups", default=self._settings.get("eligible_groups", []))] = selector.SelectSelector({"options": groups, "multiple": True})
        return self.async_show_form(step_id="calendar", data_schema=vol.Schema(fields), errors=errors)

    async def _policy_step(self, step, user_input, numbers, booleans, next_step):
        errors = {}
        if user_input is not None:
            try:
                update = {key: _finite_number(user_input.get(key, self._settings.get(key, default)), low, high, True) for key, (default, low, high) in numbers.items()}
                for key, default in booleans.items():
                    value = user_input.get(key, self._settings.get(key, default))
                    if type(value) is not bool:
                        raise ValueError("invalid_number")
                    update[key] = value
                if step == "charging" and not self._settings.get("reserve_battery", 25) < update["recharge_min_target"] <= update["recharge_max_target"]:
                    raise ValueError("invalid_battery")
                if step == "safety_weather":
                    entities = user_input.get("multipleweather_entities", [])
                    if not isinstance(entities, list) or len(entities) > 5 or any(not isinstance(e, str) or not e.startswith("weather.") or self.hass.states.get(e) is None for e in entities):
                        raise ValueError("missing_entity")
                    update["multipleweather_entities"] = list(dict.fromkeys(entities))
                self._settings.update(update)
                return await self._after_step(next_step)
            except (ValueError, TypeError) as exc:
                errors["base"] = str(exc) if str(exc) in {"invalid_number", "invalid_battery", "missing_entity"} else "invalid_number"
        fields = {vol.Required(k, default=self._settings.get(k, d)): _number(lo, hi) for k, (d, lo, hi) in numbers.items()}
        fields.update({vol.Required(k, default=self._settings.get(k, d)): selector.BooleanSelector() for k, d in booleans.items()})
        if step == "safety_weather":
            fields[vol.Optional("multipleweather_entities", default=self._settings.get("multipleweather_entities", []))] = _entity("weather", True)
        return self.async_show_form(step_id=step, data_schema=vol.Schema(fields), errors=errors)

    async def async_step_safety_weather(self, user_input=None):
        return await self._policy_step("safety_weather", user_input, {"minimum_temperature_c": (5, 0, 20), "rain_dry_minutes": (30, 0, 1440), "forecast_horizon_hours": (6, 1, 48), "forecast_probability_threshold": (50, 1, 100)}, {"light_rain_tolerance": False, "forecast_enabled": False}, "charging")

    async def async_step_charging(self, user_input=None):
        return await self._policy_step("charging", user_input, {"recharge_buffer": (10, 0, 30), "recharge_min_target": (60, 30, 100), "recharge_max_target": (95, 50, 100)}, {"adaptive_recharge": True}, "notifications")

    async def async_step_notifications(self, user_input=None):
        errors = {}
        available_actions = [f"notify.{name}" for name in self.hass.services.async_services().get("notify", {}) if name not in {"send_message", "persistent_notification", "notify"}]
        if user_input is not None:
            config, errors = validate_notifications(user_input)
            if not errors:
                if any(self.hass.states.get(entity_id) is None for entity_id in config["targets"]):
                    errors["targets"] = "missing_entity"
                if any(f"notify.{action}" not in available_actions for action in config["legacy_actions"]):
                    errors["legacy_actions"] = "missing_action"
            if not errors:
                config["legacy_actions"] = [f"notify.{action}" for action in config["legacy_actions"]]
                self._settings["notifications"] = config
                return await self._after_step("review")
        current = self._settings.get("notifications", {})
        fields = {
            vol.Optional("targets", default=current.get("targets", [])): _entity("notify", True),
            vol.Optional("events", default=current.get("events", ["attention", "complete"])): selector.SelectSelector({"options": EVENTS, "multiple": True, "translation_key": "notification_event"}),
            vol.Required("quiet_start", default=current.get("quiet_start", "22:00:00")): selector.TimeSelector(),
            vol.Required("quiet_end", default=current.get("quiet_end", "08:00:00")): selector.TimeSelector(),
            vol.Required("urgent_override", default=current.get("urgent_override", False)): selector.BooleanSelector(),
        }
        if available_actions:
            fields[vol.Optional("legacy_actions", default=[a for a in current.get("legacy_actions", []) if a in available_actions])] = selector.SelectSelector({"options": available_actions, "multiple": True})
        return self.async_show_form(step_id="notifications", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_review(self, user_input=None):
        if user_input is not None:
            if not user_input.get("understood"):
                return self.async_show_form(step_id="review", data_schema=vol.Schema({vol.Required("understood", default=False): selector.BooleanSelector()}), errors={"base": "confirmation_required"}, description_placeholders=self._summary())
            self._settings["mode"] = "observe"
            return self.async_create_entry(title=self._settings["name"] if not self._editing else "", data=self._settings)
        return self.async_show_form(step_id="review", data_schema=vol.Schema({vol.Required("understood", default=False): selector.BooleanSelector()}), description_placeholders=self._summary())

    def _summary(self):
        missing = [key.removesuffix("_entity").replace("_", " ") for key in ("rain_entity", "person_entity", "safety_entity") if not self._settings.get(key)]
        return {"areas": ", ".join(z["name"] for z in self._settings.get("zones", [])), "window": f"{self._settings.get('start_time', '09:00')}–{self._settings.get('end_time', '19:00')}", "weather": "Additional weather protection selected" if self._settings.get("weather_entity") else "No external weather source selected; rain protection is still required for control", "readiness": "Missing before control: " + ", ".join(missing) if missing else "Bindings selected; runtime readiness checks still apply"}

    async def _after_step(self, next_step):
        if self._editing:
            return await self.async_step_init()
        return await getattr(self, "async_step_" + next_step)()


class MowerConfigFlow(WizardSteps, config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one coordinator per mower, with any number of logical areas."""
    VERSION = 1

    def __init__(self):
        self._settings = {"zones": [], "mode": "observe", "allow_handoff": True, "auto_recovery": True, "protect_unowned_work": False, "adaptive_recharge": True}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MowerOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            entity_id = user_input.get("mower_entity", "")
            name = user_input.get("name", "")
            name = name.strip() if isinstance(name, str) else ""
            if not isinstance(entity_id, str) or not entity_id.startswith("lawn_mower.") or self.hass.states.get(entity_id) is None:
                errors["mower_entity"] = "missing_entity"
            if not name or len(name) > 80:
                errors["name"] = "invalid_name"
            if not errors:
                registered = er.async_get(self.hass).async_get(entity_id)
                await self.async_set_unique_id(registered.id if registered else entity_id)
                self._abort_if_unique_id_configured()
                self._settings.update({"name": name, "mower_entity": entity_id})
                if registered and registered.device_id:
                    self._settings["device_id"] = registered.device_id
                    self._suggest_bindings(registered.device_id)
                return await self.async_step_bindings()
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Required("name", default="Mammotion mower coordinator"): selector.TextSelector(), vol.Required("mower_entity"): _entity("lawn_mower")}), errors=errors)

    def _suggest_bindings(self, device_id):
        entries = er.async_entries_for_device(er.async_get(self.hass), device_id)
        hints = {"battery_entity": ("battery",), "progress_entity": ("progress",), "charging_entity": ("charging",), "activity_entity": ("activity",), "error_entity": ("self_check",), "rain_entity": ("rain",), "tracker_entity": (), "blade_time_entity": ("blade",), "mileage_entity": ("maintenance_distance",), "rtk_entity": ("positioning_mode",)}
        metadata = {"error_entity": "self_check", "mileage_entity": "maintenance_distance", "rtk_entity": "positioning_mode"}
        for key, words in hints.items():
            candidates = [item.entity_id for item in entries if item.domain == BINDINGS[key] and self.hass.states.get(item.entity_id) and (item.translation_key == metadata[key] if key in metadata else (not words or any(word in item.entity_id for word in words)))]
            if len(candidates) == 1:
                self._settings[key] = candidates[0]


class MowerOptionsFlow(WizardSteps, config_entries.OptionsFlow):
    """Edit configuration through forms; updates disarm control on reload."""
    _editing = True

    def __init__(self):
        self._settings = {}

    async def async_step_init(self, user_input=None):
        if not self._settings:
            self._settings = deepcopy({**self.config_entry.data, **self.config_entry.options})
        return self.async_show_menu(step_id="init", menu_options=["bindings", "zones", "rules", "calendar", "safety_weather", "charging", "notifications", "review"])

    async def async_step_zones(self, user_input=None):
        choices = [{"value": "add", "label": "Add an area"}] + [{"value": z["id"], "label": z["name"]} for z in self._settings["zones"]]
        errors = {}
        if user_input is not None:
            chosen = user_input.get("zone")
            if chosen == "add":
                self._zone_id = None
                return await self.async_step_zone()
            if chosen in {z["id"] for z in self._settings["zones"]}:
                self._zone_id = chosen
                return await self.async_step_zone_action()
            errors["base"] = "invalid_zone"
        return self.async_show_form(step_id="zones", data_schema=vol.Schema({vol.Required("zone"): selector.SelectSelector({"options": choices})}), errors=errors)

    async def async_step_zone_action(self, user_input=None):
        return self.async_show_menu(step_id="zone_action", menu_options=["zone", "delete_zone", "init"])

    async def async_step_delete_zone(self, user_input=None):
        errors = {}
        if user_input is not None:
            if len(self._settings["zones"]) <= 1:
                errors["base"] = "last_zone"
            elif user_input.get("confirm_delete"):
                self._settings["zones"] = [z for z in self._settings["zones"] if z["id"] != self._zone_id]
                self._zone_id = None
                return await self.async_step_init()
            else:
                return await self.async_step_init()
        return self.async_show_form(step_id="delete_zone", data_schema=vol.Schema({vol.Required("confirm_delete", default=False): selector.BooleanSelector()}), errors=errors)
