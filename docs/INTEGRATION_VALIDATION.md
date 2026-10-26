# Integration validation and release status

`0.2.0-alpha.2` is a development preview. It is separate from the original YAML reference release. It has not been deployed to the author's working Home Assistant system or tested on a physical mower.

## Current alpha.2 evidence

- **225 tests passed without skips** in the official Home Assistant 2026.10.4 container with network disabled.
- Configurable recovery, handoff, calendar/group/rest policies, charging/contact logic and weather policy are implemented. Implementation is not a blanket acceptance result.
- The expanded local native HA simulator batch **passed**, including in-place resume, charger-free handoff, bounded pause/settle/Dock return recovery, charging-contact checks, forecast gates, notifications, map quarantine and full restart. [Detailed results and revision boundaries](../lab/VALIDATION_STATUS.md).
- See the [feature mapping](FEATURE_PARITY.md) and [lab behavior matrix](../lab/BEHAVIOR_MATRIX.md) for coverage. GitHub repeats the final source in three independent, fresh isolated labs: baseline, recovery and policy.
- All seven [GitHub checks passed](https://github.com/TECHMACE/mammotion-mower-automations/actions/runs/40408085508) on code commit `aec73d3b9f495722f86fc457bc7bb1e80c00bc8d`, including three independent fresh native labs. Subsequent changes only record these results.
- No production Home Assistant deployment or physical mower commissioning is claimed for this integration release.

Earlier alpha.1 simulator runs exercised wizard setup, delayed acknowledgement, charging/resume, checkpoint persistence, map-change quarantine, restart disarming and notification behavior. Those are historical evidence, not a substitute for the current expanded run. Every mower action in that lab was simulated.

## Reproduce software checks

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python tools/check_privacy.py
python tools/check_integration.py --output build/mammotion-mower-coordinator.zip
```

Config-flow tests additionally require the pinned Home Assistant version used in `.github/workflows/validate.yml`. The workflow checks the original YAML configuration, integration metadata, HACS rules, and a fresh isolated HA runtime. The ZIP contains only the allowlisted integration directory, excluding lab storage, accounts, local maps, and test evidence.

See [the lab guide](../lab/README.md) for the official Home Assistant Container 2026.10.4 simulator. Its HA container has no default route or outbound network access. A fixed local proxy exposes its UI on `127.0.0.1:18123`. This tests Home Assistant Container, not a full Home Assistant OS installation or the HACS download UI.

## Evidence boundaries

- Pure policy tests exercise queue preservation, delayed acknowledgement, checkpoints, charging, return budgets, route changes, and fail-closed safety gates.
- Adapter tests exercise durable intent, final command guards, readiness, notifications, and restart behavior.
- Native HA config/options flow tests validate the actual schema and entity registry behavior.
- Simulator acceptance tests capture commands separately from simulated state changes. They cannot establish physical coverage or reliable charging contacts.
- Native frontend setup/options screens were inspected, including notification destinations, event selection, quiet hours, and urgent override.

The integration now exposes configurable recovery and charger-free handoff, both defaulting on as policies. The feature matrix tracks configurable coverage of the YAML reference and the evidence for each behavior; it does not establish identical physical behavior across installations. Restart and configuration reload disarm all integration commands; the user must rearm after review. Keep the mower's own protections enabled.

Real-model compatibility must be confirmed against the adapter contract in the setup guide. A passing fake-mower scenario does not certify a vendor firmware or integration version. First physical commissioning belongs on the installer's own supervised system, not on the author's working system as part of this build.

## Independent review and corrections

Claude contributed the notification delivery module and its failure/quiet-hours tests. Antigravity drafted the setup guide and independently reviewed the implementation. Review findings were checked against the actual pinned HA runtime and upstream adapter source; reviewer claims are not themselves validation.

Corrections include persisted clearing of optional settings, current Self check sensor discovery instead of historical errors, charging duration measured from observed charging onset, final command guards after durable save, notification receipt interlocks, concurrent notification deduplication, and copied commissioning attributes so HA publishes evidence changes.

HA 2026.10 uses `probatio` for these schemas. Native wizard tests in the official container confirm that import; replacing it based on older HA conventions would be incorrect. Unchanged native coordinator sensor reports still refresh HA `last_reported`; the adapter separately requires increasing blade usage and correlated progress to recognize cutting. These reports remain device telemetry, not direct proof that every strip was cut.

## Upstream adapter contract

Source inspection used [Mammotion-HA commit 6c5f353](https://github.com/mikey0000/Mammotion-HA/tree/6c5f3537a4aedd95148f9e95134918d758c2d41d) (0.6.19-beta4, requiring PyMammotion 0.10.11). Runtime uses the matching mower's reporting coordinator and validates the static cached-map structure before hashing it. No raw geometry is saved in coordinator storage or diagnostics. Unknown frame types, incomplete map frames, stale map sync, or ambiguous coordinator ownership block control. This internal adapter coupling is a compatibility limitation and is covered by synthetic cache fixtures; it has not been exercised against a physical mower in this release.
