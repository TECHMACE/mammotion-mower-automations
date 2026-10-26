# Mower Coordinator Custom Integration (`0.2.0-alpha.1`)

> **Alpha Status — Lab-Validated Only (No Production Testing):**
> `custom_components/mower_coordinator` is an alpha Home Assistant integration (`0.2.0-alpha.1`). It has been exercised only against unit tests and the isolated, network-free simulator in `lab/`. **Testing used a running isolated Home Assistant Container with a fake mower; no production Home Assistant or physical mower was accessed.** Software readiness checks and simulator runs do not establish physical mowing or docking safety. Keep the legacy YAML package instructions in [`docs/SETUP.md`](SETUP.md) and [`README.md`](../README.md) as the reference for the existing YAML workflow.

## Start here

1. Install the preview component and restart your test Home Assistant.
2. Open **Settings → Devices & Services → Add Integration → Mower Coordinator**.
3. Select your mower, connect its sensors, add your areas, and choose operating rules and notifications.
4. Leave **Automatic control off**. Open the coordinator device page and press **Check readiness**.
5. Send a test notification, check your phone or HA notification panel, and confirm receipt.
6. Read **Explanation** and resolve each failed readiness check. Only then plan a supervised first run.

The wizard does not start a mower. The separate commissioning controls make the transition from setup to control explicit. Your existing Mammotion integration remains responsible for connecting to the mower.

---

## 1. What This Integration Does

`mower_coordinator` replaces fixed-zone YAML helpers with a local Home Assistant integration that coordinates a single already-configured Mammotion mower entity (`lawn_mower.*`):

- **Guided UI Setup & Options Flow:** Configures sensor bindings, any number of user-defined mowing areas, per-area cutting profiles and direction angle sequences, operating hours, battery thresholds, and notification destinations without editing YAML or seeding helper entities.
- **Observation-First Startup:** Setup reads Home Assistant state only and never moves the mower or sends notifications. New installations, configuration edits, and Home Assistant restarts always start **disarmed** (`Automatic control` off, `Hold new work` on).
- **Durable Progress & Ownership:** Persists active zone ownership, progress checkpoints (`0–99%`), angle rotation indices, and completion dates in Home Assistant `.storage` (`mower_coordinator.<entry_id>`) before dispatching commands, and never adopts unowned mower jobs started outside the coordinator.
- **Plain-Language Explanations:** Exposes human-readable `Status`, `Explanation`, `Readiness`, and `Commissioning` sensors so you can see why work is waiting or held before enabling control.

### Alpha Scope Limitations
- **Single Daytime Window:** Operating hours must start and end within the same local calendar day (`start_time < end_time`).
- **No Automatic Obstruction Recovery:** `auto_recovery` is disabled (`False`) in this alpha. Paused or faulted jobs wait for operator inspection.
- **No Charger-Free Area Handoff:** `allow_handoff` is disabled (`False`) by default; each new area starts from confirmed charging at the dock.

---

## 2. Beginner Installation

### Prerequisite
Your mower must already be mapped in the Mammotion mobile app and integrated into Home Assistant through the `mammotion` integration so that its `lawn_mower.*` entity, telemetry sensors, and per-area `switch.*` entities exist in Home Assistant.

### Preview availability

Until this development branch is merged or released, use **manual installation from `feat/mower-coordinator`** or its validated ZIP artifact. The existing YAML release does not contain the new integration. The HACS steps below apply once an integration release is available.

### Option A: Install via HACS (Custom Repository)
1. Open **HACS** in Home Assistant.
2. Open the top-right menu (`⋮`) and select **Custom repositories**.
3. Enter the repository URL `https://github.com/TECHMACE/mammotion-mower-automations` and select category **Integration** (`hacs.json` targets Home Assistant `2026.10.4` or newer).
4. Locate **Mower Coordinator** in HACS, click **Download**, and confirm the download.
5. **Restart Home Assistant** so the custom component is loaded.

### Option B: Manual Copy
1. Copy the `custom_components/mower_coordinator` directory from this repository into your Home Assistant configuration directory at `/config/custom_components/mower_coordinator`.
2. Verify that `/config/custom_components/mower_coordinator/manifest.json` is present.
3. **Restart Home Assistant**.

### Adding the Integration Entry
1. Go to **Settings → Devices & Services**.
2. Click **Add Integration** and search for **Mower Coordinator**.

---

## 3. Guided Setup Wizard Walkthrough

The setup wizard (`config_flow.py`) inspects existing Home Assistant states only—it never calls mower movement services or sends messages during setup.

