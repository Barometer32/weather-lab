from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import mn_asos_audit as audit


class Store:
    def read_json(self, key):
        assert key == audit.KEY
        return getattr(self, "data", None)

    def write_json(self, key, data):
        assert key == audit.KEY
        self.data = data


def test_audit_separates_feed_gaps_and_arrival_lag(monkeypatch):
    store = Store()
    start = datetime(2026, 11, 9, 18, 2, tzinfo=timezone.utc)
    t = int(start.timestamp())
    reports = [("KMSP", t-120, t-10)]
    monkeypatch.setattr(audit, "parse_timing", lambda payload: iter(reports))

    def download(url):
        if url.endswith("_1700.gz"):
            raise HTTPError(url, 404, "not available", {}, None)
        return b"example"

    audit.collect(store, start, download)
    assert audit.summarize(store.data)["firstSeenByPollLag"] is None

    reports[:] = [("KMSP", t-120, t-10), ("KMSP", t+180, t+320)]
    audit.collect(store, start+timedelta(minutes=10), download)
    reports.append(("KMSP", t+1380, t+1520))
    audit.collect(store, start+timedelta(minutes=30), download)
    report = audit.summarize(store.data)
    assert report["polls"] == report["pollsWithFileErrors"] == 3
    assert report["reportGapCountsByMinutes"] == {5: 1, 20: 1}
    assert report["stations"]["KMSP"]["gapsAtLeast20Minutes"] == 1
    assert report["firstSeenByPollLag"]["medianMinutes"] == 7
    assert report["madisReceiptLag"]["medianMinutes"] == 2.3
