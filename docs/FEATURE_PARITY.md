# Where did the automations go?

They now share one coordinator. The public YAML reference stays available, but installing the integration does not require importing 34 separate automations and scripts. Configure your mower, areas and rules in the setup wizard. The coordinator keeps the queue, checkpoint and command ownership together.

This maps the behaviors in [the original inventory](COMPONENTS.md) to the integration. It describes implementation coverage, not physical mower certification. Native lab coverage is tracked separately in [the acceptance matrix](../lab/BEHAVIOR_MATRIX.md).

| Original behavior | Configurable integration equivalent | Software evidence |
| --- | --- | --- |
| Smart auto-unstick; extended stall watchdog; obstruction dock; working-pause recovery | Fresh GPS, mileage and RTK evidence; sustained stationary observation plus telemetry grace; native Resume or checkpoint fallback; bounded retries and dock fallback | Core recovery scenarios; adapter motion/fault tests; native recovery driver |
| Departure safety | Presence gate and protective return for owned work | Core protective-return tests; native safety gates |
| Guarded progress checkpoint; owner completion latch; owner reconcile | Persisted ownership, cutting-backed progress, queue reconciliation and full map/profile identity | Core checkpoint tests; native runtime, map-change and restart drivers |
| Seasonal interval schedule; run due plan | Monthly intervals, grouped areas and anchors, eligible groups, weekdays, months, excluded dates, area not-before dates, rest between completed plans, overdue-first planning | Core calendar/group/rest tests; native advanced-options driver |
| Start/release rain hold | Local rain veto plus configurable drying interval, including persisted wet observation | Adapter drying tests; core rain tests; native gates |
| Light-rain safety; tolerance cleanup; prove dry launch | Optional light-rain weather tolerance only after owned cutting proves a dry launch; cleanup on charging/new route; native rain protections stay enabled | Adapter dry-launch tests |
| Unmapped error journal | Bounded journal of fault category, numeric code and time; unknown/critical current faults block recovery | Adapter fault tests; sanitized diagnostics |
| Weather freshness and outlook | Optional multiple weather sources, current conditions, wind/gust limits, temperature floor and hourly forecast outlook | Pure policy tests; native forecast driver |
| Orphan battery reserve; roadside orphan return | Explicit opt-in protective return for external work, without claiming or resuming its checkpoint; operator reset required afterward | Core external-work safety/ownership tests |
| Roadside silent stall; roadside stationary tracker | Per-area stationary-return deadline based on fresh physical travel evidence, independent of increasing blade time | Core stationary deadline tests; adapter travel evidence |
| Owned telemetry refresh | Bounded entity refresh while the coordinator owns a job | Adapter runtime; intentionally no permanent map/report stream |
| Idle but not charging | One bounded contact recovery attempt, sustained charging and battery gain before resuming, then attention if unsuccessful | Core contact tests; native no-gain charging driver |
| Clear recovered stuck warning | Dismiss this coordinator's persistent notice after verified recovery | Notification dismissal test; runtime evidence checks |
| Owned pause alert; self-check intervention; exhausted recovery alert | Configurable notifications, persistent attention notices, quiet hours, deduplication and delivery diagnostics | Notification suite; native options/delivery driver |
| Consecutive dispatch; fresh-area start; run owned area; consecutive handoff; dock-cancel-restart; finalize owned area | Serialized durable intents, guarded in-place handoff, confirmed task cancellation when needed, preserved queue and checkpoint, bounded acknowledgement | Core handoff tests; adapter final guards; native charger-free handoff driver |
| Resume target calculator | Optional measured battery-burn target with configurable reserve, buffer and target bounds; fallback until enough evidence exists | Pure recharge policy and adapter persistence tests |
| Return/channel recovery | Observe native returns; cancel a stalled return once, wait for fresh READY/PAUSE, then issue one Dock; never toggle Dock blindly while RETURNING | Core two-stage return tests; adapter dispatch/gate tests; native return driver |

## Deliberate installation differences

Automatic recovery and in-place handoff default on in the wizard, but every installation starts disarmed. Recovery needs the selected mower's fresh motion sensors. Optional weather, forecasting, light-rain tolerance and external-work protection are explicit choices. Editing options or restarting Home Assistant disarms commands and retains saved work for review.

The original house's area names, geometry, accounts, dates, notification destinations and device IDs are not defaults. Choose your own. Native vendor safety remains in charge; light-rain tolerance does not switch off a mower rain sensor. The integration will not adopt an unrelated native job or guess a checkpoint after a remap.

A simulated command proves the software made that decision. It cannot prove the mower crossed a channel, cut an edge or made reliable charging contact. Those checks belong in each owner's supervised commissioning.
