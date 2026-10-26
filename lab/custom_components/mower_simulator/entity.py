from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from . import DOMAIN

class SimEntity:
    _attr_should_poll = False
    _attr_force_update = True
    _attr_has_entity_name = False
    def __init__(self,hass,key):
        self.hass = hass
        self.key = key
        domain = ('weather' if key == 'weather' else 'lawn_mower' if key == 'mower' else 'switch' if key.startswith('area_') else 'notify' if key == 'notification_capture' else 'binary_sensor' if key in ('charging','rain','safety_clear','operator_home') else 'sensor')
        self.entity_id = f"{domain}.lab_{key}"
        self._attr_unique_id = f"lab_{key}"
        self._attr_name = f"Lab {key.replace('_',' ')}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN,"lab-mower")})
    @property
    def sim(self): return self.hass.data[DOMAIN]
    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass,DOMAIN,self.async_write_ha_state))