### Step 1: Welcome & Mower Selection (`user`)
- **Name for this coordinator:** A friendly label (`1–80` characters, default `Mower coordinator`).
- **Mower (`mower_entity`):** Select your `lawn_mower.*` entity.
- If the selected `lawn_mower.*` entity is linked to a Home Assistant device, the wizard inspects that device's entities and pre-fills unambiguous sensor suggestions for Step 2.

### Step 2: Check the Mower Sensors (`bindings`)
Review and select the telemetry and safety entities used by the coordinator:

| Binding Key | Domain | Required in Wizard? | Required Before Arming Control? | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `battery_entity` | `sensor` | **Yes** | **Yes** | Mower battery level (`0–100%`, same device). |
| `progress_entity` | `sensor` | **Yes** | **Yes** | Current task progress (`0–100%`, same device). |
| `charging_entity` | `binary_sensor` | **Yes** | **Yes** | Charger contact state (`on` when charging, same device). |
| `activity_entity` | `sensor` | **Yes** | **Yes** | Raw activity mode (`MODE_WORKING`, `MODE_READY`, `MODE_RETURNING`, `MODE_PAUSE`, same device). |
| `error_entity` | `sensor` | **Yes** | **Yes** | Current **Self check** health sensor (`normal` when healthy, same device). Historical Last error sensors are rejected. |
| `blade_time_entity` | `sensor` | Optional | **Yes** | Blade usage time (same device); increasing values provide reported cutting evidence. |
| `rain_entity` | `binary_sensor` | Optional | **Yes** | Rain sensor (`on` means wet; blocks starts and triggers protective dock return). |
| `person_entity` | `person` | Optional | **Yes** | Operator presence (`home` required to start or continue mowing). |
| `safety_entity` | `binary_sensor` or `input_boolean` | Optional | **Yes** | Property safety permission (`on` means safe; `off` immediately vetoes movement and recovery). |
| `tracker_entity` | `device_tracker` | Optional | Optional | Mower GPS tracker entity (same device). |
| `weather_entity` | `weather` | Optional | Optional (checked if set) | External weather entity; if selected, stale or adverse weather holds mowing. |

- All five required mower telemetry bindings must be distinct entities belonging to the selected mower's device.
- You may omit `rain_entity`, `person_entity`, `safety_entity`, or `blade_time_entity` while completing initial setup for observation, but runtime preflight will block arming automatic control until all required runtime bindings are configured and valid. Device telemetry must be fresh; unchanged presence, rain, and safety permissions may remain valid without frequent state changes.

The **Self check** sensor reports the current blocking condition. Do not select **Last error** or an `error_1_code` sensor: those are historical records and may remain populated after recovery.

The safety permission is a separate property-specific sensor or manual Toggle helper. For a supervised first setup, open **Settings → Devices & Services → Helpers → Create helper → Toggle**, name it **Lawn safety permission**, and leave it off. Select that helper as the safety permission in the wizard. Turn it on only after inspecting the lawn and confirming that people, pets, gates, and obstacles are safe for operation. Turn it off when that permission no longer applies. This is a manual permission, not obstruction detection or a substitute for the mower's safety system. An existing automated binary safety sensor can be selected instead. Off or unavailable blocks integration movement commands, including dock commands; inspect the device before restoring permission.

The native **Map sync status** sensor must be enabled, fresh, and `synced`. The adapter reads the Mammotion integration's cached map in memory and fingerprints areas, paths, obstacles, no-go zones, virtual walls, corridors, and SVG geometry, retaining only the digest. It makes no map-fetch or telemetry-stream request. Missing, incomplete, unknown, or incompatible map structures block starts rather than silently trusting area IDs.

This alpha adapter was developed against **Mammotion-HA 0.6.19-beta4 / PyMammotion 0.10.11**. It validates the cache structure rather than assuming all versions or models are compatible. Older or newer versions with different cache schemas may remain observation-only until the adapter is updated. A failed map readiness check is not permission to bypass it.

### Step 3: Configure Mowing Areas & Direction Profiles (`zone` & `more_areas`)
Unlike the legacy 5-zone YAML package, you can configure **any number of logical mowing areas** (`1` or more):

