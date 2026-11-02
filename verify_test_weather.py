"""Verify the TEST UI and seeded point analysis independently of NWS uptime."""
import json
import sys
from urllib.request import Request, urlopen


def verify(base):
    def read(path):
        with urlopen(Request(base.rstrip('/')+path,headers={'User-Agent':'Weather-Lab deployment check'}),timeout=90) as response:
            return response.read()
    html = read('/').decode()
    if 'id="tab-test"' not in html or 'test-weather.js?v=test-history-v1' not in html:
        raise ValueError('TEST page assets were not published.')
    data = json.loads(read('/api/test/conditions?lat=44.9244&lon=-93.414&minutes=30'))
    if not data.get('checkedAt') or data.get('gridSpacingKm') != 5 or data.get('windowMinutes') != 30 or not isinstance(data.get('fields'), dict) or not isinstance(data.get('available'), bool):
        raise ValueError('The TEST observation snapshot was not verified.')
    history=json.loads(read('/api/test/history?lat=44.9244&lon=-93.414'))
    if len(history.get('frames',[]))!=13 or history.get('observationWindowMinutes')!=30:
        raise ValueError('TEST twelve-hour history was not verified.')
    print('TEST ready; '+str(data.get('stationCount',0))+' supporting stations near Hopkins.',flush=True)
    if not data.get('available'):
        print('No local estimate currently has enough recent station support. Source checks will continue.',flush=True)


if __name__ == '__main__':
    verify(sys.argv[1])
