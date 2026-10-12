import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import app as weather
import collector
from rapid_observations import parse_reports, current_snapshot, recent_metars
from test_realtime import MemoryStore

NOW = datetime(2026, 10, 11, 23, 55, tzinfo=timezone.utc)


def report(station, minute=50, **values):
    return {"icaoId": station, "obsTime": NOW.replace(minute=minute).timestamp(),
            "temp": 24, "dewp": 12, "wspd": 5, "wdir": 350, **values}


def payload():
    return b'station,valid,metar,tmpf\nFCM,2026-10-11 23:50,KFCM 112350Z AUTO 35005KT 10SM CLR 24/12 A2967 RMK T02440122 MADISHF,999\nMSP,2026-10-11 23:50,SPECI KMSP 112350Z 01005G20KT 10SM 24/12 A2967 RMK T02490129,999\nMIC,2026-10-11 23:45,KMIC 112345Z AUTO 00000KT 10SM CLR 25/12 A2967 MADISHF,999\n'


class RapidObservationTests(unittest.TestCase):
    def setUp(self):
        weather._cache.clear()

    def test_decodes_main_celsius_not_fahrenheit_or_precision_remark_then_averages(self):
        rows = parse_reports(payload(), weather.STATIONS, NOW)
        self.assertEqual([row['temp'] for row in rows], [24, 24, 25])
        result = current_snapshot(rows, NOW)
        self.assertTrue(result['available'])
        self.assertAlmostEqual(result['tempC'], 73 / 3)
        self.assertEqual(result['tempF'], 75.8)
        self.assertEqual(result['dewpointF'], 53.6)
        self.assertEqual(result['oldestObservedAt'], '2026-10-11T23:45:00Z')
        self.assertEqual(result['observedAt'], '2026-10-11T23:48:20Z')
        self.assertEqual(result['newestObservedAt'], '2026-10-11T23:50:00Z')
        self.assertEqual(result['wind']['direction'] % 360, 0)

    def test_negative_temperature_variable_winds_and_invalid_payload(self):
        raw=b'station,valid,metar\nFCM,2026-10-11 23:50,KFCM 112350Z VRB04KT M02/M05 A3000\n'
        row=parse_reports(raw,weather.STATIONS,NOW)[0]
        self.assertEqual((row['temp'],row['dewp'],row['wdir']),(-2,-5,'VRB'))
        with self.assertRaises(ValueError):parse_reports(b'<html>error</html>',weather.STATIONS,NOW)

    def test_rolling_updates_use_latest_each_station_and_mean_timestamp(self):
        rows=[report('KFCM',45),report('KMIC',45),report('KMSP',30,temp=25)]
        first=current_snapshot(rows,NOW)
        self.assertTrue(first['available'])
        self.assertEqual(first['observedAt'],'2026-10-11T23:40:00Z')
        self.assertFalse(first['timeSpreadWarning'])
        rows.append(report('KMSP',35,temp=26))
        second=current_snapshot(rows,NOW)
        self.assertEqual(second['observedAt'],'2026-10-11T23:41:40Z')
        self.assertAlmostEqual(second['tempC'],74/3)
        self.assertEqual(second['tempF'],76.4)
        self.assertEqual(second['count'],3)

    def test_thirty_minute_gap_warns_without_removing_station(self):
        rows=[report('KFCM',50),report('KMIC',50),report('KMSP',20)]
        result=current_snapshot(rows,NOW)
        self.assertTrue(result['available'])
        self.assertFalse(result['timeSpreadWarning'])
        rows[-1]['obsTime']-=1
        result=current_snapshot(rows,NOW)
        self.assertTrue(result['available'])
        self.assertTrue(result['timeSpreadWarning'])
        self.assertEqual(result['outOfSyncStations'],['KMSP'])
        self.assertEqual(result['timestampSpreadSeconds'],1801)
        self.assertEqual(result['qa']['stationsUsed'],3)

    def test_missing_or_invalid_station_pauses_then_resumes(self):
        rows=[report('KFCM'),report('KMIC')]
        result=current_snapshot(rows,NOW)
        self.assertFalse(result['available'])
        self.assertEqual(result['missingStations'],['KMSP'])
        self.assertIsNone(result['observedAt'])
        self.assertIsNone(result['tempF'])
        self.assertIsNone(result['wind']['speedMph'])
        rows.append(report('KMSP',30))
        self.assertTrue(current_snapshot(rows,NOW)['available'])
        rows.append(report('KMSP',35,dewp=30))
        self.assertFalse(current_snapshot(rows,NOW)['available'])
        rows.append(report('KMSP',40))
        self.assertTrue(current_snapshot(rows,NOW)['available'])

    def test_mean_time_across_hour_boundary_uses_equal_station_weights(self):
        rows=[report(s,obsTime=stamp.timestamp()) for s,stamp in zip(weather.STATIONS,
              [NOW.replace(minute=0),NOW.replace(minute=0)-timedelta(minutes=5),
               NOW.replace(minute=0)-timedelta(minutes=10)])]
        result=current_snapshot(rows,NOW.replace(minute=1))
        self.assertTrue(result['available'])
        self.assertEqual(result['observedAt'],'2026-10-11T22:55:00Z')

    def test_age_limit_future_and_invalid_fields_cannot_look_current(self):
        rows=[report(s,obsTime=(NOW-timedelta(hours=1)).timestamp()) for s in weather.STATIONS]
        self.assertTrue(current_snapshot(rows,NOW)['available'])
        self.assertFalse(current_snapshot(rows,NOW+timedelta(seconds=1))['available'])
        future=[report(s,56) for s in weather.STATIONS]
        self.assertFalse(current_snapshot(future,NOW)['available'])
        rows=[report(s) for s in weather.STATIONS];rows[1]['dewp']=30
        self.assertFalse(current_snapshot(rows,NOW)['available'])

    def test_wrong_station_timestamp_and_future_are_rejected_by_parser(self):
        bad=payload().replace(b'112350Z',b'112340Z')
        self.assertEqual([r['icaoId'] for r in parse_reports(bad,weather.STATIONS,NOW)],['KMIC'])
        self.assertEqual(parse_reports(payload(),weather.STATIONS,NOW.replace(minute=44)),[])

    def test_earlier_arriving_routine_and_speci_reports_also_use_main_celsius_group(self):
        hourly=[report(s,53,metarType='METAR',temp=99,tmpf=999,
                       rawOb=f'{s} 112353Z 35005KT 10SM CLR 24/12 A2967 RMK T02440129')
                for s in weather.STATIONS]
        rows=recent_metars(hourly,weather.STATIONS,NOW)
        self.assertEqual([r['temp'] for r in rows],[24,24,24])
        result=current_snapshot(parse_reports(payload(),weather.STATIONS,NOW)+rows,NOW)
        self.assertTrue(result['available'])
        self.assertEqual(result['observedAt'],'2026-10-11T23:53:00Z')
        self.assertEqual(result['tempF'],75.2)

    def test_hourly_history_remains_routine_and_independent_of_current(self):
        hourly=[report(s,53,metarType='METAR',temp=10) for s in weather.STATIONS]
        result=weather.observations(hourly,NOW,parse_reports(payload(),weather.STATIONS,NOW))
        self.assertEqual(len(result['history']),12)
        self.assertEqual(result['history'][0]['hour'],'2026-10-12T00:00:00Z')
        self.assertEqual(result['history'][0]['tempF'],50)
        self.assertEqual(result['current']['tempF'],75.8)

    def test_hourly_53_uses_celsius_without_intermediate_rounding_or_fahrenheit_fields(self):
        rows=[report(s,53,metarType='METAR',temp=c,tmpf=999,tempF=999)
              for s,c in zip(weather.STATIONS,[10.04,10.04,10.14])]
        hour=NOW.replace(minute=0)+timedelta(hours=1)
        result=weather.hourly_snapshot(rows,hour,NOW)
        self.assertAlmostEqual(result['tempC'],30.22/3)
        self.assertEqual(result['tempF'],50.1)

    def test_collector_and_public_api_preserve_timestamps_without_visitor_upstream_calls(self):
        store=MemoryStore()
        hourly=[report(s,53,metarType='METAR') for s in weather.STATIONS]
        rapid=parse_reports(payload(),weather.STATIONS,NOW)
        with patch('app.get_reports',return_value=hourly),patch('app.get_rapid_reports',return_value=rapid):
            collector.collect_observations(store,NOW)
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW),patch('app.download') as download:
            response=weather.app.test_client().get('/api/observations')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['current']['tempF'],75.8)
        self.assertEqual(response.json['current']['observedAt'],'2026-10-11T23:48:20Z')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        download.assert_not_called()
        with patch('app.get_reports',return_value=hourly),patch('app.get_rapid_reports',side_effect=TimeoutError()):
            collector.collect_observations(store,NOW+timedelta(minutes=26))
        saved=store.read_json('live/observations.json')
        self.assertEqual(saved['rapidCheckedAt'],weather.iso(NOW))
        self.assertFalse(current_snapshot(saved['rapidReports'],NOW+timedelta(minutes=56))['available'])

    def test_collector_retains_other_sites_during_partial_batches_and_expires_them(self):
        store=MemoryStore()
        initial=[report('KFCM',45),report('KMIC',45),report('KMSP',30)]
        with patch('app.get_reports',return_value=[]),patch('app.get_rapid_reports',return_value=initial):
            collector.collect_observations(store,NOW)
        with patch('app.get_reports',return_value=[]),patch('app.get_rapid_reports',return_value=[report('KMSP',35,temp=26)]):
            collector.collect_observations(store,NOW+timedelta(minutes=1))
        with patch('app.get_store',return_value=store),patch('app.utcnow',return_value=NOW+timedelta(minutes=1)):
            current=weather.app.test_client().get('/api/observations').json['current']
        self.assertTrue(current['available'])
        self.assertEqual(current['observedAt'],'2026-10-11T23:41:40Z')
        self.assertEqual(current['tempF'],76.4)
        with patch('app.get_reports',return_value=[]),patch('app.get_rapid_reports',return_value=[]):
            collector.collect_observations(store,NOW+timedelta(hours=1))
        self.assertEqual(store.read_json('live/observations.json')['rapidReports'],[])



if __name__ == '__main__':
    unittest.main()