- **Area name (`name`):** Friendly name for the logical zone (`1–80` characters, e.g., `Front Lawn`).
- **Native mower areas (`area_entities`):** Select one or more `switch.*` entities belonging to your mower. Every selected switch must belong to the mower's device, expose a positive integer `hash` state attribute, and must not overlap with any other configured logical area.
- **Direction angles (`angles`):** Enter `1` to `12` comma-separated whole-number angles between `0` and `180` degrees (for example `0,90` or `0,45,90,135`).
  - The coordinator uses the current angle index for the area and advances to the next angle in the sequence **only after verified 100% completion**.
  - If a job is interrupted (for example, low-battery recharge or rain return) and later resumed, it keeps its frozen cutting profile and original angle until that cut completes.
- **Lane spacing (`spacing_cm`):** Integer from `8` to `35` cm (default `11`).
- **Perimeter passes (`perimeter_laps`):** Integer from `0` to `4` laps (default `2`).
- **Days between completed cuts (`interval_days`):** Integer from `1` to `60` days (default `3`).
- **Minimum departure battery (`minimum_battery`):** Integer from `30` to `100%` (default `80%`, must exceed the return battery reserve).
- **Optional overrides:**
  - `blade_height`: Explicit cutting height override (`20–100` mm).
  - `speed`: Explicit cutting speed override (`0.2–0.8` m/s in the setup wizard; the adapter accepts `0.2–0.8` m/s).
- In the **Add another area? (`more_areas`)** step, check **Add another mowing area** to define additional zones, or leave it unchecked to proceed.

#### Editing Areas Later (`Configure` Options Flow)
- Each area is assigned an immutable internal UUID (`id`). Renaming an area in **Configure → Add, edit, or remove areas** preserves its completion history and angle rotation state.
- If you change an area's native switches (`area_entities`), map revision, or cutting profile while saved work is in progress for that area, the coordinator moves the job to the **`quarantined`** phase (`route_changed`) rather than silently resuming with mismatched route geometry.

### Step 4: Choose Operating Rules (`rules`)
- **Earliest / Latest mowing time (`start_time`, `end_time`):** Local daytime window in Home Assistant's configured timezone (default `09:00:00` to `19:00:00`). When the window ends during an owned mow, the coordinator issues a protective `lawn_mower.dock` command and saves the progress checkpoint.
- **Return battery reserve (`reserve_battery`):** `15–50%` (default `25%`). Reaching or dropping below this level triggers a protective return to the charger.
- **Battery required to resume (`resume_battery`):** `50–100%` (default `85%`, must be strictly greater than `reserve_battery`).
- **Weather freshness & wind limit (`weather_max_age`, `wind_limit_mps`):** Used when an optional `weather_entity` is selected. Weather conditions (`rainy`, `pouring`, `lightning`, `snowy`, `hail`, etc.), temperatures `<= 0°C` (converted from `°F` or `°C`), or wind/gust speeds exceeding `wind_limit_mps` (converted from `m/s`, `km/h`, `mph`, or `kn`) hold starts and trigger protective dock returns.

### Step 5: Choose Notifications (`notifications`)
- **Notification entities (`targets`):** Zero or more `notify.*` entities called via `notify.send_message`.
- **Other notification actions (`legacy_actions`):** Zero or more legacy `notify.<service>` actions (such as `notify.mobile_app_*`), up to `10` total destinations combined.
- **Events to receive (`events`):** Choose which coordinator events send push notifications.
  - Note: Needs-attention (`attention`) alerts **always** create a persistent notification in the Home Assistant UI (`persistent_notification.create`), even if push destinations are empty or quiet hours are active.
- **Quiet hours (`quiet_start`, `quiet_end`) & `urgent_override`:** Suppresses routine push notifications during the local quiet window (default `22:00:00` to `08:00:00`; set equal times to disable).
- **Failure Isolation:** Each destination has a 10-second timeout, 15-minute duplicate suppression, and a 20-message/hour routine rate limit. Notification failures never block or delay mower safety commands.

### Step 6: Review and Start Observing (`review`)
- Displays your configured areas, operating window, weather protection status, and any bindings still needed before control.
- Check **I understand that setup starts observation only and physical operation is not yet verified** to save the entry in **Observation mode**.

---

## 4. Entities, Readiness Checks, and Plain-Language Hold Reasons

Once configured, the integration creates the following entities under your coordinator device:

### Sensors
- **`Status` (`sensor.*_status`):** Shows `observe` while disarmed, or the active coordinator phase (`idle`, `starting`, `mowing`, `returning`, `charging`, `paused`, `attention`, `quarantined`, `final_return`, `complete`, `reconciling`) when armed.
- **`Explanation` (`sensor.*_explanation`):** Plain-English explanation of current state or why mowing is waiting, with attributes `updated_at`, `mode` (`observe` or `control`), and `next_step`. Examples of built-in hold and wait explanations include:
  - `"Observation only. Waiting for the allowed mowing window."`
  - `"Not ready: telemetry fresh, no legacy controller enabled."`
  - `"Manual hold is on."`
  - `"Waiting for the operator to be home."`
  - `"Waiting for dry conditions."` / `"Rain protection is unavailable."`
  - `"Weather protection is unavailable or conditions are unsuitable."`
  - `"Charging to 85% before continuing <Area> from 55%."`
  - `"Another job is active; this coordinator will not take ownership."`
