from datetime import timedelta
import unittest

import station_plots as stations
from test_station_plots import NOW, downloader, row

HEADER='station,obtime,longitude,latitude,tmpf,dwpf,sknt,drct\n'


def archive(*rows):
    return (HEADER+''.join(f'{station},{time},-93,45,50,40,5,270\n' for station,time in rows)).encode()


class LateRoadTests(unittest.TestCase):
    def test_bulk_history_keeps_each_station_once_per_hour_with_30_minute_edges(self):
        data=archive(('MN001','2026-10-14 18:30:00'),('MN001','2026-10-14 18:40:00'),
                     ('MN001','2026-10-14 19:30:00'),('OLD','2026-10-14 19:29:59'),('AT00','2026-10-14 20:00:00'))
        rows=stations.parse_rwis(data,'MN_RWIS',NOW,hours=12)
        self.assertEqual([(r['station'],r['time']) for r in rows],
                         [('MN001','2026-10-14T18:40:00Z'),('MN001','2026-10-14T19:30:00Z')])
        self.assertEqual(len(stations.parse_rwis(data,'MN_RWIS',NOW)),1)

    def test_late_roads_repair_original_hour_without_being_carried_to_new_hour(self):
        initial=stations.collect(downloader(row()),NOW)
        initial['history'][-1]['analysisUrl']='/old-analysis.json'
        later=NOW+timedelta(hours=1)
        base=downloader(row(utc_valid='2026-10-14T20:53:00Z'),
                        row('MN001','MN_RWIS',utc_valid='2026-10-14T20:00:00Z'))
        calls=[]
        def download(url):
            calls.append(url)
            if '/request/rwis.py?' in url and 'network=MN_RWIS' in url:
                return archive(('MN001','2026-10-14 19:40:00'),('MN002','2026-10-14 19:30:00'))
            return base(url)
        result=stations.collect(download,later,initial)
        earlier=next(f for f in result['history'] if f['hour']==stations.iso(NOW))
        self.assertEqual({r['station'] for r in earlier['stations']},{'KMSP','MN001','MN002'})
        self.assertNotIn('analysisUrl',earlier)
        self.assertEqual([r['station'] for r in result['stations']],['KMSP'])
        self.assertEqual(result['backfilledHours'],[stations.iso(NOW)])
        self.assertIn('MN_RWIS',result['delayedNetworks'])
        self.assertEqual(len(calls),len(stations.STATES)+len(stations.RWIS_NETWORKS)+1)
        self.assertEqual(next(r for r in earlier['stations'] if r['station']=='MN001')['time'],'2026-10-14T19:40:00Z')
        earlier['analysisUrl']='/new-analysis.json'
        again=stations.collect(download,later,result)
        self.assertNotIn(stations.iso(NOW),again['backfilledHours'])
        self.assertEqual(next(f for f in again['history'] if f['hour']==stations.iso(NOW))['analysisUrl'],'/new-analysis.json')


if __name__=='__main__':unittest.main()
