# Local native HA validation

These checks ran on 2026-10-26 in isolated Home Assistant Container 2026.10.4 with synthetic mower entities. No production HA endpoint, configuration, credentials or device was used. Simulation does not establish physical cutting, obstacle clearance or charger contact.

| Scenario | Result |
| --- | --- |
| Native wizard and arbitrary two-area configuration | Passed, including invalid inputs |
| In-place resume and delayed movement grace | Passed: late GPS/odometer movement cancelled the candidate; later sustained stationarity produced one Resume retaining 35% progress |
| Charger-free next-area handoff | Passed: second area used its 45° profile and 0% start with zero Dock commands |
| Returning-state recovery | Passed: two pause/verified-stop/Dock sequences; brief movement did not reset the retry budget; exhaustion stopped further commands |
| Battery, rain, presence, weather and physical-safety gates | Passed after charging stability matured; each gate produced its own explanation |
| Charging flag without battery gain | Passed: no resume; timeout raised attention and retained 35% checkpoint |
| Delayed acknowledgement and recharge/resume | Passed: one initial start, 55% checkpoint, 120-second contact confirmation, one 55% resume and completion evidence |
| Hourly forecast adapter | Passed: unsafe forecast held launch; clear forecast allowed exactly one simulated launch |
| Advanced policy forms | Passed: invalid recovery/calendar/weather/recharge policies rejected and valid edits reloaded disarmed |
| Notifications | Passed: modern and legacy capture targets, explicit quiet-hour test, delivery failure and recovery |
| Same-ID no-go geometry change | Passed: checkpoint 55% quarantined with no new dispatch; reload preserved it |
| Full HA restart | Passed: checkpoint, queue and retry count retained; control off, hold on, no command; resume/return budget attributes available |
| Isolation and simulator contract | Passed: internal-only HA network, no default route, blocked public/documentation/Docker-host probes, localhost-only UI, native Dock toggle reproduced |

The recovery/handoff cases ran before the final dispatch-guard and sensor-observability refinements. Focused regression tests cover those refinements. [GitHub CI](https://github.com/TECHMACE/mammotion-mower-automations/actions/runs/40408085508) repeated all native cases against code commit `aec73d3b9f495722f86fc457bc7bb1e80c00bc8d`: all seven checks passed, including independent baseline, recovery and policy labs. The full restart exposed a sensor startup-order dependency; its fix was verified with a second full restart.

After acceptance, the demo's recovery and handoff policies were enabled through the native options flow. Automatic control remains **off**, hold remains **on**, the synthetic mower is docked, the saved 55% checkpoint remains, and this options change issued no command. The retained quarantine deliberately demonstrates review of changed map identity.
