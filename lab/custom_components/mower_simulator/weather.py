"""Deterministic current weather and hourly forecast; no network provider."""
from datetime import datetime, timedelta, timezone
from homeassistant.components.weather import WeatherEntity, WeatherEntityFeature
from .entity import SimEntity

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([Weather(hass, 'weather')])

class Weather(SimEntity, WeatherEntity):
    _attr_supported_features = WeatherEntityFeature.FORECAST_HOURLY
    _attr_native_temperature_unit = '°C'
    _attr_native_wind_speed_unit = 'm/s'
    _attr_native_precipitation_unit = 'mm'

    @property
    def condition(self):
        return self.sim['state']['weather']

    @property
    def native_temperature(self):
        return self.sim['state']['temperature']

    @property
    def native_wind_speed(self):
        return self.sim['state']['wind_speed']

    @property
    def native_wind_gust_speed(self):
        return self.sim['state']['wind_gust']

    async def async_forecast_hourly(self):
        rain = self.sim['state']['forecast_rain']
        return [{
            'datetime': (datetime.now(timezone.utc) + timedelta(hours=i)).isoformat(),
            'condition': 'pouring' if rain else 'sunny',
            'native_temperature': 20,
            'native_wind_speed': 2,
            'native_precipitation': 5 if rain else 0,
            'precipitation_probability': 90 if rain else 0,
        } for i in range(49)]
