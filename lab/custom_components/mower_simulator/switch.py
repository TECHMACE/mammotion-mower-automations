from homeassistant.components.switch import SwitchEntity
from .entity import SimEntity
async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([Area(hass,f"area_{n}",n) for n in range(1,4)])
class Area(SimEntity,SwitchEntity):
    def __init__(self,hass,key,index):
        super().__init__(hass,key)
        self.index=index
        self._attr_is_on = False
    @property
    def extra_state_attributes(self):
        return {"hash":10000+self.index,"simulated":True,"map_revision":self.sim["state"]["map_revision"]}
    async def async_turn_on(self,**kwargs): self._attr_is_on=True; self.async_write_ha_state()
    async def async_turn_off(self,**kwargs): self._attr_is_on=False; self.async_write_ha_state()
