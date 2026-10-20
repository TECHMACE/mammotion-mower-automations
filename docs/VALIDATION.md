# Validation and evidence

The reviewed public package passed **51 synthetic tests** and an **isolated Home Assistant Core 2026.10.2 configuration check**. The check compiled fixture bindings into a temporary configuration and ran Home Assistant's configuration validator; it did not start Home Assistant or contact a live installation or mower. The check also rejects validation errors that can appear in output despite a zero CLI exit status.

These results apply to the reviewed public package, not arbitrary local adaptations. Your generated package still needs validation on your installation. Earlier development test counts are not treated as tests rerun against this release.

## Reproduce developer checks

Run from the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```

Use a separate Python 3.14 environment for the pinned Home Assistant check:

```sh
python3.14 -m venv .venv-ha
.venv-ha/bin/pip install -r requirements-dev.txt homeassistant==2026.10.2 colorlog==6.10.1
.venv-ha/bin/python tools/check_ha_config.py
```

Install Python 3.14 first if it is unavailable. Dependency installation needs internet access; the validation itself uses synthetic local configuration. Do not point this check at a live Home Assistant configuration. The compiler's selector normalization and removal of an unused legacy start script are part of the public adaptation; the component inventory describes what ships.

Static tests can show that code preserves a guard or produces valid package structure. They cannot establish traction, clean sensors, map accuracy, charging contact quality or physical mowing coverage. No cross-installation physical validation is claimed.

## Record before commissioning

Record the package commit, Home Assistant version, Mammotion integration version, mower model/firmware, configured timezone, units, successful configuration-check result and local adaptation changes. Keep identifiers, maps and raw traces private. For each observation capture expected behavior, actual state transitions, timestamps and any human command.

## Checklist

| Check | Evidence required | What it does not prove |
| --- | --- | --- |
| Disarmed installation | Motion-enable gate off, manual hold on, not-before gates present; no start/resume dispatch. Dock-only protective automations remain enabled. | Correct behavior after arming motion. |
| External dependencies | Real entities, matching units/enums, valid device/hash mapping and fresh telemetry. | Correct physical map boundaries. |
| Normal launch | One dispatch, status refresh, movement/blade evidence, correct owned area. | All delayed-telemetry failure paths. |
| Delayed acknowledgement | Natural event trace shows progress accepted without duplicate start, with remaining queue preserved. | Every integration outage will recover. |
| Restart protection | Motion stays disarmed after restart; enabled dock-only protections remain available; no fresh start or Resume bypasses the interlocks. | Home Assistant stays online during a power/network failure. |
| Checkpoint persistence | Saved progress and map identity survive the intended restart/reload policy. | A checkpoint guarantees complete coverage. |
| Completion and queue | Cutting evidence marks the correct area complete and advances pending work once. | No missed grass strips. |
| Low-battery return | Automatic request precedes any manual command; arrival and sustained charge observed separately. | A manually assisted arrival was autonomous. |
| Recharge/resume | Correct target reached; same eligible owned work resumes without restarting completed areas. | Reuse after a map/profile change is safe. |
| Consecutive-area handoff | Natural eligible completion proceeds to the next area without a charger visit; battery/safety gates remain true. | Handoff is available for every area/condition. |
| Trapped pause recovery | A natural delayed-position event uses the extra 30-second grace, then rechecks freshness/movement/safety before Resume. | The fix was physically proven by a recovery before its installation. |
| Resume budget | Budget persists across restart; at most three recovery attempts shared by smart-unstick, working-pause and dock/cancel recovery, no blade/progress reset, manual reset only after inspection. | An obstruction clears without help. |
| Return/channel recovery | Trace shows bounded retries, preserved ownership and checkpoint, then recovery or intervention notification. | A physical obstruction can always clear itself. |
| No-mow guard | No scheduled start, resume or recovery launch during the chosen blocked period. | All future schedule edits preserve the guard. |
| Rain/presence/time protection | Template/static checks plus naturally occurring state changes show refusal/defer behavior. | Safety sensors can be bypassed for testing. |
| Docking reliability | Multiple ordinary returns reach stable charging and battery rises over time. | Contact/camera hardware can never fail. |

The 30-second telemetry grace, charger-free handoff, delayed normal launch, and recovery without manual assistance remain specific natural-operation checks. Mark each as passed only when the relevant event actually occurred on your installation. If no event occurs, record “not observed.”

## Investigating a failed check

Secure the mower first if needed. Record the time and intervention, then inspect the owning script, relevant recovery automation, job token, checkpoint, map identity, activity/error timestamps, battery and charging history. Distinguish a command request from acknowledgement, actual movement, arrival and sustained charging.

Do not restart a completed area to collect evidence or repeatedly issue Resume/Dock while another recovery path owns the job. Keep the package disabled if dependencies or safety conditions are unclear. Adapt one cause at a time, rerun the relevant static checks and Home Assistant configuration validation, then observe the next normal opportunity.

## Public reports

Provide a small synthetic reproduction and relevant state transitions. Remove entity IDs tied to people/devices, coordinates, map hashes, notification destinations, URLs, tokens and household history. Screenshots and trace downloads can include more than the visible error. Inspect the complete attachment before publishing. Never upload your generated package, settings file or Home Assistant backup to a public issue.
