"""Readiness, notification test and explicit commissioning controls."""
from homeassistant.components.button import ButtonEntity
from .entity import MowerEntity

async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([MowerButton(entry.runtime_data,key,name) for key,name in (
        ("preflight","Check readiness"),("notification_test","Send test notification"),
        ("notification_confirm","Confirm test notification received"),
        ("commission","Confirm setup and competing schedules off"),
        ("reset_recovery","Reset recovery after inspection"),
    )])

class MowerButton(MowerEntity,ButtonEntity):
    def __init__(self,r,key,name): super().__init__(r,key,name); self.key=key
    async def async_press(self): await self.runtime.async_button(self.key)
