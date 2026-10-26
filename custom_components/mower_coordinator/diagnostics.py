"""Allowlisted diagnostics: no names, bindings, maps, coordinates or raw traces."""
async def async_get_config_entry_diagnostics(hass,entry):
    r=entry.runtime_data
    return {"schema_version":1,"integration_version":"0.2.0-alpha.1", "mode":"control" if r.armed else "observe", "held":r.hold,"zone_count":len(r.config.get("zones",[])),"phase":r.state.phase,"checkpoint":r.state.checkpoint,"recovery_attempts":r.state.retries,"commissioning":dict(r.evidence),"checks":r.preflight(),"notifications":r.notifier.diagnostics()}
