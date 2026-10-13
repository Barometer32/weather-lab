from datetime import datetime, timedelta, timezone
import gzip
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import netcdf_file

import app
import surface_observations as surface
from test_realtime import MemoryStore

HOUR=datetime(2026,10,13,1,tzinfo=timezone.utc)


def fixture(path, overrides=None, units="kelvin"):
    overrides=overrides or {}
    n=8
    with netcdf_file(path,"w") as ds:
        ds.createDimension("record",n);ds.createDimension("name",50);ds.createDimension("id",12)
        for key,values,length in [("stationId",["MN001","MN001","BAD01","NOQC","KCFE","OUT01","FUT01","KAAA"],12),
                ("dataProvider",["MesoWest"]*7+["NonFedAWOS"],12),
                ("stationName",["MNDOT"]*n,50)]:
            field=ds.createVariable(key,"c",("record","id" if length==12 else "name"))
            field[:]=np.array([list(s.ljust(length)) for s in values],dtype="S1")
        for key,values in [("latitude",[44.9]*5+[39,44.9,44.9]),("longitude",[-93.4]*n),
                ("observationTime",[(HOUR-timedelta(minutes=m)).timestamp() for m in [15,5,5,5,5,5,-1,7]])]:
            ds.createVariable(key,"d",("record",))[:]=values
        field=ds.createVariable("restrictedDataLevel","h",("record",));field._FillValue=-32767;field[:]=[-32767]*n
        for key,(target,unit,_,_) in surface.FIELDS.items():
            values=[293.15]*n if unit=="kelvin" else [50]*n if key=="relHumidity" else [10]*n
            if key=="dewpoint":values=[283.15]*n
            field=ds.createVariable(key,"f",("record",));field.units=units if key=="temperature" else unit
            field._FillValue=np.float32(3.4028235e38);field[:]=overrides.get(key,values)
            qc=ds.createVariable(key+"DD","c",("record",));qc[:]=np.array(overrides.get(key+"DD",["V","V","Q","Z","V","V","V","V"]),dtype="S1")
            ds.createVariable(key+"QCA","i",("record",))[:]=[123]*n
            ds.createVariable(key+"QCR","i",("record",))[:]=overrides.get(key+"QCR",[0,0,1,0,0,0,0,0])


