from homeassistant.components.lawn_mower import LawnMowerEntity, LawnMowerEntityFeature
from .entity import SimEntity
from . import command
async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([Mower(hass,"mower")])
class Mower(SimEntity,LawnMowerEntity):
    _attr_supported_features = LawnMowerEntityFeature.START_MOWING | LawnMowerEntityFeature.PAUSE | LawnMowerEntityFeature.DOCK | LawnMowerEntityFeature.STOP
    @property
    def activity(self): return self.sim["state"]["mower"]
    @property
    def extra_state_attributes(self):
        return {"simulated":True}
    async def async_start_mowing(self): await command(self.hass,"start_mowing",{})
    async def async_dock(self): await command(self.hass,"dock",{})
    async def async_pause(self): await command(self.hass,"pause",{})
    async def async_stop(self): await command(self.hass,"stop",{})
