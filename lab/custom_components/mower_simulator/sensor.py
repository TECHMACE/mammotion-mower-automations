from homeassistant.components.sensor import SensorEntity
from .entity import SimEntity
async def async_setup_entry(hass,entry,async_add_entities):
    async_add_entities([SimSensor(hass,key) for key in ["battery","progress","activity","error","blade_time","mileage","commands","notifications","map_sync_status"]])
class SimSensor(SimEntity,SensorEntity):
    @property
    def translation_key(self):
        return "map_sync_status" if self.key == "map_sync_status" else None
    @property
    def native_value(self):
        if self.key in ("commands","notifications"): return len(self.sim[self.key])
        return self.sim["state"][self.key]
    @property
    def native_unit_of_measurement(self):
        return {"battery":"%","progress":"%","blade_time":"s","mileage":"m"}.get(self.key)
    @property
    def extra_state_attributes(self):
        if self.key in ("commands","notifications"): return {"records":self.sim[self.key]}
        return {"simulated":True,"observed_at":self.sim["updated"]}
