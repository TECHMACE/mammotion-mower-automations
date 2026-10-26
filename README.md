# Mammotion Mower Coordinator for Home Assistant

Let the mower mow. You have other things to do.

This is for **Mammotion mowers using Home Assistant**. Pick your mower, set up your areas and cutting directions, choose when it can work, and tell it where to send notifications. It keeps track of unfinished work and explains what it is waiting on.

Built from real mowing automation work, now being packaged so other people can set it up for their own lawn. This is a community project, not an official Mammotion product.

**`0.2.0-alpha.2`: configurable scheduling, recovery and direct area handoff.** Choose your areas and direction sequences, calendar and rest days, grouped work, battery targets, weather policy and notifications in Home Assistant. Automatic recovery and charger-free handoff default on as policies; setup still starts in observation mode with control disarmed.

- **[Start here: install HACS, connect your mower and run the setup wizard](docs/START_HERE.md)**
- [Full settings and first-run guide](docs/INTEGRATION.md)
- [Where the original automation behaviors live now](docs/FEATURE_PARITY.md)
- [What has been exercised in the lab](lab/BEHAVIOR_MATRIX.md)
- [Validation and release status](docs/INTEGRATION_VALIDATION.md)

The coordinator keeps unfinished work, waits for credible movement reports before retrying, and checks sustained charging rather than treating a Dock command as success. Adaptive recharge, optional forecast checks and dry-out holds help it decide when to continue. Optional protection for externally started work can send it home, but never takes over or restarts that work.

This is a development alpha for Mammotion, not a certified universal mower controller. Model compatibility and supervised physical commissioning remain necessary. Keep native safety protections on, and run only one coordinator. The original YAML reference is still available below.

Install through HACS as a **custom repository** of type **Integration**. Select **v0.2.0-alpha.2** (enable beta versions if needed), restart HA, then add **Mammotion Mower Coordinator** under Devices & services. The [start-here guide](docs/START_HERE.md) walks through HACS installation too. [Default HACS catalog submission #12760](https://github.com/hacs/default/pull/12760) is awaiting maintainer review. Until it is accepted, use the custom-repository steps. Mammotion-HA remains a separate prerequisite.

## Fork it. Make it yours. Spread the love.

Want to change the rules, add a feature, or take this in a completely different direction? Go for it. Fork the repo, branch it, and build what works for you. It is [MIT licensed](LICENSE), so you can use, modify, and redistribute it, including commercially. Keep the license and copyright notice with your copies.

If you fix something or make it easier for the next person, a pull request is welcome. You do not have to send changes back to use your own version.

Read the [alpha release notes](docs/RELEASE_NOTES.md) for what is ready and what still needs proving.

---

## Original YAML reference package


An **alpha reference package** for coordinating a Mammotion mower through Home Assistant: scheduling areas, preserving unfinished work, returning to charge, and recovering from selected interruptions with bounded retries.

This release shares the automation logic developed through real use, with installation-specific bindings removed. It needs technical commissioning. It is not a universal blueprint or a promise of unattended operation, and the public adaptation has not been physically validated on another installation.

## What it helps do

- Keep one owner of the active job, so schedule, recovery and handoff paths cooperate.
- Preserve progress and pending areas when telemetry arrives late or an acknowledgement fails.
- Refresh status after dispatch and distinguish a delayed report from an actual failed start without blindly issuing duplicate starts.
- Resume an eligible interrupted job from a saved checkpoint, subject to route identity and safety checks.
- Return on low battery, calculate a recharge target, and retain unfinished work while charging.
- Attempt a consecutive-area handoff when battery, ownership and safety gates allow it.
- Retry selected stuck/return failures within a finite recovery budget, then surface an intervention notice.
- Apply rain, weather freshness, presence, manual hold, time-window and map-consistency checks.

A saved percentage is not proof of complete physical coverage. A Dock command is not proof of successful docking. Alerts and human intervention remain part of the operating model.

## How it works

The scheduler chooses eligible work. An owner script records the active area and job token; progress observers save a guarded checkpoint. Completion checks advance the queue. Recovery and return routines consult the same ownership state before acting. Map identifiers and route settings are included in checkpoint identity so an old checkpoint cannot silently be applied to a changed route.

```mermaid
flowchart TD
    S[Eligible schedule] --> G{Safety and ownership gates}
    G -->|Pass| M[Owned mowing job]
    G -->|Hold| D[Deferred work]
    M --> P[Save guarded checkpoint]
    P -->|Low battery| C[Return and charge]
    C -->|Target reached and gates pass| M
    P -->|Recoverable interruption| R[Bounded recovery]
    R -->|Safe continuation| M
    R -->|Budget exhausted| N[Operator notice]
    P -->|Verified completion| Q[Next eligible area or finish]
    Q -->|Eligible handoff| G
```

The source contains 34 configurations (26 automations and 8 scripts), 67 helper definitions and 43 required local bindings. A local compiler replaces binding tokens with your installation's entity IDs, map hashes and device ID, then emits a Home Assistant package. Exhausted-recovery notices use Home Assistant persistent notifications; other operator alerts use a locally bound notification action. The compiler also normalizes empty selectors so Home Assistant package merging preserves them. Local settings and generated output belong outside version control.

Starts and resumes are initially disarmed: the package enable helper starts off, manual hold starts on, and unset not-before dates block dispatch until explicitly configured. Automations load enabled on first install and restore their enabled state thereafter. Dock-only protective automations remain available when the motion gate is off, including after a restart. Install with the mower safely parked and follow commissioning before arming motion.

## Get started

1. Read [Setup and commissioning](docs/SETUP.md), including the dependency contract and persistent-state warning.
2. Prepare private local bindings and generate the package.
3. Validate the generated package on your Home Assistant installation with dispatch disabled.
4. Commission during ordinary, supervised mowing and record evidence using the [validation checklist](docs/VALIDATION.md).

## Scope and limitations

The reference topology has five logical zones backed by six native areas, a seasonal grouped schedule, and fixed route profiles. Adapting a different topology requires source changes as well as bindings. Command parameters such as blade height, speed and collection mode are fixed reference values that can override app settings; review the setup guide's fixed-behavior table for model compatibility. Scheduling windows, seasonal assumptions, battery thresholds and recovery classifications must fit your mower, integration and property.

The reviewed public package passed 65 synthetic tests and isolated Home Assistant Core 2026.10.2 configuration validation. Those checks contacted no live instance or devices and do not certify physical behavior on another installation. See the reproducible commands in the validation guide. The extra 30-second position-telemetry recovery grace still needs confirmation during a naturally occurring event. Charger-free handoff, delayed scheduled-launch telemetry, uninterrupted recovery and sustained docking should all be treated as commissioning checks, not guaranteed features.

## Contributing and privacy

Useful contributions include anonymized failure cases, integration compatibility reports, focused tests and clearer setup instructions. Share the package version, integration version, relevant state transitions and expected/actual behavior. Do not attach raw traces, maps, backups or generated packages to public issues: they can contain coordinates, household entities and device identifiers. Reproduce with synthetic data or redact and inspect every field first. If private reporting is unavailable, omit sensitive details rather than posting them publicly.

Licensed under [MIT](LICENSE). This is a community project and is not affiliated with Mammotion or Home Assistant.
