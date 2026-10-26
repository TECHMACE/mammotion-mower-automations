# Mammotion Mower Coordinator — 0.2.0-alpha.2

Let the mower mow. You have other things to do.

This alpha brings the recovery and scheduling work into configurable Home Assistant screens. Pick your Mammotion mower, add your areas and cutting directions, choose when it can work, and tell it where to send a message. Your lawn, your settings.

Automatic recovery and going straight to the next eligible area now default on as configurable policies. That does not start the mower: setup, restart and configuration changes still leave control disarmed. Readiness and notification checks come first.

There is more room to fit the plan to your lawn: weekday and seasonal calendars, excluded dates, area groups, rest days, not-before dates, seasonal intervals and area-specific stationary limits. Adaptive recharge estimates what unfinished work needs. Optional forecasts and light-rain tolerance add choices while native rain and safety protections remain intact.

Recovery waits for fresh motion evidence, respects its attempt budget and keeps the checkpoint. A stalled native return uses a guarded pause/settle/Dock sequence because sending Dock while Mammotion is already returning can cancel that return. Charging needs time and battery gain; an arrival message is not enough.

Optional external-work protection defaults off. If you enable it, the coordinator can make a protective return for a job you started elsewhere. It does not adopt or restart that job. Inspect it before clearing the hold.

**Still an alpha.** The current code passed 225 tests without skips in the official Home Assistant 2026.10.4 container with network disabled. Expanded local native simulator scenarios and all seven GitHub checks passed; see the [behavior matrix](../lab/BEHAVIOR_MATRIX.md) and [validation notes](INTEGRATION_VALIDATION.md). No physical mower commissioning is claimed. A fake mower cannot prove real traction, coverage or clean charging contacts.

## Make it yours

Fork it, branch it, improve it and spread the love. The [MIT license](../LICENSE) permits using, modifying and redistributing your version, including commercially; keep its license and copyright notice. Pull requests are welcome, not a condition of using your own changes.

This is an independent community project, not an official Mammotion product. Start with the [setup guide](INTEGRATION.md). Install this alpha through the HACS custom repository, selecting v0.2.0-alpha.2 with beta versions enabled if needed. The [start-here guide](START_HERE.md) includes HACS installation and the complete setup path.
