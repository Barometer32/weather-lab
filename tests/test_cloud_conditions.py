from datetime import datetime, timezone
import unittest

import airport_plots
from cloud_conditions import summarize


class CloudConditionsTests(unittest.TestCase):
    def test_highest_cover_and_lowest_ceiling_are_selected_independently(self):
        data=summarize({'rawOb':'METAR KMSP 161153Z 35017KT 7SM FEW011 BKN027 OVC037 08/05 A3021 RMK BKN001'})
        self.assertEqual(data['skyCover']['code'],'OVC')
        self.assertEqual(data['skyCover']['displayFraction'],1)
        self.assertEqual(data['ceiling'],{'cover':'BKN','baseFtAGL':2700,'kind':'ceiling'})
        self.assertEqual(len(data['cloudLayers']),3)

    def test_structured_layers_keep_lowest_overcast_even_if_broken_is_above_it(self):
        data=summarize({'layers':[{'cover':'BKN','baseFtAGL':5000},{'cover':'OVC','baseFtAGL':1900}]})
        self.assertEqual(data['ceiling']['cover'],'OVC')
        self.assertEqual(data['ceiling']['baseFtAGL'],1900)

    def test_category_ranges_are_preserved_instead_of_inventing_exact_oktas(self):
        for code,limits,fraction in [('FEW',[1,2],.25),('SCT',[3,4],.5),('BKN',[5,7],.75),('OVC',[8,8],1)]:
            result=summarize({'rawOb':f'KMSP 161153Z 27010KT {code}025 08/05 A3000'})
            self.assertEqual(result['skyCover']['oktaRange'],limits)
            self.assertEqual(result['skyCover']['displayFraction'],fraction)
            self.assertEqual(result['skyCover']['representativeFill'],code!='OVC')

    def test_clear_unknown_and_significant_cloud_criteria_are_distinct(self):
        clear=summarize({'rawOb':'KMSP 161153Z CLR 08/05 A3000'})
        unknown=summarize({'rawOb':'KMSP 161153Z 08/05 A3000 RMK BKN025'})
        cavok=summarize({'rawOb':'CYYY 161153Z CAVOK 08/05 Q1013'})
        self.assertEqual(clear['skyCover']['displayFraction'],0)
        self.assertIn('sensor',clear['skyCover']['description'])
        self.assertIsNone(unknown['skyCover']['code'])
        self.assertIsNone(unknown['skyCover']['displayFraction'])
        self.assertIsNone(cavok['skyCover']['displayFraction'])

    def test_obscured_sky_keeps_vertical_visibility_separate(self):
        data=summarize({'rawOb':'KMSP 161153Z 1/4SM FG VV003 08/08 A3000'})
        self.assertEqual(data['skyCover']['code'],'VV')
        self.assertEqual(data['ceiling'],{'cover':'VV','baseFtAGL':300,'kind':'verticalVisibility'})

    def test_unknown_height_is_not_replaced_with_an_unverified_higher_ceiling(self):
        data=summarize({'rawOb':'KMSP 161153Z BKN/// OVC030 08/05 A3000'})
        self.assertIsNone(data['ceiling']['baseFtAGL'])
        self.assertEqual(data['skyCover']['code'],'OVC')
        self.assertEqual(data['cloudLayers'][0]['baseFtAGL'],3000)

    def test_scattered_or_few_only_has_no_ceiling_label(self):
        data=summarize({'rawOb':'KMSP 161153Z FEW010 SCT030 08/05 A3000'})
        self.assertEqual(data['skyCover']['code'],'SCT')
        self.assertIsNone(data['ceiling'])

    def test_bad_structured_layers_and_remarks_cannot_invent_clouds(self):
        data=summarize({'layers':[{},None,{'cover':'BKN','baseFtAGL':True}], 'rawOb':'KMSP RMK OVC001'})
        self.assertIsNone(data['ceiling']['baseFtAGL'])
        self.assertEqual(summarize({'layers':'invalid','rawOb':'KMSP RMK BKN025'})['cloudLayers'],[])
        self.assertEqual(summarize({'rawOb':'KMSP NIL'})['cloudLayers'],[])

    def test_saved_history_gains_cloud_data_without_changing_any_weather_values_or_times(self):
        hour=datetime(2026,10,16,12,tzinfo=timezone.utc)
        row={'station':'KMSP','stationKey':'AWC_METAR:KMSP','network':'AWC_METAR',
             'source':airport_plots.SOURCE,'reportType':'METAR','lat':44.9,'lon':-93.3,
             'time':'2026-10-16T11:53:00Z','tempF':46.,'dewpointF':41.,
             'wind':{'speedKnots':17.,'speedMph':19.6,'direction':350.,'variable':False},
             'rawOb':'METAR KMSP 161153Z 35017KT FEW011 BKN027 OVC037 08/05 A3021'}
        data={'hour':airport_plots.iso(hour),'checkedAt':airport_plots.iso(hour),'history':[{'hour':airport_plots.iso(hour),'stations':[row]}]}
        selected=airport_plots.current(data,hour)['stations'][0]
        for key in ['station','time','tempF','dewpointF','wind','lat','lon']:
            self.assertEqual(selected[key],row[key])
        self.assertEqual(selected['ceiling']['baseFtAGL'],2700)
        self.assertEqual(selected['skyCover']['code'],'OVC')
        self.assertEqual(airport_plots.normalize(selected,hour),selected)


if __name__=='__main__':unittest.main()
