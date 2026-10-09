import base64
from datetime import datetime, timedelta, timezone
import gzip
import json
import struct
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch

import numpy as np

import app as weather
import collector
import native_radar as radar
from test_realtime import MemoryStore

NOW = datetime(2026, 10, 9, 18, tzinfo=timezone.utc)


def sweep(site="KMPX", angle=0.5, minute=59, gates=4, doppler=False):
    result = []
    for i in range(720):
        hdr = Obj(stid=site.encode(), date=20736, time_ms=(17*3600+minute*60)*1000+i*20,
                  rad_status=5 if i==0 else 2 if i==719 else 0, az_num=i+1,
                  az_angle=i*0.5, az_spacing=0.5, el_angle=angle)
        moment = Obj(num_gates=gates,first_gate=2.125,gate_width=0.25)
        moments={b"REF":(moment,np.resize(np.array([9.5,10,30,60]),gates))}
        if doppler: moments[b"VEL"]=(None,None)
        result.append(Obj(header=hdr,moments=moments,vol_consts=Obj(lat=44.8489,lon=-93.5655,vcp=212)))
    return result


class NativeRadarTests(unittest.TestCase):
    def test_chunk_restart_retains_native_values_and_only_publishes_complete_sweep(self):
        rows=sweep(gates=1832)
        items,pending=radar.consume(rows[:400],"KMPX")
        self.assertEqual(items,[])
        self.assertIsNotNone(pending)
        items,pending=radar.consume(rows[400:],"KMPX",pending)
        self.assertIsNone(pending)
        self.assertEqual(len(items),1)
        meta,codes=radar.unpack(items[0][1])
        self.assertEqual(codes.shape,(720,1832))
        self.assertEqual(meta["gateWidthMeters"],250)
        self.assertEqual(meta["azimuthSpacing"],0.5)
        self.assertEqual(codes[0,:4].tolist(),[0,86,126,186])
        self.assertEqual(meta["nominalElevation"],0.5)

    def test_missing_ray_or_missing_sweep_start_is_never_published(self):
        rows=sweep()
        for incomplete in [rows[1:],rows[:300]+rows[301:],rows[:-1]]:
            items,_=radar.consume(incomplete,"KMPX")
            self.assertFalse(items)

    def test_scan_plan_retains_lowest_supplemental_cuts_despite_antenna_transition_angles(self):
        rows=radar.Radials(sweep("KEVX",angle=0.3,minute=50)+sweep("KEVX",angle=0.5,minute=51)+sweep("KEVX",angle=0.3,minute=52))
        rows.cuts={"1":{"angle":0.3,"waveform":"Contiguous Surveillance"},
                   "2":{"angle":0.5,"waveform":"Contiguous Surveillance"},
                   "3":{"angle":0.3,"waveform":"Contiguous Surveillance"}}
        for i,row in enumerate(rows):row.header.el_num=i//720+1
        rows[0].header.el_angle=0.47
        rows[720].header.el_angle=0.31
        items,_=radar.consume(rows,"KEVX")
        self.assertEqual(len(items),2)
        self.assertEqual([meta["nominalElevation"] for meta,_ in items],[0.3,0.3])
        data=radar.manifest([{**meta,"elevationDegrees":meta["nominalElevation"]} for meta,_ in items],NOW,"KEVX",[])
        self.assertEqual(data["elevationDegrees"],0.3)

    def test_low_supplemental_scans_retained_without_split_cut_duplicates_or_other_tilts(self):
        rows=sweep(minute=50)+sweep(doppler=True,minute=51)+sweep(angle=1.5,minute=52)+sweep(minute=53)+sweep(angle=0.3,minute=54)
        items,_=radar.consume(rows,"KMPX")
        self.assertEqual(len(items),2)
        self.assertIn("17:50",items[0][0]["time"])
        self.assertIn("17:53",items[1][0]["time"])

    def test_site_mismatch_rejected_and_packet_roundtrips_exact_values(self):
        with self.assertRaises(ValueError):radar.consume(sweep("KEVX"),"KMPX")
        values=np.arange(256,dtype=np.uint8).reshape(2,128)
        data=radar.packet({"azimuths":[0,180],"gates":128},values)
        meta,actual=radar.unpack(data)
        np.testing.assert_array_equal(actual,values)
        self.assertEqual(meta["gates"],128)

    def test_window_uses_actual_timestamps_including_subsecond_future_and_midnight(self):
        now=datetime(2026,10,10,0,tzinfo=timezone.utc)
        stamps=[now-timedelta(hours=2),now-timedelta(hours=2,microseconds=1),now,now+timedelta(microseconds=1)]
        frames=[{"id":str(i),"time":radar.iso(t)} for i,t in enumerate(stamps)]
        data=radar.manifest(frames,now,"KEVX",[])
        self.assertEqual([f["id"] for f in data["frames"]],["0","2"])
        self.assertEqual(data["site"],"KEVX")

    def test_collector_keeps_sites_independent_when_one_feed_fails(self):
        with patch("native_radar.collect_site",side_effect=[ValueError("offline"),{"frames":3}]) as collect:
            result=collector.collect_radar(MemoryStore(),NOW)
        self.assertIn("error",result["KMPX"])
        self.assertEqual(result["KEVX"],{"frames":3})
        self.assertEqual([call.args[2] for call in collect.call_args_list],["KMPX","KEVX"])

    def test_stream_cursor_and_partial_sweep_survive_restart_and_ignore_unchanged_chunks(self):
        store=MemoryStore();rows=sweep(gates=1832)
        archive={"key":"2026/10/09/KMPX/KMPX20261009_175000_V06","time":"2026-10-09T17:50:00Z"}
        chunks=[{"key":f"KMPX/1/20261009-175900-{i:03d}-{'S' if i==1 else 'I'}","modified":"2026-10-09T17:59:00Z"} for i in range(1,4)]
        header=b"AR2V0006.001"+b"\0"*8+b"KMPX"
        def listing(base,prefix):return chunks if prefix=="KMPX/1/" else []
        def fetch(url,header=False):
            if header:return b"AR2V0006.001"+b"\0"*8+b"KMPX"
            return url.encode()
        def decode(data,header=True):
            url=data.decode()
            if url.endswith('-S'):return []
            if '-002-I' in url:return rows[:400]
            if '-003-I' in url:return rows[400:]
            return rows
        with patch("native_radar.archive_volumes",return_value=[archive]),patch("native_radar.objects",side_effect=listing),patch("native_radar.fetch",side_effect=fetch) as download,patch("native_radar.decode",side_effect=decode):
            result=radar.collect_site(store,NOW,"KMPX",[])
            self.assertEqual(result["frames"],1)
            self.assertEqual(store.read_json("live/radar-state-KMPX.json")["streams"]["1"]["sequence"],3)
            native_keys=[k for k in store.writes if k.endswith('.bin')]
            self.assertEqual(len(native_keys),1)
            store.writes.clear();download.reset_mock()
            radar.collect_site(store,NOW,"KMPX",[])
            self.assertEqual(download.call_count,1) # Only the cheap anchor header, no old chunks or volumes.
            self.assertFalse(any(k.endswith('.bin') for k in store.writes))

    def test_native_web_reads_site_manifest_and_gzipped_packets_without_upstream_processing(self):
        store=MemoryStore();items,_=radar.consume(sweep("KEVX",gates=1832),"KEVX")
        meta,data=items[0];key=f"radar/{radar.VERSION}/KEVX/{meta['id']}.bin"
        store.write(key,data,"application/octet-stream")
        store.write_json("live/radar-KEVX.json",radar.manifest([meta],NOW,"KEVX",[]))
        weather._cache.clear();weather.prepared_image.cache_clear()
        with patch("app.get_store",return_value=store),patch("app.utcnow",return_value=NOW),patch("app.download") as upstream:
            client=weather.app.test_client();response=client.get('/api/radar?site=KEVX')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['site'],'KEVX')
            self.assertEqual(client.get('/api/radar?site=KTLH').status_code,400)
            response=client.get('/api/prepared/'+key)
            self.assertEqual(response.headers['Content-Encoding'],'gzip')
            self.assertEqual(response.data,data)
            self.assertEqual(client.get('/api/prepared/live/radar-state-KEVX.json').status_code,404)
            upstream.assert_not_called()


if __name__=="__main__":unittest.main()
