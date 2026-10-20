# Setup and commissioning

The configuration validator is pinned to Home Assistant Core 2026.10.2; older releases are not supported by this alpha. This guide targets experienced Home Assistant users comfortable inspecting YAML, Jinja templates, integration entities and automation traces. Keep the mower safely parked while installing. Installation does not require sending it out to manufacture a test event.

## 1. Confirm the integration contract

Use an already working Mammotion integration. Verify the actions and entities below in your own Home Assistant Developer Tools before enabling this package. An entity with a similar name is not sufficient: values, units, attributes and behavior must match.

| Dependency | Required contract |
| --- | --- |
| Mower | `lawn_mower` states include `docked`, `mowing`, `paused`, `idle`, `returning`; start, pause and dock actions are available. |
| Mammotion actions | `mammotion.start_mow`, `mammotion.cancel_job`, `mammotion.get_geojson`; inspect their installed schemas and compare every call in generated YAML. |
| Activity | Raw mode values used include `MODE_READY`, `MODE_WORKING`, `MODE_PAUSE`, `MODE_RETURNING`, `MODE_CHARGING_PAUSE`, `MODE_LOCK`. |
| Battery/progress | Numeric percentages, 0–100. Charging is a separate `on`/`off` binary sensor. |
| Error telemetry | Code, text, self-check and parseable error timestamp; codes and reset semantics must match the installed firmware/integration. |
| Position | Tracker and position/RTK telemetry with timestamps and attributes used by the templates. Check freshness and stationary detection without publishing coordinates. |
| Motion/usage | Mowing speed, total mileage, blade-used time and work area. Inspect expected units before relying on burn-rate or motion calculations; there is no universal unit conversion layer. |
| Native areas | Six switch entities on the mower device with positive numeric `hash` attributes; map IDs are not Home Assistant entity IDs. |
| Weather | Two weather entities with forecast support, a local rain sensor, observation time, wind and gust values. Wind inputs and both bound weather entities must report mph. Checks use only the two bound sources; missing or mismatched units block starts/resumes. |
| Temperature | Smoothed outdoor temperature explicitly reporting °F; missing or mismatched units block starts/resumes. |
| Presence | A person entity whose home state is `home`, and a vacation-mode input boolean. Starts/resumes require the operator home; accumulated successful batches do not authorize away operation. |
| Seasonal helpers | Growth mode uses `High growth` and `Transition`; other modes follow the low-growth branch. Override uses `Auto` for automatic seasonal adjustments. |
| Notifications | A local operator notification action for ordinary alerts; exhausted recovery uses persistent notifications. |
| Selects/buttons | Traversal/turnaround selects and refresh/cancel buttons with options/behavior matching source calls. |

The package does not install or configure these external dependencies. Do not substitute constant “safe” values to bypass missing sensors. Keep native mower schedules off and disable competing launch/recovery automations so there is one coordinator.

## 2. Make a private backup and bindings file

Take a Home Assistant backup and retain a private copy of your current mower automation state. Resolve any existing `mower_` entity-ID collisions before installation; suffixes such as `_2` can break internal references.

From the repository root:

```sh
mkdir -p local build
cp settings.example.json local/settings.json
```

Fill every required setting using `source/bindings.json` as the binding catalog. Internal automation, script and helper IDs are defined by the package. The 43 required local bindings include external entity IDs, native map hashes, the Home Assistant device-registry ID and `NOTIFICATION_1`/`NOTIFICATION_2`, the integration warning notification IDs used for clearing recovered warnings. Read those IDs from your own integration; they can contain mower identifiers. These values belong in `local/settings.json`. Never put credentials in that file: the package uses the integration's existing authentication.

`MAP_HASH_N` corresponds to native `Area N`. Inspect the `expected_hashes` mapping in the fresh-area script and confirm each token matches the intended native area. Verify each area switch belongs to the selected mower device and has exactly one matching hash. A map redraw or route-profile change invalidates a saved checkpoint; do not relabel an old checkpoint to force reuse.

Build locally:

```sh
python3 tools/build.py --settings local/settings.json --output build/mower_package.yaml
```

For maintained local helper overrides, supply `--helper-settings local/helper-settings.json`. This optional JSON object maps package helper entity IDs to display-only `name` and `icon` overrides. State-machine options, ranges and initialization cannot be overridden through this file. Review generated values after every build. Use the repository's dependency instructions if the compiler requests additional Python packages. Inspect compiler errors rather than filling unknown bindings with arbitrary entities. Keep `local/`, generated `build/`, backups and traces private even if Git ignores them.

