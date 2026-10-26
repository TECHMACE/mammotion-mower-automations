# Native HA acceptance coverage

This matrix is for the isolated fake mower, never production. Captured commands and simulated observations do not establish physical mower behavior.

| Behavior | Native HA evidence |
| --- | --- |
| Wizard forms and invalid inputs | `exercise_wizard.py` |
| Delayed launch acknowledgement, no duplicate | `exercise_runtime.py` |
| Cutting-backed checkpoint and recharge/resume | `exercise_runtime.py` |
| Same-ID no-go geometry edit | `exercise_runtime.py --map-change` |
| Configuration reload retains checkpoint and disarms | `exercise_runtime.py --map-change` |
| Full HA restart retains checkpoint and disarms | `check_restart.py` |
| Notification targets, quiet-period explicit test, failure/recovery | `exercise_options.py` |
| In-place pause/channel recovery | `exercise_recovery.py` (real timer scenarios) |
| Telemetry grace cancelled by later movement | `exercise_recovery.py` (real timer scenarios) |
| Return retry budget survives brief movement | `exercise_recovery.py` (real timer scenarios) |
| Eligible next-area handoff without docking | `exercise_recovery.py` (real timer scenarios) |
| Rain/weather, battery, presence and physical-safety vetoes | `exercise_gates.py`, `exercise_forecast.py` |

## Reference coverage to retain

The mature YAML reference also includes seasonal grouped scheduling and not-before dates; rain drying holds and proved-dry-launch light-rain tolerance; forecast outlook and source freshness; measured battery-burn resume targets; zone-specific roadside stationary/orphan protection; charging-contact recovery requiring sustained contact and battery gain; unmapped-error journaling; and owned telemetry refresh. These are separate behaviors from generic start/resume. The configurable integration core and adapter regression tests cover these policy branches; native HA scripts exercise representative end-to-end paths. Passing those representative scenarios must not be described as physical validation or exhaustive coverage of every installation-specific combination.
