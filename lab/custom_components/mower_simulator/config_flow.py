from homeassistant import config_entries

class SimulatorFlow(config_entries.ConfigFlow, domain="mower_simulator"):
    VERSION = 1
    async def async_step_import(self, user_input=None):
        await self.async_set_unique_id("isolated-lab-mower")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Lab mower (simulation only)", data={})
    async def async_step_user(self, user_input=None):
        return await self.async_step_import(user_input)