def road_item(station="MN001",**changes):
    return {"station":station,"network":"MN_RWIS","name":"Road station","lat":44.9,"lon":-93.4,
            "utc_valid":surface.iso(HOUR),"tmpf":68,"dwpf":50,"relh":50,"sknt":10,"drct":350,"gust":15,**changes}


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        app._cache.clear();app.prepared_image.cache_clear()

    def parse(self,overrides=None,units="kelvin"):
        with tempfile.NamedTemporaryFile() as file:
            fixture(file.name,overrides,units)
            return surface.read_madis(file.name,HOUR,{"MN001":{"lat":44.9,"lon":-93.4,"network":"MN_RWIS","name":"Road station"}})

    def test_madis_latest_station_hour_selection_and_unit_conversion(self):
        rows=self.parse();good=next(r for r in rows if r["station"]=="MN001")
        self.assertEqual(good["time"],"2026-10-13T00:55:00Z")
        self.assertAlmostEqual(good["tempF"],68,places=2)
        self.assertAlmostEqual(good["windMph"],22.369,places=2)
        self.assertEqual(good["network"],"MN_RWIS")
        self.assertEqual([r["station"] for r in rows].count("MN001"),1)
        self.assertNotIn("KCFE",[r["station"] for r in rows])
        self.assertNotIn("OUT01",[r["station"] for r in rows])
        self.assertNotIn("FUT01",[r["station"] for r in rows])

    def test_failed_and_unchecked_fields_cannot_become_verified(self):
        rows=self.parse()
        for station in ["BAD01","NOQC"]:
            row=next(r for r in rows if r["station"]==station)
            self.assertIsNone(row["tempF"]);self.assertFalse(row["qc"]["tempF"]["accepted"])

    def test_qcr_failure_rejects_even_a_verified_descriptor(self):
        rows=self.parse({"temperatureQCR":[0,1,1,0,0,0,0,0]})
        row=next(r for r in rows if r["station"]=="MN001")
        self.assertIsNone(row["tempF"])
        self.assertIsNotNone(row["dewpointF"])

    def test_bad_units_fail_instead_of_mislabeling_temperature(self):
        with self.assertRaises(ValueError):self.parse(units="Fahrenheit")

    def test_fill_values_are_never_plotted_or_interpolated(self):
        row=next(r for r in self.parse({"temperature":[293.15,-9999,293.15,293.15,293.15,293.15,293.15,293.15]}) if r["station"]=="MN001")
        self.assertIsNone(row["tempF"])

    def test_road_air_temperature_uses_tmpf_not_pavement(self):
        rows,_=surface.road_rows({"data":[road_item(tfs0=140)]},HOUR)
        self.assertEqual(rows[0]["tempF"],68)
        self.assertEqual(rows[0]["qc"]["tempF"]["descriptor"],"LOCAL")
        self.assertAlmostEqual(rows[0]["windMph"],11.508,places=2)

    def test_road_old_future_and_invalid_latitudes_excluded(self):
        rows,_=surface.road_rows({"data":[road_item(utc_valid=surface.iso(HOUR-timedelta(minutes=31))),
            road_item("MN002",utc_valid=surface.iso(HOUR+timedelta(minutes=1))),road_item("MN003",lat=10)]},HOUR)
        self.assertEqual(rows,[])

    def test_madis_road_rejection_is_not_replaced_by_unflagged_iem_copy(self):
        roads,_=surface.road_rows({"data":[road_item()]},HOUR)
        madis=[{**roads[0],"tempF":None,"provider":"MesoWest","qc":{"tempF":{"descriptor":"Q","accepted":False}}}]
        merged=surface.merge(madis,roads,[])
        self.assertEqual(len(merged),1);self.assertIsNone(merged[0]["tempF"])

    def test_airport_is_independent_and_supersedes_duplicate_madis_id(self):
        row={"station":"KMSP","tempF":70.1,"dewpointF":50.2,"lat":44.9,"lon":-93.2,
            "time":"2026-10-13T00:53:00Z","wind":{"speedMph":10,"direction":350}}
        airports=surface.airport_rows({"history":[{"hour":surface.iso(HOUR),"stations":[row]}]},HOUR)
        merged=surface.merge([{**airports[0],"id":"Other:KMSP","tempF":99}],[],airports)
        self.assertEqual(len(merged),1);self.assertEqual(merged[0]["tempF"],70.1)
        self.assertNotIn("metro",merged[0]["station"])
        self.assertIn("rh",merged[0]["derived"])
        self.assertGreater(merged[0]["uMph"],0);self.assertLess(merged[0]["vMph"],0)

    def test_derived_dewpoint_uses_valid_inputs_and_keeps_qc_provenance(self):
        row={"tempF":68,"dewpointF":None,"rh":50,"windMph":0,"direction":None,"qc":{"tempF":{"descriptor":"V","accepted":True},"rh":{"descriptor":"V","accepted":True},"windMph":{"descriptor":"V","accepted":True}},"derived":[]}
        surface.finish(row)
        self.assertAlmostEqual(row["dewpointF"],48.7,delta=.2)
        self.assertEqual(row["qc"]["dewpointF"]["descriptor"],"V")
        self.assertEqual(row["uMph"],0)
        self.assertIn("dewpointF",row["derived"])

    def test_rejected_dewpoint_is_not_recreated_from_humidity(self):
        row={"tempF":68,"dewpointF":None,"rh":50,"qc":{"dewpointF":{"descriptor":"Q","accepted":False}},"derived":[]}
        surface.finish(row);self.assertIsNone(row["dewpointF"])

    def test_wisconet_same_hour_units_and_local_quality_provenance(self):
        properties={"station_id":"TEST","station_name":"Test site","madis_id":"WITST"}
        for source,(key,unit,_,_) in surface.WISCONET_FIELDS.items():
            properties[source]={"unitCode":unit,"observations":[{"timestamp":surface.iso(HOUR),"value":68 if key=="tempF" else 50 if key=="dewpointF" else 0 if key=="windMph" else 50,"qualityControl":"Z"}]}
        document={"type":"FeatureCollection","features":[{"geometry":{"coordinates":[-90,44]},"properties":properties}]}
        row=surface.wisconet_rows(document,HOUR)[0]
        self.assertEqual(row["tempF"],68);self.assertEqual(row["qc"]["tempF"]["descriptor"],"LOCAL")
        self.assertEqual(row["madisId"],"WITST");self.assertIn("dewpointF",row["derived"])
        properties["5min_air_temp_f_avg"]["unitCode"]="ud:degC"
        self.assertIsNone(surface.wisconet_rows(document,HOUR)[0]["tempF"])
        for field in [p for p in properties.values() if isinstance(p,dict)]:
            field["observations"][0]["timestamp"]=surface.iso(HOUR+timedelta(minutes=5))
        self.assertEqual(surface.wisconet_rows(document,HOUR),[])

    def test_wisconet_madis_alias_does_not_refill_a_rejected_madis_reading(self):
        madis={"id":"MesoWest:WITST","station":"WITST","network":"MesoWest","kind":"mesonet","lat":44,"lon":-90,"tempF":None}
        native={**madis,"id":"WISCONET:TEST","station":"TEST","network":"WISCONET","madisId":"WITST","tempF":75}
        result=surface.merge([madis],[],[],[native]);self.assertEqual(len(result),1);self.assertIsNone(result[0]["tempF"])

    def test_immutable_hour_asset_precedes_manifest_and_collection_deduplicates(self):
        store=MemoryStore();loader=lambda h,m:[]
        calls=[]
        def download(url):
            calls.append(url)
            return json.dumps({"type":"FeatureCollection","features":[]} if url.startswith(surface.WISCONET_URL) else {"data":[road_item()]}).encode()
        result=surface.collect(store,HOUR+timedelta(minutes=10),download,loader)
        self.assertEqual(result["stations"],1)
        self.assertEqual(store.writes[-1],"live/surface.json")
        manifest=store.read_json("live/surface.json");self.assertEqual(len(manifest["history"]),12)
        self.assertEqual(sum(bool(f["url"]) for f in manifest["history"]),1)
        surface.collect(store,HOUR+timedelta(minutes=11),download,loader)
        self.assertEqual(len(calls),2)
        self.assertIn("valid=2026-10-13T01%3A00%3A00Z",calls[0])

    def test_history_rolls_without_relabeling_old_observations(self):
        store=MemoryStore()
        for i in range(13):
            hour=HOUR+timedelta(hours=i)
            surface.collect(store,hour+timedelta(minutes=10),lambda u:json.dumps({"type":"FeatureCollection","features":[]} if u.startswith(surface.WISCONET_URL) else {"data":[road_item(utc_valid=surface.iso(hour))]}).encode(),lambda h,m:[])
        history=store.read_json("live/surface.json")["history"]
        self.assertEqual(len(history),12);self.assertEqual(history[0]["hour"],surface.iso(HOUR+timedelta(hours=1)))

    def test_failed_sources_retain_previous_data(self):
        store=MemoryStore();store.write_json("live/surface.json",{"old":True});before=store.read("live/surface.json")
        def fail(*args):raise TimeoutError()
        with self.assertRaises(ValueError):surface.collect(store,HOUR,fail,fail)
        self.assertEqual(store.read("live/surface.json"),before)

    def test_public_surface_api_reads_saved_objects_and_gzip_json_only(self):
        store=MemoryStore();surface.collect(store,HOUR,lambda u:json.dumps({"type":"FeatureCollection","features":[]} if u.startswith(surface.WISCONET_URL) else {"data":[road_item()]}).encode(),lambda h,m:[])
        with patch("app.get_store",return_value=store),patch("app.utcnow",return_value=HOUR),patch("app.download") as upstream:
            client=app.app.test_client();response=client.get("/api/surface")
            self.assertEqual(response.status_code,200)
            asset=client.get(response.json["history"][-1]["url"],headers={"Accept-Encoding":"gzip"})
            self.assertEqual(asset.mimetype,"application/json")
            self.assertEqual(asset.headers["Content-Encoding"],"gzip")
            self.assertEqual(json.loads(gzip.decompress(asset.data))["stations"][0]["station"],"MN001")
            self.assertEqual(client.get("/api/prepared/live/surface.json").status_code,404)
            upstream.assert_not_called()

    def test_no_web_request_initiates_surface_collection_without_store(self):
        with patch("app.get_store",return_value=None),patch("surface_observations.download_madis") as upstream:
            self.assertEqual(app.app.test_client().get("/api/surface").status_code,503);upstream.assert_not_called()


if __name__=="__main__":unittest.main()
