# Set up Mammotion Mower Coordinator — 0.2.0-alpha.2

Let the mower mow. First, tell it what a good day's work looks like.

This Home Assistant integration coordinates an already-connected **Mammotion mower**. You choose the areas, directions, calendar, battery rules and notifications through native setup and options screens. The Mammotion integration still connects to the mower and supplies its telemetry.

This is a development alpha. The [validation notes](INTEGRATION_VALIDATION.md) and [lab behavior matrix](../lab/BEHAVIOR_MATRIX.md) separate implemented features from tested scenarios. Neither proves physical safety or coverage on your lawn.

## Install

Use Home Assistant 2026.10.4 or newer and a working Mammotion integration. Map and check your property in the Mammotion app first. Disable competing native schedules and older mower controllers before arming this one; do not run the YAML reference alongside it.

**New to HACS or Home Assistant integrations? Start with [the click-by-click installation guide](START_HERE.md).** It covers installing HACS, connecting Mammotion-HA, downloading this coordinator, notifications and the first setup test.

Add [this repository](https://github.com/TECHMACE/mammotion-mower-automations) as a HACS custom repository of type **Integration**. Choose `v0.2.0-alpha.2`, enabling beta versions if needed, then restart HA. The older `v0.1.0-alpha.1` is a YAML reference, not this integration. Manual component ZIP installation is covered in the start-here guide.

Open **Settings → Devices & Services → Add Integration → Mammotion Mower Coordinator**. The wizard reads state; it does not send movement commands or notifications. Setup, restart and options reload leave **Automatic control off** and **Hold new work on**.

## Choose the mower and sensors

Select the mower, then check the suggested bindings. Similar names do not guarantee the right sensor.

| Binding | What it is for |
| --- | --- |
| Battery, progress, charging, activity | Required in the wizard; use distinct entities belonging to the selected mower's device. Percentages must be valid and reports fresh. |
| Current Self check | Current health, normally `normal` when clear. Historical Last error sensors are not substitutes. |
| Blade usage time | Required for control. Increasing usage correlated with progress establishes reported cutting evidence. A `MODE_WORKING` label alone does not. |
| Native rain sensor | Required for control. Wet, unavailable or an active dry-out hold blocks mowing. |
| Operator presence | Required for control; the operator must be home for starts/resumes. |
| Property safety permission | A binary sensor or Toggle helper: `on` means the property is safe. Off/unavailable prevents movement commands, including Dock. |
| Tracker, mileage, RTK | Required when automatic recovery is enabled. Reports must be fresh, mileage units recognized and RTK fixed. These help distinguish a stationary obstruction from delayed motion reports. |
| Recent fault code and time | Optional paired fault evidence. Use the corresponding entities from the mower, not unrelated historical sensors. |
| Weather | Optional external weather source. Advanced options can add multiple sources; configured sources must satisfy freshness and unit checks. |

If you need a manual property permission, create a Toggle helper under **Settings → Devices & Services → Helpers**. Leave it off until you inspect the lawn, gates, people, pets and obstacles. This permission does not detect obstructions or replace native mower protections.

The adapter also requires a fresh, synced native **Map sync status** and a supported cached map structure. It fingerprints geometry, including paths and no-go features, without storing the raw map. An unchanged area ID is not enough when geometry changes. Missing or incompatible map data blocks control.

The adapter was developed against **Mammotion-HA 0.6.19-beta4 / PyMammotion 0.10.11**. Internal cache structures and service behavior can change between versions and models. A failed compatibility check needs investigation, not a bypass.

## Give each area its own rules

Create one or more logical areas from the mower's native area switches. Each native switch must belong to this mower, expose a positive numeric hash, and appear in only one logical area.

- Name the area and choose its direction sequence: 1–12 whole-number angles from 0° to 180°. For example, `0,90` alternates directions after verified completion.
- Set lane spacing, perimeter passes, path mode, mowing order and obstacle passes. Optional blade-height and speed overrides must suit your model.
- Set the normal cut interval and minimum departure battery. Monthly interval overrides allow seasonal cadence without a fixed climate assumption.
- Use an optional not-before date to leave an area alone until it is ready.
- Assign a group if areas belong together. A group's due anchor can bring its other eligible members into the plan; completed work is not repeated just to fill the group.
- Optionally set a stationary-return limit for that area. Zero disables this area-specific limit.

For monthly interval overrides, enter `{"1": 14, "7": 3}` to cut every 14 days in January and every 3 days in July. Unlisted months use the normal interval.

Area UUIDs preserve history when you rename an area. Changes to its native members, map or cutting profile invalidate the identity of saved work; the coordinator preserves and quarantines the checkpoint rather than guessing where to restart. An interrupted cut keeps its frozen profile and angle until completion.

## Calendar, recovery and charging

The main rules screen sets a same-day operating window, battery reserve and fallback resume target. The default window is 09:00–19:00. Overnight windows are not supported.

**Automatic recovery and charger-free handoff default on in alpha.2.** They are policy choices, not permission to move: control remains disarmed until commissioning. You can turn either off in options. Recovery requires its additional bindings and actions to pass readiness.

| Policy | What happens |
| --- | --- |
| Automatic recovery | Observe an eligible owned interruption, allow delayed telemetry, recheck safety and ownership, then use bounded resume/return recovery. Movement cancels a stationary candidate. A stalled native return uses pause, fresh settled telemetry, then Dock; a repeated Dock during RETURNING can otherwise cancel the native return. Unknown or critical faults need inspection. |
| Recovery timing | Defaults: 120-second observation, 30-second grace, 120-second cooldown and acknowledgement timeout. The default retry limit is 2, configurable from 1 to 3. |
| Direct area handoff | An eligible next area can start without a charger visit after completion, task cancellation/ready confirmation and fresh guards. The default handoff battery floor is 60%; a failed gate can require return instead. |
| Return and contact | Dock request, arrival, charging flag and sustained charging are separate observations. Defaults require 60 seconds stable charging, 120 seconds contact confirmation and a 2-point battery rise, or full charge. |
| Contact trouble | A suitable missing-contact episode may receive one bounded redock attempt. Insufficient battery gain or exhausted recovery produces attention rather than endless retries. |
| Adaptive recharge | On by default. Use observed battery consumption and remaining work plus a buffer to estimate a resume target, within configured bounds. Without a usable estimate, use the fallback target. Default buffer 10 points; bounds 60–95%. |
| External work protection | `protect_unowned_work` defaults off. When explicitly enabled and control is armed, unsafe weather/presence/window or low battery can trigger Dock for an externally started job. It never adopts, resumes or restarts that job's checkpoint. Inspection and a disarmed docked reset are required before coordinator planning continues. |

Advanced calendar options select weekdays, active months, excluded dates, eligible groups and rest days between completed plans. These gates also apply when considering continuation; they are not just a morning alarm. Existing unfinished work remains accounted for.

## Rain, weather and forecasts

Keep Mammotion's native rain and safety protections enabled. The coordinator does not switch them off.

External weather is optional; every configured source must be usable. Wind limits use meters per second in settings, with supported source-unit conversion. Temperature uses a configurable Celsius floor. Defaults are 10 m/s and 5°C. The dry-out delay defaults to 30 minutes after observed rain clears.

Forecast protection is optional and defaults off. When enabled, configure weather sources that support hourly forecasts, a horizon and precipitation-probability threshold. Defaults are 6 hours and 50%. The provider must supply continuous hourly coverage across the selected horizon and valid rain probabilities. Missing, partial or stale forecast data holds work rather than being treated as a clear forecast.

Light-rain tolerance is optional and defaults off. It applies to external weather reports only after a dry launch has been established for the owned job. It does not waive native rain, severe-weather, physical-safety or other movement gates.

## Notifications and the device page

Choose supported notification entities and/or legacy notify actions, event types, quiet hours and whether urgent alerts may override quiet hours. A persistent Home Assistant notification is the fallback when no push destination is selected.

The device page shows **Status**, **Explanation**, **Readiness**, **Saved progress**, **Remaining areas**, **Recovery attempts**, **Commissioning** and **Notification delivery**. Recovery attempts shows resume attempts, with separate return-attempt and limit attributes in the entity details. Readiness reports individual checks; it is a software check, not a certificate that the lawn is clear.

1. Leave control off and press **Check readiness**. Resolve failed checks.
2. Press **Send test notification**. Explicit tests bypass quiet hours/event filters.
3. After seeing the message arrive, press **Confirm test notification received**. A successful service call alone does not prove phone delivery.
4. Confirm setup and competing schedules are off. Only then plan a supervised run.

**Automatic control off blocks every integration command, including protective Dock.** **Hold new work** is different: while control remains armed it blocks new/resumed mowing, while an owned job can still receive a protective return. Physical safety permission can veto even Dock. These controls are not a physical emergency stop.

Restart and configuration edits disarm control. Saved ownership, checkpoints and pending intents persist, but the integration does not blindly replay a command. Inspect the current mower state and readiness before deliberately rearming. Keep native mower protections working independently of Home Assistant.

## First ordinary mowing run

Start with a small area you can watch. Verify the map and model's supported cutting values, turn on property safety permission only when the lawn is clear, confirm setup, release Hold new work and arm Automatic control. Watch launch, cutting evidence, completion, return and sustained charging separately.

Do not create a trap or dirty a camera to test recovery. Observe natural interruptions, record manual commands and compare timestamps. Use **Reset recovery after inspection** only after resolving the cause, disarming and docking. A simulator result does not prove traction, obstacle detection or charging-contact quality.

For updates, back up Home Assistant, inspect release notes and repeat readiness and notification checks. For rollback, safely stop/park the mower, disarm this integration and restore the prior version or backup. Enable another controller only after checking ownership and unfinished work.

## Share improvements, keep private data private

Fork it, change it and help the next person. The [MIT license](../LICENSE) permits modification and redistribution; keep the license and copyright notice. Reports should include versions, expected behavior and a small synthetic reproduction. Do not publish raw maps, coordinates, storage, accounts, device identifiers or unreviewed traces.
