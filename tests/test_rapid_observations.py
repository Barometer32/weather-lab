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
        self.assertEqual(result['wind']['direction'] % 360, 0)

    def test_negative_temperature_variable_winds_and_invalid_payload(self):
        raw=b'station,valid,metar\nFCM,2026-10-11 23:50,KFCM 112350Z VRB04KT M02/M05 A3000\n'
        row=parse_reports(raw,weather.STATIONS,NOW)[0]
        self.assertEqual((row['temp'],row['dewp'],row['wdir']),(-2,-5,'VRB'))
        with self.assertRaises(ValueError):parse_reports(b'<html>error</html>',weather.STATIONS,NOW)

    def test_five_minute_spread_allowed_but_over_five_and_partial_sets_rejected(self):
        rows=[report('KFCM'),report('KMSP'),report('KMIC',45)]
        self.assertTrue(current_snapshot(rows,NOW)['available'])
        for invalid in [rows[:2], rows[:2]+[report('KMIC',44)]]:
            result=current_snapshot(invalid,NOW)
            self.assertFalse(result['available'])
            self.assertIsNone(result['tempF'])
            self.assertIsNone(result['dewpointF'])
            self.assertIsNone(result['wind']['speedMph'])

    def test_latest_set_is_used_without_searching_older_complete_set(self):
        rows=[report(s,45) for s in weather.STATIONS]+[report('KFCM',55),report('KMSP',55)]
        self.assertFalse(current_snapshot(rows,NOW)['available'])

    def test_age_limit_future_and_invalid_fields_cannot_look_current(self):
        rows=[report(s,25) for s in weather.STATIONS]
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
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        download.assert_not_called()
        with patch('app.get_reports',return_value=hourly),patch('app.get_rapid_reports',side_effect=TimeoutError()):
            collector.collect_observations(store,NOW+timedelta(minutes=26))
        saved=store.read_json('live/observations.json')
        self.assertEqual(saved['rapidCheckedAt'],weather.iso(NOW))
        self.assertFalse(current_snapshot(saved['rapidReports'],NOW+timedelta(minutes=26))['available'])


if __name__ == '__main__':
    unittest.main()
