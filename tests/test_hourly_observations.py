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

    def test_collector_forces_fresh_requests_and_retains_partial_batch_corrections(self):
        store=MemoryStore()
        initial=reports();initial[0]['receiptTime']='2026-10-12T15:54:00Z'
        with patch('app.get_reports',return_value=initial),patch('app.get_rapid_reports') as rapid:
            app._cache['metar']=('sentinel',initial)
            collector.collect_observations(store,NOW.replace(minute=55))
            self.assertNotIn('metar',app._cache)
        rapid.assert_not_called()
        new={**initial[0],'temp':25,'receiptTime':'2026-10-12T15:57:00Z'}
        with patch('app.get_reports',return_value=[new,initial[0]]):
            collector.collect_observations(store,NOW)
        saved=store.read_json('live/observations.json')
        self.assertEqual(len(saved['reports']),3)
        self.assertNotIn('rapidReports',saved)
        self.assertEqual(app.observations(saved['reports'],NOW)['current']['tempF'],75.8)

    def test_failed_and_empty_collection_preserves_data_and_checked_time(self):
        store=MemoryStore();store.write_json('live/observations.json',dict(reports=reports(),checkedAt=app.iso(NOW)))
        original=store.read('live/observations.json')
        with patch('app.get_reports',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):collector.collect_observations(store,NOW+timedelta(minutes=4))
        self.assertEqual(store.read('live/observations.json'),original)
        with patch('app.get_reports',return_value=[]):
            with self.assertRaises(ValueError):collector.collect_observations(store,NOW+timedelta(minutes=4))
        self.assertEqual(store.read('live/observations.json'),original)

    def test_saved_snapshot_not_stale_during_normal_gap_but_flags_missed_checks(self):
        for now,checked,stale in [
            (NOW.replace(minute=40),NOW.replace(minute=2),False),
            (NOW.replace(minute=56),NOW.replace(minute=2),False),
            (NOW.replace(minute=57),NOW.replace(minute=2),True),
            (NOW.replace(minute=59),NOW.replace(minute=55),False),
            (HOUR,HOUR-timedelta(minutes=5),True),
            (HOUR+timedelta(minutes=4),HOUR-timedelta(minutes=2),True),
            (HOUR+timedelta(minutes=40),HOUR+timedelta(minutes=2),False),
        ]:
            with self.subTest(now=now,checked=checked):
                app._cache.clear();store=MemoryStore()
                store.write_json('live/observations.json',dict(reports=reports(),checkedAt=app.iso(checked)))
                with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=now),patch('app.download') as download:
                    data=app.app.test_client().get('/api/observations').json
                self.assertEqual(data['stale'],stale)
                download.assert_not_called()

    def test_deployment_schedule_has_only_three_observation_checks(self):
        from pathlib import Path
        self.assertIn("weather_schedule observations '2,55,58 * * * *'",Path('deploy.sh').read_text())
