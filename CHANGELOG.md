## Unreleased

- Replace the overbroad readiness diagnostic key `no_legacy_controller_enabled` with `no_known_controller_reported_on`. Templates using the old attribute must migrate. The predicate only detects matching entity IDs reporting `on`; it does not prove exclusive control or disabled/missing entities. Expose its scope and clarify recovery defaults and hold/disarm behavior.

# Changelog

## 0.2.0-alpha.2 — 2026-10-26

- Publish the integration for HACS custom-repository installation with a beginner start-here guide covering HACS, Mammotion connection, setup, notifications and first-run checks.

### Mower Coordinator configurable parity preview (0.2.0-alpha.2)

- Expose automatic recovery and charger-free handoff as configurable policies, default on; commissioning remains observation-first and disarmed.
- Add calendar eligibility, excluded dates, seasonal intervals, grouped work, rest days and area-specific stationary limits.
- Add adaptive recharge, multiple weather sources, optional hourly forecast checks, dry-out delay and optional light-rain tolerance without disabling native safety.
- Require fresh motion evidence for bounded recovery; persist attempt accounting and retain saved work.
- Recover stalled native returns through pause, fresh settled telemetry and Dock, avoiding Mammotion's Dock-while-returning cancellation behavior.
- Confirm charging contact through sustained contact and battery gain; bound redock attempts.
- Add optional protection of unowned work without checkpoint adoption, automatic restart or silent handoff of ownership.
- Current software validation: 225 tests, no skips, official HA 2026.10.4 container with network disabled. Expanded local native simulator acceptance and all seven GitHub checks passed; physical commissioning remains unproved.

### Earlier Mower Coordinator preview (0.2.0-alpha.1)

- Add native setup and options wizards for arbitrary mowing areas, direction rotation, operating rules, optional weather, and notification routing.
- Add persistent job ownership, guarded checkpoints, low-battery return, recharge continuation, readiness explanations, and deliberate commissioning controls.
- Add testable notifications with quiet hours, event choices, urgent override, rate limits, and isolated delivery failures.
- Add a network-isolated Home Assistant Container lab, fake mower, native-flow/runtime acceptance checks, HACS metadata, and reproducible component-only ZIP packaging.
- Start disarmed after install, restart, and options changes. That initial preview omitted automatic obstruction recovery and charger-free handoff; alpha.2 adds their configurable policies. Physical commissioning is still required.

### YAML reference maintenance

- Allow one guarded same-day reattachment after a newly established, stable charging session newer than the last owned-controller start. Existing cross-day limits and checkpoint identity checks remain.
- Preserve the three-attempt return-recovery budget across brief movement; repeated channel failures no longer reset it within the active return episode.
- Added 14 regression cases; 65 synthetic tests now pass.

## 0.1.0-alpha.1

- Initial public reference release: 26 automations, 8 scripts and 67 helper definitions.
- Local binding compiler for device entities, map hashes and integration warning IDs; no installation identifiers are shipped.
- Preserved ownership/checkpoint, launch confirmation, queue, low-battery return, recovery and consecutive-area logic.
- Included the bounded late-telemetry grace and physical-progress recheck in trapped recovery.
- Added disarmed motion defaults, setup/commissioning guide, synthetic regression tests and privacy checks.
- Hardened binding validation, weather scope, presence/unit guards, restart protection and a persistent recovery budget.
- Household speaker routing removed; terminal recovery alerts use persistent notifications. Historical dated exceptions neutralized; obsolete migration controllers omitted.
- Public adaptation has not been commissioned on another mower. Refer to the validation guide for the evidence boundary.