## 3. Review the generated configuration

Read the generated YAML before installing it. The reference layout uses logical `Zone A` through `Zone E`, six native areas, and `Group A`/`Group B`. These are internal enum strings, not labels to casually rename. A different layout needs coordinated changes to mapping, helper options, scheduler, completion keys, route profiles and tests.

Configure the area-map helper with a JSON object containing each logical zone's native area list and a nonempty `_revision`. Example shape only:

```json
{"_revision":"local-v1","Zone A":["Area 1","Area 2"],"Zone B":["Area 3"],"Zone C":["Area 4"],"Zone D":["Area 5"],"Zone E":["Area 6"]}
```

This is an illustrative mapping, not a recommendation for your property. Keep the value within the helper's 255-character limit. Do not assign one native area to multiple zones. Verify all mappings against the real mower map while dispatch is disabled.

Review these settings together:

- Start/resume window: reference logic uses 09:00–19:00 in Home Assistant's configured timezone. Change every relevant guard consistently.
- Seasonal cadence and winter dormancy: reference month and Fahrenheit assumptions may not suit your climate or grass.
- Battery reserve, per-zone departure thresholds, recharge target and recovery budgets.
- Spacing in centimeters, speed/height parameters and perimeter/angle profiles. Zone C has an explicit stricter profile check; changing only the call arguments will cause refusal.
- Presence, departure, rain, weather freshness and safety-error classification. Preserve these protections while adapting their inputs.
- Historical one-off exceptions have been neutralized. Do not reactivate them as a shortcut around current gates.

### Fixed reference behavior requiring local review

Bindings substitute identities; they do not automatically adapt the yard topology or mower model. The supplied plan still has five logical zones and six native areas, with paired zone groups and zone-specific rules. Native area labels in diagnostic text are generic Area N labels; verify their meaning against your map.

| Fixed reference choice | What to review before enabling |
| --- | --- |
| In-place handoff battery floors | Zone A 55%, B 50%, C 45%, D 40%, E 55%; validate against local area sizes and safe return reserve. |
| Roadside stationary protection | Applies to Zones A and C; it does not automatically identify hazards in other zones. |
| Zone C profile and hold | A dedicated not-before date and exact route profile are enforced; update both dispatch and validation if adapting it. |
| Route angles | The reference uses native-area angle helpers and 0°/90° alternation. |
| Cutting commands | Both fresh start and checkpoint restart send `blade_height: 80`, `speed: 0.5`, `ultra_wave: 10`, `is_dump: true`, `collect_grass_frequency: 10`, and `obstacle_laps: 1`, plus the selected spacing, perimeter and angle profile. |
| Traversal/turnaround | The reference changes traversal/turnaround selects, including `multipoint`; confirm supported options. |
| Error handling | Numeric error classifications come from the reference integration/model and are not certified across all Mammotion models or firmware. |
| Seasonal schedule | Month-based logic assumes a northern-hemisphere season; temperature thresholds assume °F. Review for your climate. |

The cutting parameters are actual command values and can override app settings. Check their units and valid ranges in the installed integration, and confirm model/attachment compatibility. Do not assume an unsupported height, collection mode or traversal option will safely do nothing. Adapt every relevant call and route identity together, validate the generated configuration, then commission under supervision. This release is not a model-neutral settings translator.

## 4. Install inactive and validate

Use Home Assistant packages. If packages are not already enabled, merge the following into your existing `homeassistant:` section; do not create a duplicate top-level section:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Copy your reviewed output to the `packages` directory in your Home Assistant configuration. Run Home Assistant's full configuration check. Resolve every error before restarting or reloading. After loading, verify all expected helpers, scripts and automations exist with the intended IDs and inspect the logs for missing actions, unsupported fields or template errors.

Leave `input_boolean.mower_package_enabled` off and manual hold on. Automations load enabled on first install and restore their enabled state after restart. Dock-only protection is intentionally independent of the motion-enable gate, so installation can issue protective Dock requests if the mower is out. Install while it is safely parked. Verify bindings, sensor units, timestamps and template results using read-only tools. Do not click “Run actions” on movement scripts to validate syntax; that can execute real mower commands and can bypass automation trigger conditions.

## 5. Set helper values and persistence deliberately

