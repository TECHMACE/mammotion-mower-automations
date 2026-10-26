from homeassistant.components.notify import NotifyEntity
from .entity import SimEntity
from . import capture
async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([Capture(hass,"notification_capture")])
class Capture(SimEntity,NotifyEntity):
    async def async_send_message(self,message,title=None):
        await capture(self.hass,message,title)
