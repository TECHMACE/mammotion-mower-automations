"""Portable evidence and environmental policy; no HA services or device commands."""
from __future__ import annotations
from datetime import datetime
import math

CLEAR_HEALTH = {'normal', '0', '0.0', 'none', 'None', 'clear'}
CRITICAL_CODES = {'1004', '1030', '1008', '2800', '2801'}
RECOVERABLE_CODES = {'1201', '11133', '1214'}
SEVERE_WEATHER = {'pouring', 'lightning', 'lightning-rainy', 'snowy', 'snowy-rainy', 'hail', 'exceptional'}


def finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def distance_m(first, second):
    """Great-circle distance; inputs are ephemeral and never persisted."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*first, *second))
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(a)))


def mileage_m(value, unit):
    value = finite(value)
    factor = {'m': 1, 'km': 1000, 'mi': 1609.344, 'ft': .3048}.get(unit)
    return value * factor if value is not None and value >= 0 and factor else None


def event_timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.timestamp() if result.tzinfo is not None else 0
    except (ValueError, TypeError):
        return 0


def weather_condition(condition, attrs, wind_limit, minimum_temperature, tolerate_light_rain=False):
    """None means missing/invalid units or evidence, never an implicit safe default."""
    if condition in {None, '', 'unknown', 'unavailable'}:
        return None
    if condition in SEVERE_WEATHER or (condition == 'rainy' and not tolerate_light_rain):
        return False
    temp, wind = finite(attrs.get('temperature')), finite(attrs.get('wind_speed'))
    if temp is None or wind is None or wind < 0:
        return None
    if attrs.get('temperature_unit') == '°F':
        temp = (temp-32)*5/9
    elif attrs.get('temperature_unit') != '°C':
        return None
    factor = {'m/s': 1, 'km/h': 1/3.6, 'mph': .44704, 'kn': .514444}.get(attrs.get('wind_speed_unit'))
    gust = finite(attrs.get('wind_gust_speed', wind))
    if factor is None or gust is None or gust < 0:
        return None
    return temp > minimum_temperature and max(wind, gust)*factor <= wind_limit


def forecast_safe(forecast, attrs, now, horizon_hours, probability_threshold, wind_limit, minimum_temperature):
    if not isinstance(forecast, list) or not forecast:
        return None
    # An hourly forecast describes the following hour. Require enough samples
    # across the requested horizon; one clear hour cannot certify six hours.
    # One minute tolerates normal provider rounding without accepting a gap.
    tolerance = 60
    if not isinstance(horizon_hours,(int,float)) or isinstance(horizon_hours,bool) or not math.isfinite(horizon_hours) or horizon_hours <= 0:
        return None
    horizon_end = now+horizon_hours*3600
    stamped=[]
    for item in forecast:
        if not isinstance(item,dict):return None
        stamp=event_timestamp(item.get('datetime'))
        if not stamp:return None
        if now <= stamp <= horizon_end+tolerance:stamped.append((stamp,item))
    stamped.sort(key=lambda pair:pair[0])
    if (not stamped or stamped[0][0]>now+3600+tolerance
            or stamped[-1][0]<horizon_end-3600-tolerance
            or any(right[0]-left[0]>3600+tolerance for left,right in zip(stamped,stamped[1:]))):
        return None
    upcoming=[item for _,item in stamped]
    for item in upcoming:
        data = {**attrs, **item}
        # Forecast-specific measures must be present; current conditions cannot
        # masquerade as forecast observations.
        if not {'condition', 'temperature', 'wind_speed'} <= item.keys():
            return None
        result = weather_condition(item['condition'], data, wind_limit, minimum_temperature)
        if result is not True:
            return result
        raw_probability=item.get('precipitation_probability')
        probability = finite(raw_probability)
        if isinstance(raw_probability,bool) or probability is None or not 0<=probability<=100:
            return None
        if probability >= probability_threshold:
            return False
    return True


def recharge_target(config, checkpoint, rate):
    fallback = int(config.get('resume_battery', 85))
    if not config.get('adaptive_recharge', True) or rate is None or not 0 < rate <= 2:
        return fallback
    estimate = math.ceil(config.get('reserve_battery', 25) + (100-checkpoint)*rate*1.10 + config.get('recharge_buffer', 10))
    return min(config.get('recharge_max_target', 95), max(config.get('recharge_min_target', 60), config.get('reserve_battery', 25)+1, estimate))