Not-before dates are initially unset; configure deliberate local eligibility dates before enabling. An explicit future date such as `2099-01-01` can retain a hold. Fill the area map and required tuning inputs. Completion dates must reflect known work, not fabricated completion. Do not invent a nonzero checkpoint or an active owner token to make an initial launch pass.

Before the first launch, initialize the following through the Home Assistant helper UI or the appropriate `input_*` action, while the package is disabled and there is **no active mower job**. These are one-time state changes, not permanent YAML `initial` settings. If a real job exists, preserve its state and reconcile it before commissioning rather than resetting it.

| Helper state | First-install value or decision |
| --- | --- |
| Active area, resume area, active batch, resume batch | `Idle` |
| Coordinator state, due plan | `Idle` |
| Job token, route signature, checkpoint map identity | `Idle` |
| Owner checkpoint, resume progress | `0` |
| Area map | Your verified local JSON mapping and revision, as above. |
| Scheduling and zone-specific not-before dates | Deliberate local eligibility dates; a future date retains a hold. |
| High wind limit | Choose for the property and mower; reference value is `25` mph. Check all weather inputs use compatible units. |
| Rain hold minutes | Choose for local drying conditions; reference value is `20` minutes. |
| Roadside stationary limit | Choose for expected return behavior; reference value is `10` minutes. |
| Zone group hold | `input_boolean.mower_zone_group_hold` blocks scheduling the Zone A/C group when on. Set it deliberately for local eligibility; there is no hardcoded weekday restriction. |
| Completion history | Only known actual completion dates. Leave unproved work unproved. |

Use the exact public helper entity IDs in [the component inventory](COMPONENTS.md). Inspect the remaining helper defaults and options before enabling. Do not reset checkpoints or ownership as routine maintenance: those values are how recovery distinguishes existing work from a fresh job.

**YAML `initial` values override restored helper state after a restart.** Checkpoint, ownership and completion state are intentionally allowed to restore. Manual hold starts on and package enable starts off as restart interlocks. Safety configuration uses explicit restart defaults: recovery target 95%, rain hold 20 minutes, stationary limit 10 minutes and wind limit 25 mph. If you need different permanent safety settings, adapt the maintained source and validate it; changing a helper in the UI does not override its next-startup YAML default.

Seed runtime state once through helper actions, not permanent `initial` values. Repeatedly resetting checkpoints, ownership, completion dates or area mapping defeats recovery and scheduling. Review every generated update before deployment.

Automations omit `initial_state`, allowing enabled state to restore. Dock-only protective automations do not depend on the package motion gate. Keep them enabled so rain, departure and low-battery return can still act when a restart disarms starts/resumes. Turning the package off is not an emergency stop and does not cancel a script already running.

Smart-unstick, working-pause and dock/cancel recovery share a persistent budget of at most three attempts. Fresh starts do not consume this recovery budget. Blade activity or a small progress increase does not reset that budget. After exhaustion, inspect and resolve the cause before manually resetting the budget helper; do not schedule an automatic reset to bypass the cap.

## 6. Commission during normal work

With the operator present, safe conditions and the area clear, enable the reviewed observers/recovery routines and scheduler, set the intended not-before dates, release manual hold and enable the package only when ready for normal mowing. Record the initial states and watch the first ordinary launch. Keep physical controls accessible.

Use the validation checklist to observe completion, charging and later resume. Leave unresolved capabilities marked unverified. Do not deliberately trap the mower, obstruct a channel, expose it to hazards, defeat rain sensors or drain its battery merely to exercise recovery. Investigate naturally occurring events using timestamps and traces; record any manual intervention so it is not mistaken for automatic recovery.

## Rollback and updates

For rollback, first secure the mower using its normal physical/operator controls. Disable the package and its automations, then stop any running package scripts only once the mower is safe. Remove the package or restore the backup and run a configuration check. Restore old schedules only after confirming there is no competing owner or queued job. Retain private checkpoint evidence for diagnosis.

For updates, compare source and generated YAML, back up helpers, rebuild with private bindings and repeat configuration validation. Recheck map identity and initialization settings. Treat firmware/integration changes as compatibility changes requiring renewed observation.

## Upstream references

- [Home Assistant packages](https://www.home-assistant.io/docs/configuration/packages/): inclusion and merge rules used by this package.
- [Home Assistant input boolean](https://www.home-assistant.io/integrations/input_boolean/): startup defaults and restored state.
- [Mammotion-HA integration](https://github.com/mikey0000/Mammotion-HA): integration installation, compatibility and upstream documentation. Confirm your installed version's action schemas locally.