- **`Readiness` (`sensor.*_readiness`):** Reports `ready` or `needs attention`. Its `checks` attribute exposes fourteen read-only preflight gates:
  1. `supported_adapter`: The `lawn_mower` entity belongs to the `mammotion` (or lab `mower_simulator`) platform.
  2. `saved_state_readable`: Persistent `.storage` state loaded without corruption.
  3. `telemetry_fresh`: All 7 device telemetry entities (`mower`, `battery`, `progress`, `charging`, `activity`, `error`, `blade_time`) reported a valid state within the last `120` seconds.
  4. `battery_and_progress_valid`: Battery and progress sensors report finite numbers in `0–100`.
  5. `start_action_available`: Service `mammotion.start_mow` is registered.
  6. `dock_action_available`: Service `lawn_mower.dock` is registered.
  7. `areas_match_mower`: All configured area `switch.*` entities exist, belong to the mower's device, and expose distinct positive integer `hash` attributes.
  8. `map_revision_available`: The mower entity or all configured area `switch.*` entities expose a non-empty `map_revision` attribute.
  9. `settings_valid`: Zone profiles, battery reserves, and operating window pass `core.Settings` validation.
  10. `no_legacy_controller_enabled`: Legacy YAML package master switch (`input_boolean.mower_package_enabled`) and all `automation.mower_*` entities are turned off.
  11. `weather_ready`: Optional `weather_entity` is either unconfigured or reporting fresh, unit-valid temperature and wind data.
  12. `rain_available`: `rain_entity` is configured and reporting `on` or `off`.
  13. `presence_available`: `person_entity` is configured and reporting a valid state.
  14. `physical_safety_ready`: `safety_entity` is configured and currently `on`.
- **`Saved progress` (`sensor.*_saved_progress`):** Monotonic checkpoint percentage (`%`) for the active area.
- **`Commissioning` (`sensor.*_commissioning`):** Reports `setup confirmed` or `setup incomplete`, with `steps` (`setup_confirmed`, `notification_test_requested`, `notification_received`, `launch_observed`, `completion_observed`, `charging_observed`) and `physical_validation: "not established by software"`.
- **`Remaining areas` (`sensor.*_remaining_areas`):** Number of due areas remaining in the queue.
- **`Recovery attempts` (`sensor.*_recovery_attempts`):** Number of recovery attempts used (`retries`).
- **`Notification delivery` (`sensor.*_notification_delivery`):** Current notification subsystem status.

### Buttons & Notification Testing
1. **`Check readiness` (`button.*_check_readiness`):** Runs an immediate read-only evaluation of all preflight checks and updates the `Readiness` and `Explanation` sensors.
2. **`Send test notification` (`button.*_send_test_notification`):** Sends a clearly labeled test message (`Title: "Mower coordinator: TEST notification"`, prefixed with `"TEST ONLY - not a mower event."`) to your configured destinations (or a persistent notification if no push targets are configured), bypassing quiet hours and event filters, and records `notification_test_requested: true`.
3. **`Confirm test notification received` (`button.*_confirm_test_notification_received`):** Press this only after you physically see the test notification arrive on your phone or display. A successful Home Assistant service call only proves Home Assistant accepted the request—it does not prove downstream delivery to your device.
4. **`Confirm setup and competing schedules off` (`button.*_confirm_setup_and_competing_schedules_off`):** Requires all `Readiness` preflight checks to pass (`all(preflight().values())`), and confirmed notification receipt when destinations are configured, then records `setup_confirmed: true`.
5. **`Reset recovery after inspection` (`button.*_reset_recovery_after_inspection`):** Resets exhausted retry counters after you physically inspect the mower, disarm `Automatic control`, and confirm the mower is `docked`.

### Switches & Arming Interlocks

**Disarming Automatic control stops every command from this integration, including protective dock commands.** “Hold new work” is different: while control remains armed, it blocks starts but still allows an owned job to return. Restarting or editing configuration disarms the integration; inspect the mower and rearm deliberately. The mower's own protections remain essential.

