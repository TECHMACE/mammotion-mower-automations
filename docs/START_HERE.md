# Start here: your Mammotion mower, with a plan

Let the mower mow. You have other things to do.

Mammotion Mower Coordinator helps Home Assistant decide **what to mow, when to continue, when to charge and when to ask for help**. You choose your areas, cutting directions, schedule and notifications. It remembers unfinished work, can move straight to the next eligible area, and attempts bounded recovery when fresh reports show a recoverable interruption.

The everyday setup uses Home Assistant screens. No YAML editing or copying someone else's lawn settings. Start with the basics; advanced weather, seasonal groups and recharge options can wait.

**Release:** `v0.2.0-alpha.2`. This is a community alpha for Mammotion mowers. Software and simulated mowing tests passed; each owner still needs a supervised first run. It is available as a HACS **custom repository**. [Default catalog submission #12760](https://github.com/hacs/default/pull/12760) is awaiting maintainer review; the custom-repository steps below still apply. The separate Mammotion-HA connection also needs to be installed.

## The short version

Already have HACS and your Mammotion mower working in HA? Jump to [install the coordinator](#3-install-mammotion-mower-coordinator).

1. Install HACS, the community integration manager.
2. Connect the mower using Mammotion-HA.
3. Download Mammotion Mower Coordinator through HACS.
4. Follow the setup wizard and send yourself a test notification.
5. Check readiness, then supervise the first ordinary mowing run.

Downloading an integration and adding it to HA are two separate steps. HACS downloads the files; **Settings → Devices & services → Add integration** starts configuration.

## Before you start

- Home Assistant **2026.10.4 or newer**; this alpha was tested on 2026.10.4. Check your version and installation type under **Settings → System → Repairs → ⋮ → System information**.
- A Mammotion mower already mapped and working in the Mammotion app.
- An administrator login for HA and a GitHub account for HACS.
- A current HA backup. Keep the mower parked while setting this up.

There are two mower integrations here. **Mammotion-HA** connects to the device. **Mammotion Mower Coordinator** plans and supervises the work using that connection. You need both.

## 1. Get HACS installed

Already see **HACS** in your HA sidebar? Skip to step 2.

These steps cover the standalone HACS integration on HA 2026.10. The [official HACS guide](https://www.hacs.xyz/docs/use/download/download/) has version-specific instructions, including the newer Marketplace path. Follow the version you actually run.

### Home Assistant OS, including HA Green

1. Open **Settings → Apps → Install app**. Older interfaces call these **Add-ons → Add-on store**.
2. Open the store's **⋮ → Repositories** and add `https://github.com/hacs/addons`.
3. Find **Get HACS**, install it and start it.
4. Open its **Log** tab and complete the instructions shown there.
5. Restart Home Assistant when directed.

### Home Assistant Container / Docker

Use the Container tab in the [official download instructions](https://www.hacs.xyz/docs/use/download/download/). It explains how to open a shell inside your HA container and run the HACS installer. Container installations do not have the HA OS app store. Restart the HA container afterward.

### Finish connecting HACS

1. Open **Settings → Devices & services → Add integration**, search for **HACS** and select it.
2. Review its acknowledgements. Follow the GitHub authorization link, sign in, enter the displayed device code and authorize HACS.
3. Return to HA and finish setup. Open **HACS** from the sidebar.

If HACS does not appear in Add integration, hard-refresh the browser after restarting HA. The [official HACS setup guide](https://www.hacs.xyz/docs/use/configuration/basic/) has screenshots. A GitHub device code belongs in that authorization screen, not in a public issue.

## 2. Connect your Mammotion mower

Skip this if HA already shows your mower, battery, activity and native areas correctly.

1. Open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/mikey0000/Mammotion-HA` with type **Integration**.
3. Search HACS for **Mammotion**, download it, then restart HA.
4. Open **Settings → Devices & services → Add integration → Mammotion** and follow its connection flow.
5. Confirm the mower and its areas appear, and that battery, current Self check, blade usage, tracker, mileage, RTK and map-sync reports are available.

Follow [Mammotion-HA's installation and account guidance](https://github.com/mikey0000/Mammotion-HA#installation-). Its Wi-Fi guidance calls for a separate account with the mower shared to it, to avoid logging the app out. The coordinator does not ask for your Mammotion password.

Our adapter was developed against **Mammotion-HA 0.6.19-beta4 / PyMammotion 0.10.11**. A different version/model may need compatibility work. Readiness checks block unsupported or incomplete map data. Do not force a pass by substituting unrelated sensors.

## 3. Install Mammotion Mower Coordinator

[Open this repository in your HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=TECHMACE&repository=mammotion-mower-automations&category=Integration), or add it manually:

1. Open **HACS → ⋮ → Custom repositories**.
2. Paste `https://github.com/TECHMACE/mammotion-mower-automations`.
3. Choose **Integration**, then **Add**.
4. Search for **Mammotion Mower Coordinator** and open it.
5. Choose **Download → Need a different version?** and select release **v0.2.0-alpha.2**. If already downloaded, use **⋮ → Redownload → Need a different version?**. Older HACS versions may instead offer **Show beta versions**. Do not choose `v0.1.0-alpha.1`: that is the older YAML reference.
6. Restart HA.
7. Open **Settings → Devices & services → Add integration → Mammotion Mower Coordinator**.

The repository menu and labels can vary by HACS version. The [custom-repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/) and [version-selection guide](https://www.hacs.xyz/docs/use/repositories/dashboard/) show the current screens. If the expected version is missing, refresh repository information; use the release link below to confirm it exists before proceeding.

Manual installation is also available: download the component ZIP from [the alpha release](https://github.com/TECHMACE/mammotion-mower-automations/releases/tag/v0.2.0-alpha.2), extract it into your HA configuration folder, and verify `custom_components/mower_coordinator/manifest.json` exists. Restart, then add the integration. The ZIP is not a HA backup.

## 4. Walk through the wizard

| Screen | What you choose |
| --- | --- |
| Mower and sensors | Your mower and the suggested matching sensors. Check the suggestions. Recovery needs fresh tracker, mileage and fixed RTK reports. |
| Areas | Which native areas belong together, a friendly name, directions and cutting settings. Start with one small area. |
| Rules | Working hours, battery limits, recovery and direct handoff. Recovery/handoff policies default on; the mower is still disarmed. |
| Advanced settings | Optional calendars, weather and charging refinements. Skip these initially if you do not need them. |
| Notifications | Where messages go, which events you want and quiet hours. |
| Review | Check the choices and finish. Setup does not launch the mower. |

Select a person whose presence HA can track. For property safety permission, use a suitable existing binary sensor or create **Settings → Devices & services → Helpers → Create helper → Toggle**, named something like **Lawn clear to mow**. Leave it off until you inspect the lawn. A manual toggle is permission, not an obstacle detector.

For phone alerts, first connect the Home Assistant Companion app and allow notifications on the phone. Choose its available notify destination in the wizard; legacy `notify.mobile_app_…` actions are also supported. With no push target, notices stay in HA's persistent notifications.

The [full settings guide](INTEGRATION.md) explains every policy and sensor requirement. You can revisit them through the integration's **Configure/Options** button.

## 5. Test setup, then let it mow

On the coordinator's device page:

1. Keep **Automatic control off** and **Hold new work on**.
2. Press **Check readiness**. Read **Explanation** and fix failed checks.
3. Press **Send test notification**. Confirm it actually arrived, then press **Confirm test notification received**.
4. Disable competing mower schedules/controllers. Confirm setup using **Confirm setup and competing schedules off**.
5. During suitable weather and working hours, inspect the property and turn on its safety permission. Release **Hold new work**, then enable **Automatic control** for a supervised run.
6. Watch launch, cutting, completion, return and sustained charging separately. Do not create a trap just to test recovery.

**Automatic control off** blocks all coordinator commands. **Hold new work** blocks new mowing and resumes while allowing protective returns for owned work when control is armed. A restart or options change disarms the coordinator again; inspect it before rearming.

The device page tells you what it is doing and why it is waiting. Saved progress and remaining areas show unfinished work. Recovery details show used resume and return attempts. A charging flag alone is not enough to resume: contact must stay established and battery gain must be observed, or the battery must already be full.

## If something gets stuck during setup

| What you see | What to check |
| --- | --- |
| HACS cannot add the repository | Use the repository URL above, type Integration, and check the HA minimum version. |
| Coordinator missing from Add integration | Check the downloaded version, restart HA and hard-refresh your browser. |
| No mower or native areas offered | Finish Mammotion-HA first. Areas must belong to that mower and have valid map hashes. |
| Recovery readiness failed | Enable/select the required device sensors and wait for fresh telemetry and fixed RTK. |
| Notification test did not arrive | Check the destination and phone permissions. Do not confirm receipt until you see it. |
| It is waiting instead of mowing | Read Explanation: rain, weather, battery, presence, safety permission, calendar or Hold may be doing its job. |
| Saved work is quarantined | The map or cutting profile changed. Inspect it; do not reuse an old checkpoint on a new route. |

For updates, back up HA, read the release notes, update in HACS, restart and repeat readiness/notification checks. Report bugs with versions and a small synthetic example; never upload raw maps, credentials or unreviewed traces.

Fork it. Make it yours. Spread the love. The [MIT license](../LICENSE) lets you modify and redistribute it; keep the license notice with your copy.
