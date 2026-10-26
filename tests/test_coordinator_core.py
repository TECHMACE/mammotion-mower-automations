"""Event-sequence contract tests for the standalone coordinator policy."""
import importlib.util
from pathlib import Path
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

_PATH = Path(__file__).resolve().parents[1] / "custom_components/mower_coordinator/core.py"
_SPEC = importlib.util.spec_from_file_location("mower_policy_test", _PATH)
core = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = core
_SPEC.loader.exec_module(core)


class Scenario:
    def __init__(self, **settings):
        self.now = datetime(2026, 10, 26, 10, tzinfo=timezone.utc)
        self.settings = core.Settings(zones=(core.Zone("one", "First lawn", ("11",)), core.Zone("two", "Second lawn", ("22",))), **settings)
        self.state = core.State()
        self.obs = core.Observation(timestamp=self.now.timestamp(), mower_state="docked", battery=100, progress=0, charging=True, working=False, safe=True, home=True, rain=False, weather_ok=True, map_revision="map-1", area_ids=("11", "22"))

    def tick(self, seconds=1, enabled=True, hold=False, **changes):
        self.now += timedelta(seconds=seconds)
        self.obs = replace(self.obs, timestamp=self.now.timestamp(), **changes)
        decision = core.tick(self.settings, self.state, self.obs, self.now, enabled, hold)
        self.state = decision.state
        return decision

    def launch(self):
        self.tick()
        return self.tick(61)

    def cut(self, progress=20, **changes):
        return self.tick(10, mower_state="mowing", charging=False, working=True, moving=True, progress=progress, **changes)

    def finish(self):
        return self.tick(10, progress=100, working=False, moving=False, mower_state="idle", completed=True)


def kinds(decision):
    return [intent.kind for intent in decision.intents]