- **`Hold new work` (`switch.*_hold_new_work`):** Defaults to **on** (`True`). While on, no new or resumed mow starts will be dispatched, though an already-owned active mow can still be commanded to return to the dock for safety/battery/weather/window holds.
- **`Automatic control` (`switch.*_automatic_control`):** Defaults to **off** (`False`). Turning it on is blocked with an error unless:
  1. `Confirm setup and competing schedules off` has been pressed (`setup_confirmed: true`),
  2. Every check in `Readiness` is `true`, and
  3. The mower is currently `docked` (unless resuming an already-owned `active_zone`).

---

## 5. Restart Disarming and Options Reload Behavior

To prevent unexpected physical movement after power outages, upgrades, or configuration edits:

1. **Always Disarmed on Startup:** `Automatic control` (`armed`) is initialized to `False` and `Hold new work` (`hold`) is initialized to `True` whenever Home Assistant starts or the integration reloads. Switch states are intentionally never restored armed from Home Assistant state history.
2. **Editing Options Disarms Control:** Saving changes in the integration's **Configure** flow triggers an entry reload (`async_options_updated`), returning the coordinator to disarmed Observation mode (`armed = False`, `hold = True`).
3. **Crash & Restart Reconciliation (`reconciling`):** Job ownership, progress checkpoints, and pending command flags are saved to `.storage` before any service call is made. If Home Assistant restarts while a job or command was active, `reconcile_restart()` places the state into `reconciling`. It **never** blindly replays a previous `mammotion.start_mow` or `lawn_mower.dock` command after a restart; instead, it waits for fresh telemetry to confirm whether the mower is actively cutting or docked and charging.

---

## 6. Commissioning Distinction: Lab vs. Real Mower Capabilities

### What the Isolated Lab (`lab/`) Can Test
The repository includes an air-gapped Docker Compose environment (`lab/compose.yaml` with `internal: true` networking) and a synthetic `mower_simulator` component (`lab/custom_components/mower_simulator`). In the lab:
- `mower_simulator` creates fake entities (`lawn_mower.lab_mower`, synthetic battery/progress/activity/error/blade_time sensors, 3 area switches with hashes `10001–10003`, `person.lab_operator`, and `notify.lab_capture`) and registers a mock `mammotion.start_mow` service.
- Calling `mower_simulator.tick` synthetically increments `progress` and `blade_time`, drains/charges `battery`, and transitions states in memory.
- This validates the coordinator's state machine transitions, config flow schemas, `.storage` persistence, and notification filtering **in software only**.

### What Software Checks and the Lab Cannot Validate
Neither unit tests, the `lab/` simulator, nor the `Readiness` preflight sensor can verify physical reality on your property:
- **Physical Map & Perimeter Safety:** Whether native Mammotion area switches correspond to obstacle-free lawn boundaries, safe slopes, and clear channels.
- **Adapter & Firmware Behavior:** How your specific Mammotion model, firmware version, and `mammotion` integration version handle `mammotion.start_mow` parameters (`toward`, `channel_width`, `mowing_laps`, `blade_height`, `speed`, `start_progress`) over real Bluetooth, local, or cloud transport.
- **Physical Cutting Proof:** On a real mower, the runtime requires `lawn_mower` state `"mowing"`, `activity_entity` state `"MODE_WORKING"`, and an observed increase in `blade_time_entity` after dispatch, correlated with a subsequent progress report, before treating a start as confirmed cutting. If your mower does not update `blade_time_entity` frequently during a cut, starts will time out into `start_unconfirmed`.
- **Physical Docking & Charging Contact:** Whether your `reserve_battery` percentage leaves enough margin for the mower to travel back to the charger and establish sustained charging contact (`charging_stable_seconds = 60s`).

### Supervised First-Run Commissioning Checklist
Before relying on `mower_coordinator` on a real mower:
1. Disable all schedules in the Mammotion mobile app and verify any legacy YAML mower automations (`input_boolean.mower_package_enabled`, `automation.mower_*`) are turned off.
2. Complete the setup wizard with a single small, easily observed mowing area first, and verify `Readiness` reports `ready`.
3. Press **Send test notification**, verify the test message arrives on your device, and press **Confirm test notification received**.
4. Observe the `Explanation` sensor while in `observe` mode to confirm the coordinator's planned behavior matches expectations.
5. With the mower physically docked, clear the lawn of people, pets, and obstacles, press **Confirm setup and competing schedules off**, turn off **Hold new work**, and turn on **Automatic control** while physically supervising the mower through launch, cutting, and return-to-dock charging.
