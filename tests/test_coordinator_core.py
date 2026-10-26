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
        decision = sim.tick(121, battery=95)
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
        self.assertEqual(kinds(sim.tick(121)), ["start"])
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
            sim.tick(130, mower_state="paused", working=False, moving=False, recoverable=True, error="channel")
            sim.tick(90)
            decision = sim.tick(61)
            self.assertEqual(kinds(decision), ["resume"])
            self.assertEqual(sim.state.retries, index + 1)
            sim.cut(21 + index, error=None)
            self.assertEqual(sim.state.retries, index + 1)
        self.assertEqual(kinds(sim.tick(130, mower_state="paused", working=False, moving=False, recoverable=True, error="channel")), ["notify"])
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
            sim.tick(130, mower_state="paused", moving=False, recoverable=True, error="channel")
            sim.tick(90)
            decision = sim.tick(61)
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

    def stopped(self, sim, **changes):
        return sim.tick(130,mower_state="paused",working=False,moving=False,recoverable=True,error="channel",**changes)

    def observe_recovery(self, sim):
        sim.tick(90)
        return sim.tick(61)

    def test_delayed_motion_cancels_recovery_candidate_without_budget(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(35)
        self.stopped(sim)
        self.assertEqual(kinds(sim.tick(90)),[])
        sim.tick(40,moving=True)
        sim.tick(20,moving=False)
        self.assertEqual(sim.state.retries,0)
        self.assertEqual(kinds(sim.tick(90)),[])
        self.assertEqual(kinds(sim.tick(61)),["resume"])
        self.assertEqual(sim.state.checkpoint,35)

    def test_motion_proof_must_postdate_candidate_and_be_fresh(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut()
        old=sim.now.timestamp()
        self.stopped(sim,motion_timestamp=old)
        self.assertEqual(kinds(self.observe_recovery(sim)),[])
        self.assertEqual(sim.state.retries,0)
        self.assertEqual(kinds(sim.tick(motion_timestamp=sim.now.timestamp())),["resume"])

    def test_restart_and_telemetry_gap_restart_observation_not_budget(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut();self.stopped(sim)
        sim.state.retries=1
        sim.state=core.reconcile_restart(sim.state)
        self.assertEqual(kinds(sim.tick(100)),[])
        self.assertEqual(sim.state.retries,1)
        self.assertEqual(kinds(sim.tick(200)),[])
        self.assertEqual(kinds(self.observe_recovery(sim)),["resume"])
        self.assertEqual(sim.state.retries,2)

    def test_native_resume_failure_docks_then_restarts_exact_checkpoint(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(43);profile=dict(sim.state.frozen_profile)
        self.stopped(sim)
        self.assertEqual(kinds(self.observe_recovery(sim)),["resume"])
        sim.tick(121)
        self.assertEqual(kinds(self.observe_recovery(sim)),["dock"])
        self.assertEqual(sim.state.return_retries,1)
        sim.tick(20,mower_state="docked",charging=True,battery=60,error=None,recoverable=False)
        sim.tick(90,battery=85)
        decision=sim.tick(31,battery=95,ready=True)
        self.assertEqual(kinds(decision),["start"])
        self.assertEqual(decision.intents[0].data["start_progress"],43)
        self.assertEqual(decision.intents[0].data["profile"],profile)
        self.assertEqual(sim.state.queue,["one","two"])

    def test_ready_recovery_uses_frozen_route_not_native_resume(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(47)
        self.stopped(sim,can_resume=False,ready=True)
        decision=self.observe_recovery(sim)
        self.assertEqual(kinds(decision),["start"])
        self.assertTrue(decision.intents[0].data["recovery"])
        self.assertEqual(decision.intents[0].data["start_progress"],47)

    def test_handoff_cancels_once_waits_ready_then_starts(self):
        sim=Scenario(allow_handoff=True);sim.launch();sim.cut();sim.finish()
        self.assertEqual(kinds(sim.tick(ready=False)),["cancel"])
        for _ in range(4):self.assertEqual(kinds(sim.tick(10,ready=False)),[])
        decision=sim.tick(ready=True)
        self.assertEqual(kinds(decision),["start"])
        self.assertEqual(decision.intents[0].data["zone_id"],"two")
        self.assertEqual(sim.state.completed_dates["one"],sim.now.date().isoformat())

    def test_charged_checkpoint_cancel_ready_does_not_require_another_charge(self):
        sim=Scenario();sim.launch();sim.cut(50,battery=25)
        sim.tick(20,mower_state="docked",charging=True,working=False,moving=False,battery=60,ready=False)
        sim.tick(90,battery=95)
        self.assertEqual(kinds(sim.tick(31)),["cancel"])
        decision=sim.tick(ready=True)
        self.assertEqual(kinds(decision),["start"])
        self.assertEqual(decision.intents[0].data["start_progress"],50)

    def test_handoff_cancel_timeout_preserves_queue_and_never_replays(self):
        sim=Scenario(allow_handoff=True);sim.launch();sim.cut();sim.finish()
        sim.tick(ready=False)
        self.assertEqual(kinds(sim.tick(121)),["notify"])
        self.assertEqual(kinds(sim.tick(121)),[])
        self.assertEqual(sim.state.queue,["two"])

    def test_hold_or_weather_at_handoff_returns_instead_of_starting(self):
        for changes in ({"hold":True},{"rain":True},{"home":False}):
            sim=Scenario(allow_handoff=True);sim.launch();sim.cut();sim.finish()
            self.assertEqual(kinds(sim.tick(**changes)),["dock"])
            self.assertEqual(sim.state.queue,["two"])

    def test_late_cutting_after_dock_does_not_duplicate_dock(self):
        sim=Scenario();sim.launch();sim.cut(40,battery=25)
        self.assertEqual(kinds(sim.cut(41,battery=24)),[])
        self.assertEqual(sim.state.pending_command,"dock")

    def test_contact_retry_is_once_only_and_manual_hold_cancels(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(42,battery=25)
        sim.tick(121,mower_state="docked",charging=False,working=False,moving=False)
        self.assertEqual(kinds(self.observe_recovery(sim)),["dock"])
        self.assertTrue(sim.state.contact_retry_used)
        self.assertEqual(kinds(sim.tick(121)),["notify"])
        self.assertNotIn("dock",kinds(sim.tick(121)))
        self.assertEqual(sim.state.checkpoint,42)
        sim2=Scenario(auto_recovery=True);sim2.launch();sim2.cut(42,battery=25)
        self.assertEqual(kinds(sim2.tick(121,mower_state="docked",charging=False,working=False,moving=False,hold=True)),[])
        self.assertFalse(sim2.state.contact_retry_used)

    def test_slow_charge_does_not_resume_and_reports_attention(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(40,battery=25)
        sim.tick(10,mower_state="docked",charging=True,working=False,moving=False,battery=95)
        self.assertNotIn("start",kinds(sim.tick(121)))
        self.assertEqual(kinds(sim.tick(1200)),["notify"])
        self.assertEqual(sim.state.attention_code,"slow_charging")
        self.assertEqual(sim.state.checkpoint,40)

    def test_excluded_day_and_season_block_launch_resume_handoff(self):
        sim=Scenario(excluded_dates=("2026-10-26",));self.assertEqual(kinds(sim.launch()),[])
        sim=Scenario(season_months=(5,6));self.assertEqual(kinds(sim.launch()),[])
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut()
        sim.settings=replace(sim.settings,excluded_dates=("2026-10-26",))
        self.assertEqual(kinds(self.stopped(sim)),["dock"])
        sim=Scenario(allow_handoff=True);sim.launch();sim.cut();sim.finish()
        sim.settings=replace(sim.settings,season_months=(5,6))
        self.assertEqual(kinds(sim.tick()),["dock"])

    def test_group_date_and_seasonal_interval_queue_eligibility(self):
        sim=Scenario(eligible_groups=("a",))
        one=replace(sim.settings.zones[0],group="b")
        two=replace(sim.settings.zones[1],group="a",not_before="2026-10-27")
        sim.settings=replace(sim.settings,zones=(one,two))
        self.assertEqual(kinds(sim.launch()),[])
        two=replace(two,not_before=None,seasonal_intervals={"10":7})
        sim.settings=replace(sim.settings,zones=(one,two))
        sim.state.completed_dates["two"]="2026-10-22"
        self.assertEqual(kinds(sim.tick()),[])
        sim.state.completed_dates["two"]="2026-10-18"
        self.assertEqual(kinds(sim.tick()),["start"])
        self.assertEqual(sim.state.active_zone,"two")

    def test_stationary_zone_deadline_returns_with_checkpoint(self):
        sim=Scenario(auto_recovery=True);sim.settings=replace(sim.settings,zones=(replace(sim.settings.zones[0],stationary_return_seconds=60),sim.settings.zones[1]))
        sim.launch();sim.cut(35)
        sim.tick(5,mower_state="paused",working=False,moving=False,recoverable=True)
        self.assertEqual(kinds(sim.tick(61)),["dock"])
        self.assertEqual(sim.state.checkpoint,35)


    def test_group_anchor_triggers_followers_even_before_their_own_interval(self):
        sim=Scenario()
        anchor=replace(sim.settings.zones[0],group="front",group_anchor=True)
        follower=replace(sim.settings.zones[1],group="front",interval_days=14)
        sim.settings=replace(sim.settings,zones=(anchor,follower))
        sim.state.completed_dates={"one":"2026-10-22","two":"2026-10-25"}
        planned=core.new_plan(sim.settings,sim.state,sim.now)
        self.assertEqual(planned.queue,["one","two"])
        sim.state.completed_dates["one"]="2026-10-25"
        sim.state.completed_dates["two"]="2026-09-01"
        self.assertEqual(core.new_plan(sim.settings,sim.state,sim.now).queue,[])

    def test_group_anchor_never_restarts_today_completed_follower(self):
        sim=Scenario()
        sim.settings=replace(sim.settings,zones=(replace(sim.settings.zones[0],group="g",group_anchor=True),replace(sim.settings.zones[1],group="g")))
        sim.state.completed_dates["two"]="2026-10-26"
        self.assertEqual(core.new_plan(sim.settings,sim.state,sim.now).queue,["one"])
        sim.settings=replace(sim.settings,zones=(replace(sim.settings.zones[0],not_before="2026-10-27"),sim.settings.zones[1]))
        sim.state.completed_dates.clear()
        self.assertEqual(core.new_plan(sim.settings,sim.state,sim.now).queue,[])

    def test_any_due_anchor_can_enable_group_with_multiple_anchors(self):
        sim=Scenario()
        zones=(replace(sim.settings.zones[0],group="g",group_anchor=True),replace(sim.settings.zones[1],group="g",group_anchor=True),core.Zone("third","Follower",("33",),group="g"))
        sim.settings=replace(sim.settings,zones=zones)
        sim.state.completed_dates={"one":"2026-10-25","two":"2026-10-20","third":"2026-10-25"}
        planned=core.new_plan(sim.settings,sim.state,sim.now)
        self.assertEqual(set(planned.queue),{"one","two","third"})
        self.assertEqual(planned.queue[0],"two")

    def test_overdue_first_with_stable_config_order_and_existing_queue_retained(self):
        sim=Scenario()
        sim.state.completed_dates={"one":"2026-10-21","two":"2026-10-19"}
        self.assertEqual(core.new_plan(sim.settings,sim.state,sim.now).queue,["two","one"])
        sim.state.completed_dates["one"]="2026-10-19"
        self.assertEqual(core.new_plan(sim.settings,sim.state,sim.now).queue,["one","two"])
        sim.state.queue=["two"]
        self.assertEqual(core.new_plan(sim.settings,sim.state,sim.now).queue,["two","one"])

    def test_rest_days_apply_only_after_all_queued_work_verified_complete(self):
        sim=Scenario(rest_days_between_plans=1,allow_handoff=True)
        sim.launch();sim.cut();sim.finish()
        self.assertIsNone(sim.state.last_plan_completed)
        sim.tick();sim.cut();sim.finish()
        self.assertEqual(sim.state.last_plan_completed,"2026-10-26")
        settings=replace(sim.settings,zones=tuple(replace(z,interval_days=1) for z in sim.settings.zones))
        tomorrow=sim.now+timedelta(days=1)
        self.assertEqual(core.new_plan(settings,sim.state,tomorrow).queue,[])
        self.assertEqual(core.new_plan(settings,sim.state,tomorrow+timedelta(days=1)).queue,["one","two"])
        restored=core.State.from_dict(sim.state.to_dict())
        self.assertEqual(restored.last_plan_completed,"2026-10-26")

    def test_rest_setting_never_abandons_unfinished_owned_checkpoint(self):
        sim=Scenario(rest_days_between_plans=7);sim.launch();sim.cut(60,battery=25)
        sim.state.last_plan_completed="2026-10-25"
        sim.tick(10,mower_state="docked",working=False,moving=False,charging=True,battery=60)
        decision=sim.tick(121,battery=95)
        self.assertEqual(kinds(decision),["start"])
        self.assertEqual(decision.intents[0].data["start_progress"],60)
        self.assertEqual(sim.state.queue,["one","two"])

    def test_schedule_rule_validation(self):
        with self.assertRaises(ValueError):core.Zone("a","A",("1",),group_anchor=True)
        with self.assertRaises(ValueError):Scenario(rest_days_between_plans=-1)
        with self.assertRaises(ValueError):Scenario(season_months=(13,))
        with self.assertRaises(ValueError):Scenario(excluded_dates=("next Tuesday",))


    def test_returning_label_with_stationary_channel_fault_retries_with_budget(self):
        sim=Scenario(auto_recovery=True,max_retries=2);sim.launch();sim.cut(45,battery=25)
        for attempt in range(2):
            sim.tick(121,mower_state="returning",working=False,moving=False,recoverable=True,error="channel")
            decision=self.observe_recovery(sim)
            self.assertEqual(kinds(decision),["cancel_return"])
            self.assertEqual(sim.state.pending_command,"cancel_return")
            self.assertEqual(kinds(sim.tick(5)),[])
            self.assertEqual(kinds(sim.tick(5,mower_state="paused",ready=False,can_resume=True)),["dock"])
            self.assertEqual(sim.state.return_retries,attempt+1)
            self.assertEqual(sim.state.pending_command,"dock")
            self.assertEqual(sim.state.checkpoint,45)
            sim.tick(10,mower_state="returning",moving=True)
        decision=sim.tick(121,moving=False)
        self.assertEqual(kinds(decision),["notify"])
        self.assertEqual(sim.state.attention_code,"return_exhausted")

    def test_returning_stall_late_motion_or_hold_prevents_retry(self):
        for changes in ({"moving":True},{"hold":True}):
            sim=Scenario(auto_recovery=True);sim.launch();sim.cut(45,battery=25)
            sim.tick(121,mower_state="returning",working=False,moving=False,recoverable=True)
            sim.tick(90)
            self.assertEqual(kinds(sim.tick(61,**changes)),[])
            self.assertEqual(sim.state.return_retries,0)

    def test_static_working_label_uses_dock_fallback_not_resume(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(51)
        sim.tick(130,mower_state="mowing",working=False,moving=False,recoverable=True,error="channel",ready=False,can_resume=False)
        decision=self.observe_recovery(sim)
        self.assertEqual(kinds(decision),["dock"])
        self.assertEqual(sim.state.retries,1)
        self.assertEqual(sim.state.checkpoint,51)
        self.assertEqual(sim.state.queue,["one","two"])
        self.assertEqual(sim.state.pending_command,"dock")
        self.assertNotIn("dock",kinds(sim.tick(10)))

    def test_static_working_label_without_verified_fault_never_recovers(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(51)
        sim.tick(130,mower_state="mowing",working=False,moving=False,recoverable=False)
        self.assertEqual(kinds(self.observe_recovery(sim)),[])
        self.assertEqual(sim.state.retries,0)

    def test_native_autonomous_return_is_observed_without_duplicate_dock(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(20)
        self.assertEqual(kinds(sim.tick(10,mower_state="returning",working=False,moving=True)),[])
        self.assertEqual(sim.state.pending_command,"dock")
        sim.tick(121,moving=False,recoverable=True,error="channel")
        self.assertEqual(kinds(self.observe_recovery(sim)),["cancel_return"])
        self.assertEqual(sim.state.return_retries,1)


    def test_stationary_deadline_uses_travel_not_spinning_blades(self):
        sim=Scenario(auto_recovery=True);sim.settings=replace(sim.settings,zones=(replace(sim.settings.zones[0],stationary_return_seconds=60),sim.settings.zones[1]))
        sim.launch();sim.cut(35,travel_moving=False)
        decision=sim.cut(36,travel_moving=False)
        self.assertEqual(kinds(decision),[])
        decision=sim.tick(51,working=True,moving=True,travel_moving=False,progress=37)
        self.assertEqual(kinds(decision),["dock"])
        self.assertEqual(sim.state.checkpoint,37)

    def test_stationary_deadline_needs_fresh_travel_samples(self):
        sim=Scenario(auto_recovery=True);sim.settings=replace(sim.settings,zones=(replace(sim.settings.zones[0],stationary_return_seconds=60),sim.settings.zones[1]))
        sim.launch();sim.cut(35,travel_moving=False,motion_timestamp=0)
        self.assertEqual(kinds(sim.tick(70)),[])
        self.assertEqual(sim.state.stationary_since,0)
        sim.tick(motion_timestamp=sim.now.timestamp())
        self.assertGreater(sim.state.stationary_since,0)
        self.assertEqual(kinds(sim.tick(61,motion_timestamp=0)),[])
        self.assertEqual(sim.state.stationary_since,0)

    def test_unowned_protection_is_opt_in_and_never_adopts_work(self):
        for enabled,protect in ((True,False),(False,True)):
            sim=Scenario(protect_unowned_work=protect)
            decision=sim.tick(mower_state="mowing",charging=False,working=True,moving=True,battery=20,enabled=enabled)
            self.assertEqual(kinds(decision),[])
            self.assertFalse(sim.state.unowned_guard)
        sim=Scenario(protect_unowned_work=True)
        decision=sim.tick(mower_state="mowing",charging=False,working=True,moving=True,battery=20)
        self.assertEqual(kinds(decision),["dock"])
        self.assertTrue(sim.state.unowned_guard)
        self.assertIsNone(sim.state.active_zone)
        self.assertIsNone(sim.state.job_token)
        self.assertEqual(sim.state.checkpoint,0)
        self.assertEqual(sim.state.queue,[])
        self.assertEqual(kinds(sim.tick(10)),[])

    def test_unowned_return_guard_survives_charge_and_restart_until_explicit_reset(self):
        sim=Scenario(protect_unowned_work=True)
        sim.tick(mower_state="mowing",charging=False,working=True,battery=20)
        sim.state=core.reconcile_restart(core.State.from_dict(sim.state.to_dict()))
        self.assertTrue(sim.state.unowned_guard)
        sim.tick(10,mower_state="docked",charging=True,working=False,moving=False,battery=30)
        self.assertEqual(kinds(sim.tick(121,battery=100)),[])
        for _ in range(3):self.assertNotIn("start",kinds(sim.tick(200)))
        self.assertEqual(sim.state.completed_dates,{})
        sim.state=core.reset_recovery(sim.state)
        self.assertFalse(sim.state.unowned_guard)
        self.assertEqual(kinds(sim.tick()),["start"])

    def test_unowned_guard_all_protective_conditions_and_safe_veto(self):
        for changes in ({"rain":True},{"home":False},{"battery":25},{"weather_ok":False}):
            sim=Scenario(protect_unowned_work=True,weather_required=True)
            self.assertEqual(kinds(sim.tick(mower_state="mowing",charging=False,**changes)),["dock"])
        sim=Scenario(protect_unowned_work=True)
        self.assertEqual(kinds(sim.tick(mower_state="mowing",charging=False,battery=20,safe=False)),["notify"])
        self.assertFalse(sim.state.unowned_guard)
        sim=Scenario(protect_unowned_work=True,excluded_dates=("2026-10-26",))
        self.assertEqual(kinds(sim.tick(mower_state="mowing",charging=False)),["dock"])

    def test_unowned_return_recovery_remains_bounded_without_adopting(self):
        sim=Scenario(protect_unowned_work=True,auto_recovery=True,max_retries=1)
        sim.tick(mower_state="mowing",charging=False,battery=20)
        sim.tick(121,mower_state="returning",working=False,moving=False,recoverable=True)
        self.assertEqual(kinds(self.observe_recovery(sim)),["cancel_return"])
        self.assertEqual(kinds(sim.tick(mower_state="paused",ready=False,can_resume=True)),["dock"])
        self.assertEqual(sim.state.return_retries,1)
        self.assertEqual(kinds(sim.tick(121,mower_state="returning")),["notify"])
        self.assertTrue(sim.state.unowned_guard)
        self.assertIsNone(sim.state.active_zone)
        self.assertEqual(sim.state.queue,[])

    def test_return_cancel_durable_timeout_and_restart_never_repeat_toggle(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(41,battery=25)
        sim.tick(121,mower_state="returning",working=False,moving=False,recoverable=True)
        self.assertEqual(kinds(self.observe_recovery(sim)),["cancel_return"])
        sim.state=core.reconcile_restart(core.State.from_dict(sim.state.to_dict()))
        self.assertEqual(sim.state.pending_command,"cancel_return")
        self.assertEqual(kinds(sim.tick(20)),[])
        self.assertEqual(kinds(sim.tick(110)),["notify"])
        self.assertEqual(sim.state.attention_code,"return_cancel_unconfirmed")
        self.assertEqual(kinds(sim.tick(200)),[])
        self.assertEqual(sim.state.return_retries,1)
        self.assertEqual(sim.state.checkpoint,41)

    def test_return_cancel_second_stage_needs_new_safe_ready_sample(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(41,battery=25)
        sim.tick(121,mower_state="returning",working=False,moving=False,recoverable=True)
        self.observe_recovery(sim)
        self.assertEqual(kinds(sim.tick(0,mower_state="paused",ready=True)),[])
        self.assertEqual(kinds(sim.tick(hold=True)),[])
        self.assertEqual(kinds(sim.tick(safe=False)),["notify"])
        self.assertEqual(kinds(sim.tick(safe=True)),["dock"])
        self.assertEqual(sim.state.return_retries,1)
        self.assertEqual(kinds(sim.tick()),[])

    def test_return_cancel_arrives_charger_race_sends_no_redock(self):
        sim=Scenario(auto_recovery=True);sim.launch();sim.cut(41,battery=25)
        sim.tick(121,mower_state="returning",working=False,moving=False,recoverable=True)
        self.observe_recovery(sim)
        self.assertEqual(kinds(sim.tick(mower_state="docked",charging=True,battery=50,recoverable=False)),[])
        self.assertEqual(kinds(sim.tick(60,battery=60)),[])
        self.assertEqual(sim.state.return_retries,1)
        self.assertEqual(sim.state.pending_command,"dock")


if __name__ == "__main__":
    unittest.main()
