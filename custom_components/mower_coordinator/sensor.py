"""Plain-language operational and commissioning state."""
from homeassistant.components.sensor import SensorEntity
from .entity import MowerEntity

async def async_setup_entry(hass, entry, async_add_entities):
    r = entry.runtime_data
    async_add_entities([MowerSensor(r, key, name) for key,name in (
        ("status","Status"),("explanation","Explanation"),("checkpoint","Saved progress"),
        ("readiness","Readiness"),("commissioning","Commissioning"),("queue","Remaining areas"),
        ("retries","Recovery attempts"),("notifications","Notification delivery"),
    )])

class MowerSensor(MowerEntity, SensorEntity):
    def __init__(self,r,key,name):
        super().__init__(r,key,name)
        self.key=key
        if key=="checkpoint": self._attr_native_unit_of_measurement="%"
    @property
    def native_value(self):
        return self.runtime.status_value(self.key)
    @property
    def extra_state_attributes(self):
        if self.key=="retries": return {"resume_attempts":self.runtime.state.retries,"return_attempts":self.runtime.state.return_retries,"limit_per_kind":self.runtime.config.get("max_retries",2)}
        if self.key=="readiness": return {"checks":self.runtime.preflight()}
        if self.key=="commissioning": return {"steps":dict(self.runtime.evidence), "physical_validation":"not established by software"}
        if self.key=="explanation": return {"updated_at":self.runtime.updated_at, "mode":"control" if self.runtime.armed else "observe", "next_step":self.runtime.next_step}
        return None
