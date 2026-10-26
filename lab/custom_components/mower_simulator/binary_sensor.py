from homeassistant.components.binary_sensor import BinarySensorEntity
from .entity import SimEntity
async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([SimBinary(hass,key) for key in ["charging","rain","safety_clear","operator_home"]])
class SimBinary(SimEntity,BinarySensorEntity):
    @property
    def is_on(self): return bool(self.sim["state"][self.key])
