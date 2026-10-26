"""A charging flag without battery gain must not resume unfinished work."""
from exercise_recovery import prepare, assert_count
from scenario_client import Lab

def run():
    lab=Lab()
    try:
        prepare(lab)
        lab.fake(battery=25)
        lab.wait(lambda:len(lab.commands('dock'))==1,message='reserve return')
        lab.fake(mower='docked',activity='MODE_READY',charging=True,battery=40)
        lab.wait(lambda:lab.value('sensor.lab_coordinator_status')=='attention',145,'slow charging attention')
        assert_count(lab,'start_mow',1)
        assert_count(lab,'start_mowing',0)
        assert float(lab.value('sensor.lab_coordinator_saved_progress'))==35
        assert 'charg' in lab.value('sensor.lab_coordinator_explanation').lower()
        print('PASS: charging flag with no batterygain did not resume; attention retained35%checkpoint',flush=True)
    finally:
        lab.disarm()
        lab.fake(mower='docked',activity='MODE_READY',charging=True,error='normal')

if __name__=='__main__':run()
