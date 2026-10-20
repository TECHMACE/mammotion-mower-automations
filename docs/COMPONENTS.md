# Component inventory

Generated from the public source: 26 automations, 8 scripts and 67 helper definitions. Names are internal identifiers; external bindings stay local. The unused legacy start script is not included.

| Kind | Component |
| --- | --- |
| automation | `automation.mower_smart_auto_unstick` |
| automation | `automation.mower_extended_stall_watchdog` |
| automation | `automation.mower_obstruction_dock` |
| automation | `automation.mower_departure_safety` |
| automation | `automation.mower_working_pause_recovery` |
| automation | `automation.mower_guarded_progress_checkpoint` |
| automation | `automation.mower_seasonal_interval_schedule` |
| automation | `automation.mower_owner_completion_latch` |
| automation | `automation.mower_owner_reconcile` |
| automation | `automation.mower_start_rain_hold` |
| automation | `automation.mower_release_rain_hold` |
| automation | `automation.mower_light_rain_safety` |
| automation | `automation.mower_rain_tolerance_cleanup` |
| automation | `automation.mower_prove_dry_launch_before_light_rain_tolerance` |
| automation | `automation.mower_unmapped_error_journal` |
| automation | `automation.mower_weather_freshness_and_outlook` |
| automation | `automation.mower_orphan_battery_reserve` |
| automation | `automation.mower_roadside_orphan_return` |
| automation | `automation.mower_roadside_silent_stall` |
| automation | `automation.mower_roadside_stationary_tracker` |
| automation | `automation.mower_owned_telemetry_refresh` |
| automation | `automation.mower_idle_but_not_charging` |
| automation | `automation.mower_clear_recovered_stuck_warning` |
| automation | `automation.mower_owned_pause_alert` |
| automation | `automation.mower_self_check_intervention` |
| automation | `automation.mower_consecutive_dispatch` |
| script | `script.mower_start_fresh_area` |
| script | `script.mower_run_owned_area` |
| script | `script.mower_consecutive_handoff` |
| script | `script.mower_dock_cancel_restart` |
| script | `script.mower_run_due_plan` |
| script | `script.mower_finalize_owned_area` |
| script | `script.mower_resume_target_calculator` |
| script | `script.mower_exhausted_recovery_alert` |

## Helpers

| Kind | Helper |
| --- | --- |
| input_boolean | `input_boolean.mower_batch_cut_complete` |
| input_boolean | `input_boolean.mower_carryover_active` |
| input_boolean | `input_boolean.mower_light_rain_tolerance` |
| input_boolean | `input_boolean.mower_manual_hold` |
| input_boolean | `input_boolean.mower_near_term_weather_risk` |
| input_boolean | `input_boolean.mower_owner_cut_proved` |
| input_boolean | `input_boolean.mower_rain_hold_active` |
| input_boolean | `input_boolean.mower_rain_override_legacy_1` |
| input_boolean | `input_boolean.mower_roadside_return_due` |
| input_boolean | `input_boolean.mower_weather_sources_fresh` |
| input_datetime | `input_datetime.mower_zone_c_not_before` |
| input_datetime | `input_datetime.mower_owner_heartbeat` |
| input_datetime | `input_datetime.mower_zone_e_last_complete` |
| input_datetime | `input_datetime.mower_rain_release_after` |
| input_datetime | `input_datetime.mower_resume_date` |
| input_datetime | `input_datetime.mower_scheduling_not_before` |
| input_number | `input_number.mower_area_3_next_angle` |
| input_number | `input_number.mower_area_6_next_angle` |
| input_number | `input_number.mower_high_wind_limit` |
| input_number | `input_number.mower_intervention_free_batches` |
| input_number | `input_number.mower_owner_checkpoint` |
| input_number | `input_number.mower_owner_reconcile_attempts` |
| input_number | `input_number.mower_rain_hold_minutes` |
| input_number | `input_number.mower_recovery_attempts` |
| input_number | `input_number.mower_recovery_target_battery` |
| input_number | `input_number.mower_resume_progress` |
| input_number | `input_number.mower_roadside_stationary_limit_minutes` |
| input_number | `input_number.mower_segment_end_battery` |
| input_number | `input_number.mower_segment_end_blade_time` |
| input_number | `input_number.mower_segment_start_battery` |
| input_number | `input_number.mower_segment_start_blade_time` |
| input_number | `input_number.mower_segment_start_progress` |
| input_number | `input_number.mower_valid_burn_rate` |
| input_number | `input_number.mower_zone_fail_count` |
| input_select | `input_select.mower_active_area` |
| input_select | `input_select.mower_active_batch` |
| input_select | `input_select.mower_coordinator_state` |
| input_select | `input_select.mower_due_plan` |
| input_select | `input_select.mower_resume_area` |
| input_select | `input_select.mower_resume_batch` |
| input_text | `input_text.mower_area_attempt_dates` |
| input_text | `input_text.mower_area_map` |
| input_text | `input_text.mower_carryover_last_attempt_date` |
| input_text | `input_text.mower_checkpoint_map_identity` |
| input_text | `input_text.mower_dock_contact_recovery` |
| input_text | `input_text.mower_zone_c_last_complete_verified` |
| input_text | `input_text.mower_zone_d_last_complete_verified` |
| input_text | `input_text.mower_zone_a_last_complete_verified` |
| input_text | `input_text.mower_job_token` |
| input_text | `input_text.mower_last_pause_alert_key` |
| input_text | `input_text.mower_last_plan_date` |
| input_text | `input_text.mower_last_status_area` |
| input_text | `input_text.mower_last_trapped_recovery_key` |
| input_text | `input_text.mower_last_unmapped_error` |
| input_text | `input_text.mower_observed_cut_owner` |
| input_text | `input_text.mower_orphan_reserve_return_token` |
| input_text | `input_text.mower_pending_handoff` |
| input_text | `input_text.mower_planned_areas` |
| input_text | `input_text.mower_zone_e_last_complete_verified` |
| input_text | `input_text.mower_roadside_return_budget` |
| input_text | `input_text.mower_roadside_stationary_candidate` |
| input_text | `input_text.mower_route_signature` |
| input_text | `input_text.mower_schedule_rationale` |
| input_text | `input_text.mower_self_check_alert_episode` |
| input_text | `input_text.mower_zone_b_last_complete_verified` |
| input_number | `input_number.mower_auto_resume_budget_used` |
| input_boolean | `input_boolean.mower_zone_group_hold` |