class CoreScenarioTests(unittest.TestCase):
    def test_delayed_launch_ack_never_duplicates_and_queue_is_preserved(self):
        sim = Scenario()
        self.assertEqual(kinds(sim.launch()), ["start"])
        for _ in range(10):
            self.assertNotIn("start", kinds(sim.tick(10)))
        self.assertEqual(kinds(sim.cut(1)), [])
        self.assertEqual(sim.state.phase, "mowing")
        self.assertEqual(sim.state.queue, ["one", "two"])

    def test_unconfirmed_start_keeps_checkpoint_queue_and_stays_blocked(self):
        sim = Scenario()
        sim.launch()
        self.assertEqual(kinds(sim.tick(130)), ["notify"])
        for _ in range(5):
            self.assertEqual(kinds(sim.tick(300)), [])
        self.assertEqual(sim.state.queue, ["one", "two"])
        self.assertEqual(sim.state.active_zone, "one")

    def test_low_battery_dock_charge_resume_preserves_frozen_profile(self):
        sim = Scenario()
        sim.launch()
        profile = sim.state.frozen_profile.copy()
        self.assertEqual(kinds(sim.cut(55, battery=25)), ["dock"])
        self.assertEqual(sim.state.checkpoint, 55)
        self.assertEqual(kinds(sim.tick(20, mower_state="returning", working=False)), [])
        self.assertEqual(kinds(sim.tick(30, mower_state="docked", charging=True, battery=30)), [])
        decision = sim.tick(90, battery=95)
        self.assertEqual(kinds(decision), ["start"])
        self.assertEqual(decision.intents[0].data["start_progress"], 55)
        self.assertEqual(decision.intents[0].data["profile"], profile)
        self.assertEqual(sim.state.queue, ["one", "two"])

    def test_new_charge_after_failed_launch_can_resume_but_same_charge_cannot(self):
        sim = Scenario()
        sim.launch()
        sim.tick(130)
        sim.tick(5, charging=False, mower_state="idle")
        sim.tick(5, charging=True, mower_state="docked")
        self.assertEqual(kinds(sim.tick(61)), ["start"])
        sim.tick(130)
        self.assertNotIn("start", kinds(sim.tick(200)))

    def test_completion_advances_angle_once_and_handoffs_only_when_eligible(self):
        sim = Scenario(allow_handoff=True)
        sim.launch()
        sim.cut(30)
        self.assertEqual(kinds(sim.finish()), ["notify"])
        decision = sim.tick()
        self.assertEqual(kinds(decision), ["start"])
        self.assertEqual(decision.intents[0].data["zone_id"], "two")
        self.assertEqual(sim.state.angle_indices, {"one": 1})
        self.assertEqual(sim.state.queue, ["two"])
        self.assertNotIn("start", kinds(sim.tick()))

    def test_ineligible_handoff_docks_and_does_not_drop_next_area(self):
        sim = Scenario()
        sim.launch()
        sim.cut()
        sim.finish()
        self.assertEqual(kinds(sim.tick()), ["dock"])
        self.assertEqual(sim.state.queue, ["two"])
        self.assertNotIn("dock", kinds(sim.tick(1)))

    def test_completed_without_cutting_evidence_does_not_complete(self):
        sim = Scenario()
        sim.launch()
        sim.tick(progress=100, completed=True)
        self.assertEqual(sim.state.completed_dates, {})
        self.assertEqual(sim.state.queue, ["one", "two"])

    def test_progress_is_monotonic_across_zero_blips(self):
        sim = Scenario()
        sim.launch()
        sim.cut(55)
        sim.cut(0)
        self.assertEqual(sim.state.checkpoint, 55)

    def test_map_change_quarantines_without_losing_work(self):
        sim = Scenario()
        sim.launch()
        sim.cut(55)
        decision = sim.tick(map_revision="map-2")
        self.assertEqual(kinds(decision), ["notify"])
        self.assertEqual(sim.state.phase, "quarantined")
        self.assertEqual(sim.state.checkpoint, 55)
        self.assertEqual(sim.state.queue, ["one", "two"])
        self.assertNotIn("start", kinds(sim.tick()))

    def test_profile_change_quarantines_but_label_change_does_not(self):
        sim = Scenario()
        sim.launch()
        sim.cut()
        sim.settings = replace(sim.settings, zones=(replace(sim.settings.zones[0], name="Renamed lawn"), sim.settings.zones[1]))
        self.assertEqual(sim.tick().state.phase, "mowing")
        sim.settings = replace(sim.settings, zones=(replace(sim.settings.zones[0], spacing_cm=12), sim.settings.zones[1]))
        self.assertEqual(sim.tick().state.phase, "quarantined")

    def test_recovery_budget_never_resets_on_movement_or_progress(self):
        sim = Scenario(auto_recovery=True)
        sim.launch()
        sim.cut()
        for index in range(3):
            decision = sim.tick(130, mower_state="paused", working=False, moving=False, recoverable=True, error="channel")
            self.assertEqual(kinds(decision), ["start"])
            self.assertEqual(sim.state.retries, index + 1)
            sim.cut(21 + index, error=None)
            self.assertEqual(sim.state.retries, index + 1)
        self.assertEqual(kinds(sim.tick(130, mower_state="paused", working=False, recoverable=True, error="channel")), ["notify"])
        self.assertEqual(sim.state.attention_code, "recovery_exhausted")
        self.assertEqual(sim.state.retries, 3)
        restored = core.State.from_dict(sim.state.to_dict())
        self.assertEqual(restored.retries, 3)
        self.assertEqual(core.reset_recovery(restored).retries, 0)
        self.assertEqual(restored.retries, 3)

    def test_return_recovery_is_bounded_even_after_movement(self):
        sim = Scenario(auto_recovery=True)
        sim.launch()
        sim.cut(50, battery=25)
        for index in range(3):
            sim.tick(20, mower_state="returning", working=False, moving=True)
            decision = sim.tick(130, mower_state="paused", moving=False, recoverable=True, error="channel")
            self.assertEqual(kinds(decision), ["dock"])
            self.assertEqual(sim.state.return_retries, index + 1)
        decision = sim.tick(130)
        self.assertNotIn("dock", kinds(decision))
        self.assertEqual(sim.state.attention_code, "return_exhausted")

    def test_restart_does_not_replay_uncertain_command(self):
        sim = Scenario()
        sim.launch()
        sim.state = core.reconcile_restart(core.State.from_dict(sim.state.to_dict()))
        self.assertNotIn("start", kinds(sim.tick(10)))
        sim.tick(130)
        self.assertNotIn("start", kinds(sim.tick(300)))
        self.assertEqual(sim.state.queue, ["one", "two"])

    def test_restart_adopts_only_previously_owned_fresh_cutting(self):
        sim = Scenario()
        sim.launch()
        sim.cut(50)
        sim.state = core.reconcile_restart(sim.state)
        self.assertEqual(sim.cut(51).state.phase, "mowing")
        self.assertEqual(sim.state.checkpoint, 51)
        self.assertEqual(sim.state.retries, 0)

    def test_no_unowned_job_adoption(self):
        sim = Scenario()
        decision = sim.cut(20)
        self.assertEqual(kinds(decision), [])
        self.assertIsNone(sim.state.active_zone)

    def test_protective_return_still_works_when_start_disarmed(self):
        sim = Scenario()
        sim.launch()
        sim.cut(20)
        self.assertEqual(kinds(sim.tick(enabled=False, hold=True, home=False)), ["dock"])

    def test_physical_safety_vetoes_return_and_recovery(self):
        sim = Scenario(auto_recovery=True)
        sim.launch()
        sim.cut()
        decision = sim.tick(safe=False, battery=10, home=False)
        self.assertEqual(kinds(decision), ["notify"])
        self.assertNotIn("dock", kinds(sim.tick(500)))

    def test_unknown_error_is_never_recovered(self):
        sim = Scenario(auto_recovery=True)
        sim.launch()
        sim.cut()
        decision = sim.tick(200, mower_state="paused", working=False, error="unrecognized", recoverable=False)
        self.assertEqual(kinds(decision), ["notify"])
        self.assertEqual(sim.state.retries, 0)

    def test_weather_none_is_optional_only_when_explicitly_disabled(self):
        sim = Scenario(weather_required=True)
        sim.tick(weather_ok=None)
        self.assertNotIn("start", kinds(sim.tick(61)))
        sim.settings = replace(sim.settings, weather_required=False)
        self.assertEqual(kinds(sim.tick()), ["start"])

    def test_missing_rain_sensor_blocks_until_restored(self):
        sim = Scenario()
        sim.tick(rain=None)
        self.assertNotIn("start", kinds(sim.tick(61)))
        self.assertEqual(kinds(sim.tick(rain=False)), ["start"])

    def test_window_and_weekday_limits(self):
        sim = Scenario()
        sim.now = sim.now.replace(hour=8)
        sim.tick()
        self.assertNotIn("start", kinds(sim.tick(61)))
        sim.now = sim.now.replace(hour=10)
        sim.settings = replace(sim.settings, weekdays=(1,))
        self.assertNotIn("start", kinds(sim.tick()))

    def test_window_end_returns_owned_mower(self):
        sim = Scenario()
        sim.launch()
        sim.cut()
        sim.now = sim.now.replace(hour=19)
        self.assertEqual(kinds(sim.tick()), ["dock"])

    def test_numeric_sensor_validation_and_future_stale_timestamps(self):
        for value in (float("nan"), float("inf"), -1, 101, "100", True):
            sim = Scenario()
            sim.tick()
            sim.now += timedelta(seconds=61)
            bad = replace(sim.obs, timestamp=sim.now.timestamp(), battery=value)
            self.assertNotIn("start", kinds(core.tick(sim.settings, sim.state, bad, sim.now, True, False)))
        for delta in (-121, 6, float("nan")):
            sim = Scenario()
            sim.tick()
            sim.now += timedelta(seconds=61)
            bad = replace(sim.obs, timestamp=sim.now.timestamp() + delta)
            self.assertNotIn("start", kinds(core.tick(sim.settings, sim.state, bad, sim.now, True, False)))

    def test_due_plan_never_restarts_completed_area_same_day(self):
        sim = Scenario(allow_handoff=True)
        sim.launch()
        sim.cut()
        sim.finish()
        sim.tick()
        sim.cut(20)
        sim.finish()
        sim.tick()
        sim.tick(30, mower_state="docked", charging=True)
        self.assertNotIn("start", kinds(sim.tick(300)))
        self.assertEqual(sim.state.queue, [])
        self.assertEqual(set(sim.state.completed_dates), {"one", "two"})

    def test_persistence_roundtrip_and_unknown_version_fail_closed(self):
        sim = Scenario()
        sim.launch()
        sim.cut(55)
        self.assertEqual(core.State.from_dict(sim.state.to_dict()), sim.state)
        data = sim.state.to_dict()
        data["version"] = 999
        with self.assertRaises(ValueError): core.State.from_dict(data)
        data = sim.state.to_dict()
        data["checkpoint"] = float("nan")
        with self.assertRaises(ValueError): core.State.from_dict(data)

    def test_input_state_never_mutated(self):
        sim = Scenario()
        original = sim.state.to_dict()
        sim.tick()
        self.assertEqual(original, core.State().to_dict())
        initial = sim.state
        saved = initial.to_dict()
        sim.tick(61)
        self.assertEqual(initial.to_dict(), saved)

    def test_protection_preempts_pending_start_acknowledgement(self):
        sim = Scenario()
        sim.launch()
        decision = sim.tick(10, mower_state="idle", charging=False, home=False)
        self.assertEqual(kinds(decision), ["dock"])
        self.assertEqual(sim.state.queue, ["one", "two"])

    def test_corrupt_frozen_profile_is_quarantined(self):
        sim = Scenario()
        sim.launch()
        sim.cut()
        sim.state.frozen_profile["angle"] = 45
        self.assertEqual(sim.tick().state.phase, "quarantined")

    def test_nonboolean_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            Scenario(auto_recovery="false")
        sim = Scenario()
        sim.tick(rain=0)
        self.assertNotIn("start", kinds(sim.tick(61)))

    def test_old_complete_percentage_requires_current_completion_evidence(self):
        sim = Scenario()
        sim.launch()
        sim.cut(55)
        sim.tick(progress=100,working=False,completed=False,mower_state="idle")
        self.assertEqual(sim.state.completed_dates,{})
        self.assertEqual(sim.state.checkpoint,55)

    def test_returning_forever_eventually_needs_attention_without_duplicate_dock(self):
        sim = Scenario()
        sim.launch()
        sim.cut(50,battery=25)
        decision=sim.tick(1300,mower_state="returning",working=False)
        self.assertEqual(kinds(decision),["notify"])
        self.assertEqual(sim.state.attention_code,"return_timeout")
        self.assertEqual(kinds(sim.tick(100)),[])

    def test_arbitrary_topology_and_invalid_overlap(self):
        zones = tuple(core.Zone(str(i), "Lawn " + str(i), (str(i + 10),), angles=(10, 80, 150)) for i in range(12))
        settings = core.Settings(zones)
        state = core.new_plan(settings, core.State(), datetime.now(timezone.utc))
        self.assertEqual(len(state.queue), 12)
        with self.assertRaises(ValueError): core.Settings((zones[0], replace(zones[1], area_ids=zones[0].area_ids)))
        with self.assertRaises(ValueError): core.Settings(zones, window_start="19:00", window_end="09:00")
        with self.assertRaises(ValueError): core.Settings(zones, max_retries=4)


if __name__ == "__main__":
    unittest.main()
