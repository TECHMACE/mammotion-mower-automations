# Mammotion Mower Coordinator for Home Assistant
## 0.2.0-alpha.1 preview

Let the mower mow. You have other things to do.

This is for **Mammotion mowers**, with Home Assistant helping keep the mowing plan together. Set up your areas, cutting directions, operating hours, battery limits, optional weather checks, and notifications through a setup wizard. Your lawn, your settings.

The idea is simple: keep track of the work, preserve unfinished progress, and explain what is happening. If it is waiting on charging, rain, an operating window, or a safety check, you should be able to see why.

Setup starts with control off. Walk through the checks, send yourself a test notification, and confirm it arrived before enabling control. No surprise test drive across the yard.

We built a separate Home Assistant lab with a fake mower to test launches, delayed updates, charging, saved progress, map changes, and notification failures. The working house system was not used as a test bench. [The validation notes](INTEGRATION_VALIDATION.md) explain exactly what passed.

**This is still an alpha.** The new integration needs supervised testing on real installations. Automatic obstruction recovery and moving straight into the next area without docking are not enabled in this version. The original YAML reference has more history; this new package still has to earn that confidence. A test passing does not mean the mower physically cut every strip or made good contact with its charger.

### Make it yours

Fork it, branch it, change it, and build something useful. Want different rules or a new feature? Have at it. The [MIT license](../LICENSE) lets you use, modify, share, and sell your version; keep its license and copyright notice. Sending improvements back is welcome, but it is not a requirement. Spread the love.

This is an independent community project, not an official Mammotion product. Start with the [setup guide](INTEGRATION.md). Preview installation currently uses the development branch or its ZIP; HACS installation follows an integration release or merge to the default branch.
