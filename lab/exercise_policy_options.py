"""Native advanced-policy forms reject invalid values and reload disarmed."""
from client import api
from urllib.error import HTTPError
from exercise_wizard import exercise
from scenario_client import Lab

def run():
    lab=Lab()
    entry=exercise()
    cases=[('rules',{'max_retries':0},{}),
           ('calendar',{'weekdays':[]},{'excluded_dates':'2099-01-01'}),
           ('safety_weather',{'multipleweather_entities':['weather.missing']},{'multipleweather_entities':['weather.lab_weather']}),
           ('charging',{'recharge_min_target':90,'recharge_max_target':60},{'recharge_min_target':60,'recharge_max_target':95})]
    for section,bad,good in cases:
        flow=api('/api/config/config_entries/options/flow',{'handler':entry},lab.token)
        url='/api/config/config_entries/options/flow/'+flow['flow_id']
        form=api(url,{'next_step_id':section},lab.token)
        data={item['name']:item['default'] for item in form['data_schema'] if 'default' in item}
        try:
            rejected=api(url,{**data,**bad},lab.token)
        except HTTPError as error:
            assert error.code==400,error
        else:
            assert rejected.get('errors'),rejected
        result=api(url,{**data,**good},lab.token)
        assert result['type']=='menu',result
        api(url,{'next_step_id':'review'},lab.token)
        assert api(url,{'understood':True},lab.token)['type']=='create_entry'
        lab.wait(lambda:lab.value('switch.lab_coordinator_automatic_control')=='off',message='disarmed policy reload')
    print('PASS: native recovery/calendar/weather/charging forms reject invalid policies and preserve disarmed reload',flush=True)

if __name__=='__main__':run()
