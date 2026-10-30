import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import app
import collector
from test_realtime import MemoryStore

UTC=timezone.utc
NOW=datetime(2026,10,12,15,58,tzinfo=UTC)
HOUR=NOW.replace(hour=16,minute=0)
def report(station,**extra):
    return dict(icaoId=station,metarType='METAR',obsTime=NOW.replace(minute=53).timestamp(),
                temp=24,dewp=12,wspd=5,wdir=350,**extra)
def reports():return [report(s) for s in app.STATIONS]

class HourlyObservationTests(unittest.TestCase):
    def setUp(self):app._cache.clear()

    def test_t_remark_precision_is_preferred_then_averaged_before_fahrenheit(self):
        rows=[report(s,rawOb=f'{s} 121553Z 35005KT 24/12 RMK T0{t}0{d}')
              for s,t,d in zip(app.STATIONS,['244','245','249'],['121','123','127'])]
        data=app.observations(rows,NOW,rapid_reports=[{**r,'temp':99} for r in rows])
        self.assertTrue(data['current']['available'])
        self.assertEqual(data['current']['hour'],app.iso(HOUR))
        self.assertAlmostEqual(data['current']['tempC'],73.8/3)
        self.assertEqual(data['current']['tempF'],76.3)
        self.assertEqual(data['current']['dewpointF'],54.3)
        self.assertEqual(data['current']['tempF'],data['history'][0]['tempF'])

    def test_negative_precision_and_decoded_fallback(self):
        row=app.metar_precision(report('KFCM',rawOb='KFCM 121553Z M02/M05 RMK T10241057'))
        self.assertEqual(row['temp'],-2.4);self.assertEqual(row['dewp'],-5.7)
        self.assertEqual(app.metar_precision(report('KFCM'))['temp'],24)
        self.assertEqual(app.metar_precision(report('KFCM',rawOb='KFCM 121553Z RMK T0244'))['dewp'],12)
        self.assertEqual(app.metar_precision(report('KFCM',rawOb='KFCM T00000000 121553Z'))['temp'],24)

    def test_no_rapid_request_and_speci_cannot_replace_hourly(self):
        with patch('app.get_reports',return_value=reports()),patch('app.get_rapid_reports') as rapid:
            value=app.observations(now=NOW)
        rapid.assert_not_called()
        rows=reports()+[{**report('KFCM'),'metarType':'SPECI','temp':40}]
        self.assertEqual(app.observations(rows,NOW)['current']['tempF'],75.2)
        self.assertEqual(value['current']['tempF'],75.2)

    def test_missing_current_site_pauses_without_carrying_previous_hour(self):
        rows=reports()[:2]+[{**report('KMIC'),'obsTime':(NOW.replace(minute=53)-timedelta(hours=1)).timestamp()}]
        data=app.observations(rows,NOW)
        self.assertFalse(data['current']['available'])
        self.assertEqual(data['current']['missingStations'],['KMIC'])
        self.assertIsNone(data['current']['tempF'])
        self.assertEqual(data['history'][0]['tempF'],75.2)
        self.assertEqual(data['history'][0]['qa']['stationsUsed'],2)

    def test_legacy_observation_collector_delegates_to_shared_source(self):
        store=MemoryStore()
        with patch('collector.collect_metar_clouds',return_value={'stations':3}) as shared,patch('app.get_reports') as individual:
            self.assertEqual(collector.collect_observations(store,NOW),{'stations':3})
        shared.assert_called_once_with(store,NOW);individual.assert_not_called()

    def test_failed_shared_collection_preserves_data_and_checked_time(self):
        store=MemoryStore();store.write_json('live/metar-clouds.json',dict(history=[],checkedAt=app.iso(NOW)))
        original=store.read('live/metar-clouds.json')
        for payload in (TimeoutError(),b'<response><data/></response>'):
            with self.subTest(payload=type(payload).__name__):
                with patch('app.download',**({'side_effect':payload} if isinstance(payload,Exception) else {'return_value':payload})):
                    with self.assertRaises((TimeoutError,ValueError)):collector.collect_observations(store,NOW)
                self.assertEqual(store.read('live/metar-clouds.json'),original)

    def test_saved_snapshot_not_stale_during_hourly_gap_but_flags_missed_collection(self):
        hour=NOW.replace(minute=0)
        for now,checked,stale in [(hour+timedelta(minutes=40),hour+timedelta(minutes=2),False),
                                  (hour+timedelta(minutes=59),hour+timedelta(minutes=2),False),
                                  (hour+timedelta(hours=1,minutes=1),hour+timedelta(minutes=2),False),
                                  (hour+timedelta(hours=1,minutes=5),hour+timedelta(minutes=2),True),
                                  (hour+timedelta(hours=1,minutes=5),hour+timedelta(hours=1,minutes=2),False)]:
            with self.subTest(now=now,checked=checked):
                app._cache.clear();store=MemoryStore()
                store.write_json('live/observations.json',dict(reports=reports(),checkedAt=app.iso(checked)))
                with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=now),patch('app.download') as download:
                    data=app.observation_payload()
                self.assertEqual(data['stale'],stale);download.assert_not_called()

    def test_deployment_has_one_shared_hourly_job_and_retires_separate_observations(self):
        from pathlib import Path
        text=Path('deploy.sh').read_text()
        self.assertIn("weather_schedule metar-clouds '0,5,10 * * * *'",text)
        self.assertNotIn('weather_schedule observations',text)
        self.assertIn('gcloud scheduler jobs delete weather-live-observations',text)

