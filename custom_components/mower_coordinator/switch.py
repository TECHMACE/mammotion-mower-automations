"""Explicit startup interlocks; switches are never restored armed."""
from homeassistant.components.switch import SwitchEntity
from .entity import MowerEntity

async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([MowerSwitch(entry.runtime_data,"armed","Automatic control"), MowerSwitch(entry.runtime_data,"hold","Hold new work")])

class MowerSwitch(MowerEntity, SwitchEntity):
    def __init__(self,r,key,name): super().__init__(r,key,name); self.key=key
    @property
    def is_on(self): return getattr(self.runtime,self.key)
    async def async_turn_on(self,**kwargs): await self.runtime.async_set_control(self.key,True)
    async def async_turn_off(self,**kwargs): await self.runtime.async_set_control(self.key,False)
