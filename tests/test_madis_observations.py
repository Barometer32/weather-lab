from datetime import datetime, timedelta, timezone
import gzip
from io import BytesIO
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

import numpy as np
from scipy.io import netcdf_file

import app
import madis_observations as madis
from rapid_observations import current_snapshot

NOW=datetime(2026,10,11,23,55,tzinfo=timezone.utc)


def fixture(qc_failure=False, invalid_unit=False, future=False, wind_status=0, wind_qc=0, wind_dd=b'V', wind_missing=False):
    stream=BytesIO()
    with netcdf_file(stream,'w') as dataset:
        dataset.createDimension('record',3);dataset.createDimension('idlen',6)
        dataset.createDimension('layer',3);dataset.createDimension('coverlen',8)
        station=dataset.createVariable('stationId','c',('record','idlen'))
        station[:]=np.array([list(s.ljust(6)) for s in app.STATIONS],dtype='S1')
        stamp=dataset.createVariable('observationTime','d',('record',))
        stamp[:]=[(NOW.replace(minute=50 if i<2 else 45)+timedelta(hours=int(future))).timestamp() for i in range(3)]
        for name,values in [('latitude',[44.83,44.88,45.07]),('longitude',[-93.45,-93.22,-93.35])]:
            dataset.createVariable(name,'f',('record',))[:]=values
        sky=dataset.createVariable('skyCvr','c',('record','layer','coverlen'))
        sky[:]=np.array([[list(cover.ljust(8)),list(' '*8),list(' '*8)] for cover in ['BKN','CLR','SCT']],dtype='S1')
        bases=dataset.createVariable('skyCovLayerBase','f',('record','layer'));bases.units=b'meter'
        bases[:]=[[1828.8,-9999,-9999],[3810,-9999,-9999],[609.6,-9999,-9999]]
        for name,unit,values in [('temperature',b'kelvin',[297.15,297.15,298.15]),
                                  ('dewpoint',b'kelvin',[285.15]*3),('windDir',b'degree',[350,10,0]),
                                  ('windSpeed',b'meter/sec',[2.572222]*3)]:
            field=dataset.createVariable(name,'f',('record',));field.units=b'Fahrenheit' if invalid_unit and name=='temperature' else unit
            field._FillValue=np.float32(3.4028235e38);field.missing_value=np.float32(-9999);field[:]=values
            check=dataset.createVariable(name+'QCR','i',('record',));check[:]=[0,wind_qc if name in ('windSpeed','windDir') else int(qc_failure and name=='temperature'),0]
            status=dataset.createVariable(name+'Status','i',('record',));status[:]=[0,wind_status if name in ('windSpeed','windDir') else 0,0]
            descriptor=dataset.createVariable(name+'DD','c',('record',));descriptor[:]=np.array([b'V',wind_dd,b'V'],dtype='S1')
            if wind_missing and name=='windSpeed':field[1]=-9999
        dataset.flush();content=stream.getvalue()
    return gzip.compress(content)


class MadisTests(unittest.TestCase):
    def test_decodes_kelvin_to_celsius_then_averages_without_fahrenheit_input(self):
        rows=madis.parse_file(fixture(),app.STATIONS,NOW)
        self.assertEqual(len(rows),3)
        self.assertAlmostEqual(rows[0]['temp'],24,places=4)
        result=current_snapshot(rows,NOW)
        self.assertTrue(result['available'])
        self.assertAlmostEqual(result['tempC'],73/3,places=4)
        self.assertEqual(result['tempF'],75.8)
        self.assertEqual(result['wind']['speedMph'],5.8)

    def test_noaa_qc_failure_prevents_three_station_average(self):
        rows=madis.parse_file(fixture(qc_failure=True),app.STATIONS,NOW)
        self.assertIsNone(rows[1]['temp'])
        self.assertFalse(current_snapshot(rows,NOW)['available'])

    def test_regional_clouds_use_meter_to_foot_conversion_without_inventing_clear_heights(self):
        rows=madis.parse_file(fixture(),None,NOW)
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['layers'][0]['baseFtAGL'],6000)
        self.assertEqual(rows[1]['layers'][0]['cover'],'CLR')
        self.assertIsNone(rows[1]['layers'][0]['baseFtAGL'])
        self.assertEqual(rows[2]['layers'][0]['baseFtAGL'],2000)

    def test_unexpected_units_future_reports_and_unselected_stations_are_not_used(self):
        with self.assertRaises(ValueError):madis.parse_file(fixture(invalid_unit=True),app.STATIONS,NOW)
        self.assertEqual(madis.parse_file(fixture(future=True),app.STATIONS,NOW),[])
        self.assertEqual(madis.parse_file(fixture(),{'KZZZ'},NOW),[])

    def test_new_hour_reads_previous_file_if_current_file_is_not_available(self):
        now=NOW+timedelta(minutes=8);urls=[]
        def download(url):
            urls.append(url)
            if '20261012_0000' in url:raise HTTPError(url,404,'not ready',{},None)
            return fixture()
        rows=madis.get_reports(app.STATIONS,now,download)
        self.assertEqual(len(rows),3)
        self.assertEqual(len(urls),2)
        self.assertIn('LDAD/hfmetar/netCDF/20261011_2300.gz',urls[-1])

    def test_conditional_download_reuses_unchanged_payload(self):
        madis._files.clear();url=madis.file_url(NOW)
        response=MagicMock();response.__enter__.return_value=response
        response.read.return_value=b'compressed';response.headers={'ETag':'example-version'}
        with patch('madis_observations.urlopen',side_effect=[response,HTTPError(url,304,'unchanged',{},None)]) as fetch:
            self.assertEqual(madis.fetch_file(url),b'compressed')
            self.assertEqual(madis.fetch_file(url),b'compressed')
        self.assertEqual(fetch.call_args.args[0].get_header('If-none-match'),'example-version')
        madis._files.clear()


    def test_reserved_wind_status_with_positive_madis_qc_keeps_numeric_wind(self):
        for status in [1,4,11,13,14,15]:
            with self.subTest(status=status):
                rows=madis.parse_file(fixture(wind_status=status),app.STATIONS,NOW)
                self.assertAlmostEqual(rows[1]['wspd'],5,places=4)
                self.assertEqual(rows[1]['wdir'],10)
                self.assertTrue(current_snapshot(rows,NOW)['available'])

    def test_reserved_status_does_not_override_failed_or_unconfirmed_qc(self):
        for options in [dict(wind_qc=1),dict(wind_dd=b'Q'),dict(wind_dd=b'B'),dict(wind_dd=b'X'),dict(wind_dd=b'Z'),dict(wind_missing=True)]:
            with self.subTest(options=options):
                rows=madis.parse_file(fixture(wind_status=15,**options),app.STATIONS,NOW)
                self.assertIsNone(rows[1]['wspd'])
                self.assertFalse(current_snapshot(rows,NOW)['available'])

    def test_explicit_sensor_faults_and_unknown_codes_still_excluded(self):
        for status in [2,3,5,6,7,8,9,10,12,99,-9999]:
            with self.subTest(status=status):
                rows=madis.parse_file(fixture(wind_status=status),app.STATIONS,NOW)
                self.assertIsNone(rows[1]['wspd'])
                self.assertFalse(current_snapshot(rows,NOW)['available'])


if __name__=='__main__':unittest.main()