The compiler adds `input_boolean.mower_package_enabled` as the global commissioning gate.

## Local binding catalog

Supply all 43 values in your private settings file. The purpose column describes each dependency; it is not a value to copy blindly.

| Key | Purpose |
| --- | --- |
| `BIND_027` | binary_sensor.mower_rain_detected |
| `BIND_028` | binary_sensor.local_rain |
| `BIND_029` | binary_sensor.mower_charging |
| `BIND_030` | button.mower_refresh_status |
| `BIND_031` | button.mower_cancel_current_task |
| `BIND_032` | device_tracker.mower_position |
| `BIND_043` | input_boolean.operator_vacation |
| `BIND_050` | input_number.outdoor_temperature_ema |
| `BIND_069` | input_select.seasonal_growth_mode |
| `BIND_070` | input_select.seasonal_growth_override |
| `BIND_102` | lawn_mower.mower |
| `BIND_103` | notify.operator_mobile |
| `BIND_104` | person.operator |
| `BIND_113` | select.mower_traversal_mode |
| `BIND_114` | select.mower_turnaround_mode |
| `BIND_115` | sensor.mower_self_check |
| `BIND_116` | sensor.mower_activity_mode |
| `BIND_117` | sensor.mower_battery |
| `BIND_118` | sensor.mower_blade_used_time |
| `BIND_119` | sensor.mower_connection |
| `BIND_120` | sensor.mower_device_position_type |
| `BIND_121` | sensor.mower_last_error |
| `BIND_122` | sensor.mower_last_error_code |
| `BIND_123` | sensor.mower_last_error_time |
| `BIND_124` | sensor.mower_progress |
| `BIND_125` | sensor.mower_rtk_position |
| `BIND_126` | sensor.mower_total_mileage |
| `BIND_127` | sensor.mower_work_area |
| `BIND_128` | sensor.weather_observation_time |
| `BIND_129` | sensor.wind_gust |
| `BIND_130` | sensor.wind_speed |
| `BIND_131` | switch.mower_rain_detection_mower_on_off |
| `BIND_132` | weather.primary |
| `BIND_133` | weather.secondary |
| `MAP_HASH_1` | Unique native area identifier 1 |
| `MAP_HASH_2` | Unique native area identifier 2 |
| `MAP_HASH_3` | Unique native area identifier 3 |
| `MAP_HASH_4` | Unique native area identifier 4 |
| `MAP_HASH_5` | Unique native area identifier 5 |
| `MAP_HASH_6` | Unique native area identifier 6 |
| `DEVICE_1` | Mower Home Assistant device registry ID |
| `NOTIFICATION_1` | Integration persistent warning notification ID (contains your mower identifier; keep local) |
| `NOTIFICATION_2` | Integration persistent warning notification ID (contains your mower identifier; keep local) |
