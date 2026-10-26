# Local native HA validation status

All checks use the isolated synthetic mower only. This file distinguishes completed tests from pending runs; it does not establish physical operation.

Current run (2026-10-26):

| Scenario | Status |
| --- | --- |
| In-place resume, delayed movement grace, charger-free next-area handoff | Passed before the subsequent return-toggle-only adapter fix; no dock was issued in this scenario |
| Rain, presence, weather, battery and physical-safety launch vetoes | Passed; each gate produced its own explanation after charging stability matured |
| Returning-state pause/verified-stop/dock recovery and persistent budget | Running against final toggle-aware simulator and adapter |
| Charging flag without sustained battery gain | Pending final run |
| Baseline delayed acknowledgement, recharge/checkpoint/resume, completion | Pending final run with strengthened contact confirmation |
| Unsafe hourly forecast and subsequent clear forecast | Unsafe hold observed; complete revised scenario pending |
| Advanced policy native form validation | Pending final run |
| Map identity quarantine and full HA restart | Pending final run |

Earlier alpha acceptance also passed native wizard, notification options/failure handling, checkpoint persistence and isolation probes. Repeat the scripts for the current source rather than relying on those earlier results.
