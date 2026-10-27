"""Explicit adapter edge cases using synthetic state, storage and service doubles."""
import asyncio
import json
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
import test_coordinator_runtime as fixture

class EdgeAcceptance(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.RuntimeTests.asyncSetUp
    asyncTearDown = fixture.RuntimeTests.asyncTearDown

    async def test_concurrent_evaluations_dispatch_one_start(self):
        original = self.r.store.async_save
        async def yielding_save(data):
            await asyncio.sleep(0)
            await original(data)
        self.r.store.async_save = yielding_save
        await asyncio.gather(*(self.r.async_evaluate() for _ in range(20)))
        self.assertEqual(sum(s=='start_mow' for _,s,_ in self.hass.services.calls),1)

    async def test_storage_read_failure_blocks_dispatch(self):
        self.r.store.async_load=AsyncMock(side_effect=ValueError('synthetic corrupt storage'))
        await self.r.async_load()
        await self.r.async_evaluate()
        self.assertTrue(self.r.storage_error)
        self.assertEqual(self.hass.services.calls,[])

    async def test_storage_write_failure_disarms_before_dispatch(self):
        self.r.store.async_save=AsyncMock(side_effect=OSError('synthetic full disk'))
        with self.assertRaises(fixture.Error):await self.r.async_evaluate()
        self.assertTrue(self.r.storage_error)
        self.assertFalse(self.r.armed)
        self.assertEqual(self.hass.services.calls,[])
        blocked_state=self.r.state.to_dict()
        await self.r.async_evaluate()
        self.assertEqual(self.r.state.to_dict(),blocked_state)
        self.assertEqual(self.hass.services.calls,[])

    async def test_uncertain_service_failure_restart_does_not_replay(self):
        self.r.dispatch=AsyncMock(side_effect=TimeoutError('synthetic uncertain response'))
        await self.r.async_evaluate()
        self.assertEqual(self.r.dispatch.await_count,1)
        await self.r.async_load()
        for _ in range(10):await self.r.async_evaluate()
        self.assertEqual(self.r.dispatch.await_count,1)
        self.assertEqual(len(self.r.state.queue),1)

    async def test_ha_user_pause_sets_hold_without_resume(self):
        await fixture.RuntimeTests.own_job(self)
        self.r.armed=False
        callbacks=[]
        def track(hass,entities,callback):
            callbacks.append(callback)
            return lambda:None
        with patch.object(fixture.runtime,'async_track_state_change_event',side_effect=track):
            await self.r.async_start()
        self.r.armed=True
        state=types.SimpleNamespace(state='paused',context=types.SimpleNamespace(user_id='synthetic-user'))
        self.hass.states.put('lawn_mower.fake','paused',attrs={'map_revision':'fake-map-v1'})
        self.hass.states.put('sensor.activity','MODE_PAUSE')
        callbacks[0](types.SimpleNamespace(data={'entity_id':'lawn_mower.fake','new_state':state}))
        await asyncio.gather(*self.entry.tasks)
        self.assertTrue(self.r.hold)
        self.assertEqual(self.r.state.checkpoint,40)
        self.assertEqual(self.r.state.retries,0)
        self.assertFalse(any(s in {'start_mow','start_mowing'} for _,s,_ in self.hass.services.calls))

    async def test_stale_future_and_unavailable_reports_block_launch(self):
        for age,value in ((121,'100'),(-6,'100'),(0,'unavailable'),(0,'unknown')):
            with self.subTest(age=age,value=value):
                self.hass.states.put('sensor.battery',value,age=age)
                await self.r.async_evaluate()
                self.assertEqual(self.hass.services.calls,[])

    async def test_contradictory_mower_and_activity_do_not_launch(self):
        for mower,activity in (('docked','MODE_WORKING'),('mowing','MODE_READY'),('returning','MODE_READY')):
            with self.subTest(mower=mower,activity=activity):
                self.hass.states.put('lawn_mower.fake',mower,attrs={'map_revision':'fake-map-v1'})
                self.hass.states.put('sensor.activity',activity)
                await self.r.async_evaluate()
                self.assertFalse(any(s in {'start_mow','start_mowing'} for _,s,_ in self.hass.services.calls))

    async def test_known_yaml_check_does_not_claim_custom_controller_detection(self):
        key='no_known_controller_reported_on'
        for eid in ('input_boolean.mower_package_enabled','automation.mower_schedule'):
            self.hass.states.put(eid,'on')
            self.assertFalse(self.r.preflight()[key])
            self.hass.states.put(eid,'off')
        self.hass.states.put('automation.custom_garden_unstick','on')
        self.assertTrue(self.r.preflight()[key])
        self.r.armed=False
        self.r.evidence['setup_confirmed']=False
        with self.assertRaises(fixture.Error):await self.r.async_set_control('armed',True)
        self.assertFalse(self.r.armed)
        self.assertIn('not detected',fixture.runtime.CONTROLLER_CHECK_SCOPE)

    async def test_guidance_matches_recovery_defaults_and_detection_scope(self):
        root=Path(__file__).resolve().parents[1]/'custom_components/mower_coordinator'
        strings=json.loads((root/'strings.json').read_text())
        self.assertEqual(strings,json.loads((root/'translations/en.json').read_text()))
        for section in ('config','options'):
            rules=strings[section]['step']['rules']['description']
            self.assertNotIn('remain disabled in this alpha',rules)
            self.assertIn('selected by default',rules)
            self.assertIn('cannot detect custom or renamed',strings[section]['step']['review']['description'])

    async def test_queued_disarm_precedes_queued_evaluation(self):
        await self.r._lock.acquire()
        disarm=asyncio.create_task(self.r.async_set_control('armed',False))
        await asyncio.sleep(0)
        evaluation=asyncio.create_task(self.r.async_evaluate())
        await asyncio.sleep(0)
        self.r._lock.release()
        await asyncio.gather(disarm,evaluation)
        self.assertFalse(self.r.armed)
        self.assertEqual(self.hass.services.calls,[])

    async def test_corrupt_persisted_version_blocks_fresh_runtime(self):
        runtime=fixture.runtime.MowerRuntime(self.hass,self.entry)
        data=runtime.state.to_dict();data['version']=999
        runtime.store.data={'state':data}
        await runtime.async_load()
        await runtime.async_evaluate()
        self.assertTrue(runtime.storage_error)
        self.assertFalse(runtime.armed)
        self.assertTrue(runtime.hold)
        self.assertEqual(self.hass.services.calls,[])

    async def test_controller_predicate_exact_states_and_prefixes(self):
        key='no_known_controller_reported_on'
        for eid,matched in (('input_boolean.mower_package_enabled',True),('automation.mower_x',True),('automation.mowerx',False),('automation.my_mower_x',False),('automation.renamed_garden',False)):
            for state in (None,'off','unknown','unavailable','on'):
                with self.subTest(entity=eid,state=state):
                    if state is None:self.hass.states.items.pop(eid,None)
                    else:self.hass.states.put(eid,state)
                    self.assertEqual(self.r.preflight()[key],not(matched and state=='on'))
            self.hass.states.items.pop(eid,None)

    async def test_known_controller_enabled_after_setup_blocks_arm_and_evaluation(self):
        self.r.armed=False
        self.hass.states.put('automation.mower_x','on')
        with self.assertRaises(fixture.Error):await self.r.async_set_control('armed',True)
        self.r.armed=True
        await self.r.async_evaluate()
        self.assertEqual(self.hass.services.calls,[])
        self.assertIn('no known controller reported on',self.r.reason)
