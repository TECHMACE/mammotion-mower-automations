# Changelog

## Unreleased

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
