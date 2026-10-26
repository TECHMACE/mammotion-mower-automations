# Isolated mower integration lab

This runs Home Assistant Container 2026.10.4 on Docker Desktop, with a **simulated** mower. It is not Home Assistant OS and it never contacts a mower. No production configuration, backup, token, map, USB device or Bluetooth device is used.

## Start and inspect

From the repository root:

```sh
docker compose -f lab/compose.yaml up -d
python3 lab/client.py
python3 tools/test_lab.py
python3 lab/exercise_wizard.py
python3 lab/exercise_runtime.py --fresh
python3 lab/exercise_runtime.py --fresh --map-change
python3 lab/exercise_options.py
python3 lab/exercise_recovery.py handoff
python3 lab/exercise_recovery.py return
python3 lab/exercise_gates.py
python3 lab/exercise_forecast.py
python3 lab/exercise_contact.py
python3 lab/exercise_policy_options.py
```

The advanced recovery and handoff scenarios enable configurable automatic recovery and charger-free handoff explicitly. Their observation/grace timers use valid minimum settings and run in real time; the return budget scenario deliberately reaches an intervention state. The contact scenario deliberately supplies a charging flag without battery gain and expects intervention.

The runtime acceptance test replaces only its own fixture coordinator entry when `--fresh` is supplied; it refuses unknown or renamed entries. It exercises actual HA services against the fake mower and waits for real charging-stability timers. The options test leaves all-day quiet hours selected and the coordinator disarmed. The map-change scenario deliberately leaves its saved work quarantined for review.

On native Linux, the container runs as UID 0 with all capabilities dropped. Its synthetic configuration directory must therefore be owned by UID 0 (Docker Desktop handles shared-directory ownership differently). Before starting on Linux, run `sudo chown 0:0 lab/config` from this repository. This changes only the lab directory; never point these mounts at a working HA configuration. The source `configuration.yaml` remains readable, and generated credentials stay ignored.

The image is the official `ghcr.io/home-assistant/home-assistant:2026.10.4`. First startup can take a minute. The web interface is `http://127.0.0.1:18123`. `lab/client.py` completes creation of a dedicated test account, keeping its random password and refresh token only in ignored `lab/.evidence/auth.json` (mode 0600). Never publish this file. It does not read production environment variables or credentials. After first creation, finish ordinary HA onboarding in the lab UI if needed. The test driver uses only this fixed loopback URL.

The runtime integration source is mounted read-only from `custom_components/mower_coordinator`. Restart the **lab service only** after Python changes:

```sh
docker compose -f lab/compose.yaml restart homeassistant
```

Stop without deleting its test configuration:

```sh
docker compose -f lab/compose.yaml down
```

`mower_simulator.reset` resets fake mower observations, command records and notification records. It does not delete coordinator checkpoints or configuration. For a completely new installation, stop the lab and archive the generated `lab/config/.storage` directory outside the active config, then start again and remove the old ignored lab auth file. Do not reset a running instance or manipulate production storage.

## Isolation boundary

- Home Assistant is connected **only** to a Docker network marked `internal: true`; it has no default route and no published port.
- Docker Desktop does not publish an internal-network container's port. A separate fixed-destination Python TCP proxy exposes only `127.0.0.1:18123`, forwarding exclusively to lab HA port 8123.
- The proxy has a separate ordinary bridge solely for the host's port-forwarding path. It mounts only `proxy.py`, not HA config, tokens or the integration. It is not an HTTP forward proxy and offers no arbitrary destination routing.
- Both containers drop all Linux capabilities and use `no-new-privileges`. No host network, device passthrough, production mounts or privileged mode.
- The test driver inspects the network and routes and confirms public, documentation-address and Docker-host probes fail from HA. These checks are necessary: a separate container alone does not establish network isolation.
- Public image download occurs via the Docker daemon before runtime. No network access is required by the simulator or coordinator at runtime. Standard HA onboarding may try to initialize optional online services; their outbound traffic is blocked by this network.

## Simulator contract

All entities belong to one synthetic device (except the generated lab owner account). Main bindings:

| Role | Entity |
|---|---|
| Mower | `lawn_mower.lab_mower` |
| Battery / progress | `sensor.lab_battery`, `sensor.lab_progress` |
| Raw activity / error | `sensor.lab_activity`, `sensor.lab_error` |
| Cutting / travel | `sensor.lab_blade_time`, `sensor.lab_mileage` |
| Charging / rain / safety | `binary_sensor.lab_charging`, `binary_sensor.lab_rain`, `binary_sensor.lab_safety_clear` |
| Presence | `person.lab_operator` |
| Location | `device_tracker.lab_mower` (synthetic coordinates) |
| Native areas | `switch.lab_area_1` … `switch.lab_area_3`, hashes 10001 … 10003 |
| Modern notification sink | `notify.lab_notification_capture` |
| Legacy notification action | `notify.lab_capture` |
| Evidence | `sensor.lab_commands`, `sensor.lab_notifications` attributes `records` |

`mammotion.start_mow`, `mammotion.cancel_job`, and `mammotion.get_map_data`, and `mammotion.get_geojson` are local fakes. Mower start, pause, stop and dock are captured. The fake reproduces the native Dock toggle: Dock while already returning cancels that return. Return recovery must therefore pause/cancel the return, observe the stopped state, then issue Dock. Native Resume preserves progress. No vendor library or account exists here. The simulator supports only the tested contract, not all Mammotion firmware behavior.

`mower_simulator.set_state` accepts fields such as `battery`, `progress`, `mower`, `activity`, `error`, `charging`, `rain`, `safety_clear`, `operator_home`, `blade_time`, `mileage`, `delay_ack`, `fail_dock`, `fail_notify`, and `map_revision`, and `map_sync_status`. Synthetic cached geometry is available through dataclass frame lists on the fixture reporting coordinator, including no-go geometry; the synced-status entity has the upstream translation key. The coordinator exercises its full cached map hashing path without service calls or a simulator-only revision shortcut. `no_go_revision` edits a synthetic no-go boundary while preserving area IDs. `mower_simulator.tick` advances fake mowing progress/usage, return-to-dock, or charging deterministically. `delay_ack: true` records start commands without changing mower activity. `fail_dock: true` leaves returns in progress. `fail_notify: true` raises a local delivery failure.

Tests should distinguish captured commands from resulting observations. Simulation proves software behavior only. Physical cutting coverage, traction, route execution and charging contacts remain unverified.

## What the acceptance scripts verify

- `tools/test_lab.py`: container/network isolation, failed egress probes, simulator contract and local notification capture.
- `exercise_wizard.py`: each native configuration form, invalid input rejection, arbitrary two-area configuration, creation in observation mode.
- `exercise_runtime.py --fresh`: delayed acknowledgement without duplicate start; cutting-backed 55% checkpoint; reserve return; sustained charging before one resume at 55%; completion evidence updates.
- `exercise_runtime.py --fresh --map-change`: a no-go boundary edit with unchanged area IDs quarantines the saved checkpoint; entry reload preserves progress and disarms without another start.
- `exercise_options.py`: native options reload disarms; modern and legacy targets; explicit test during quiet hours; simulated delivery failure and recovery.

These are integration acceptance tests inside HA Container, not evidence that a physical mower executed a route or charged successfully.
