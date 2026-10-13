"""All fixtures are fictional; they make no claims of actual viewing/listening."""
import copy
import importlib.util
import math
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('story_decisions', Path(__file__).parents[1]/'scripts/story_decisions.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture():
    return {'schema_version':'story-decisions/1','fps':25,
        'assets':[{'id':'fictional_video','duration':30},{'id':'fictional_music','duration':30}],
        'events':[{'id':'fictional_action','evidence':[{'asset_id':'fictional_video','source_start':10,'source_end':20,'review_ref':'FICTIONAL_TEST_ONLY'}]}],
        'shots':[{'shot_id':'s1','asset_id':'fictional_video','event_id':'fictional_action','reaction_to_event_id':None,'source_start':10,'source_end':20,'timeline_start':4,'speed':2}],
        'protected':[{'asset_id':'fictional_video','source_start':13,'source_end':15,'kind':'semantic','review_ref':'FICTIONAL_TEST_ONLY'}],
        'candidates':[{'id':'protected','shot_id':'s1','source_time':14,'dramatic_beat_id':'fictional_action','review_ref':'FICTIONAL_TEST_ONLY'}, {'id':'safe','shot_id':'s1','source_time':16,'dramatic_beat_id':'fictional_action','review_ref':'FICTIONAL_TEST_ONLY'}],
        'music':{'asset_id':'fictional_music','source_start':10,'source_end':20,'timeline_start':4,'listened_ranges':[{'source_start':10,'source_end':20,'review_ref':'FICTIONAL_TEST_ONLY'}],'beats':[12,13.08]},
        'max_beat_distance':.12}


def mapped_fixture(kind='constant'):
    data = fixture()
    data['schema_version'] = 'story-decisions/2'
    shot = data['shots'][0]
    shot.pop('speed')
    shot['output_duration'] = 5
    if kind == 'constant':
        shot['time_map'] = {'kind': 'constant', 'speed': 2}
    elif kind == 'speed_curve':
        # Source consumption = 5 * (1 + 3) / 2 = 10 seconds.
        shot['time_map'] = {'kind': 'speed_curve', 'knots':
                            [{'time': 0, 'speed': 1}, {'time': 5, 'speed': 3}]}
    else:
        shot['time_map'] = {'kind': 'pts', 'review_ref': 'FICTIONAL_TEST_ONLY',
            'points': [{'source_time': 10, 'output_time': 0},
                       {'source_time': 10.033, 'output_time': .04},
                       {'source_time': 10.1, 'output_time': .08},
                       {'source_time': 20, 'output_time': 5}]}
        data['candidates'] = [dict(data['candidates'][1], source_time=10.033)]
    data['music'] = None
    return data


class DecisionsTests(unittest.TestCase):
    def test_mapping_and_protection_override_exact_beat(self):
        d=fixture(); result=m.suggest(d)
        self.assertEqual(result['selected']['id'],'safe')
        self.assertEqual(result['selected']['timeline_time'],7)
        self.assertAlmostEqual(result['selected']['distance_to_music_beat'],.08)
        self.assertIn('PROTECTED_INTERIOR',result['rejected'][0]['reasons'])
        self.assertFalse(result['applied_to_plan'])

    def test_input_unchanged(self):
        d=fixture(); before=copy.deepcopy(d); m.suggest(d); self.assertEqual(d,before)

    def test_no_solution_never_forces_cut(self):
        d=fixture(); d['candidates']=d['candidates'][:1]
        self.assertIsNone(m.suggest(d)['selected'])
        d=fixture(); d['max_beat_distance']=.01
        self.assertIsNone(m.suggest(d)['selected'])

    def test_protection_boundary_allowed_not_inside(self):
        d=fixture(); d['music']=None; d['candidates']=d['candidates'][1:]
        d['candidates'][0]['source_time']=15.04
        self.assertIsNotNone(m.suggest(d)['selected'])
        d['protected'][0]['source_end']=15.04
        self.assertIsNotNone(m.suggest(d)['selected'])
        d['protected'][0]['source_end']=15.05
        self.assertIsNone(m.suggest(d)['selected'])

    def test_off_frame_rejected_without_snapping(self):
        d=fixture(); d['candidates']=d['candidates'][1:]; d['candidates'][0]['source_time']=16.01
        r=m.suggest(d); self.assertIsNone(r['selected'])
        self.assertIn('NOT_FRAME_ALIGNED',r['rejected'][0]['reasons'])

    def test_invalid_numbers(self):
        for key, values in [('fps',[True,0,29.97,float('nan')]),('max_beat_distance',[-1,False,float('inf')])]:
            for value in values:
                with self.subTest(key=key,value=value):
                    d=fixture(); d[key]=value
                    with self.assertRaises(m.Invalid): m.validate(d)
        for value in [0,-1,True,5,float('nan')]:
            d=fixture(); d['shots'][0]['speed']=value
            with self.assertRaises(m.Invalid): m.validate(d)

    def test_source_bounds_and_review_coverage(self):
        for end in [10,31]:
            d=fixture(); d['shots'][0]['source_end']=end
            with self.assertRaises(m.Invalid): m.validate(d)
        d=fixture(); d['events'][0]['evidence'][0]['source_end']=19
        with self.assertRaises(m.Invalid): m.validate(d)

    def test_reaction_must_belong_to_same_event(self):
        d=fixture(); d['shots'][0]['reaction_to_event_id']='fictional_action'; m.validate(d)
        e=copy.deepcopy(d['events'][0]); e['id']='different_event'; d['events'].append(e)
        d['shots'][0]['reaction_to_event_id']='different_event'
        with self.assertRaises(m.Invalid): m.validate(d)

    def test_music_requires_actual_declared_listening_range(self):
        d=fixture(); d['music']['listened_ranges'][0]['source_end']=12.5
        with self.assertRaises(m.Invalid): m.validate(d)
        d=fixture(); d['music']['beats']=[13,12]
        with self.assertRaises(m.Invalid): m.validate(d)

    def test_dramatic_beat_cannot_be_music_time(self):
        d=fixture(); d['candidates'][0]['dramatic_beat_id']=12
        with self.assertRaises(m.Invalid): m.validate(d)

    def test_duplicate_and_unknown_scoring_fields_rejected(self):
        d=fixture(); d['candidates'].append(copy.deepcopy(d['candidates'][0]))
        with self.assertRaises(m.Invalid): m.validate(d)
        d=fixture(); d['shots'][0]['emotion_score']=.95
        with self.assertRaises(m.Invalid): m.validate(d)

    def test_speed_and_fps_mapping(self):
        for fps in (24,25,30,50,60):
            d=fixture(); d['fps']=fps; d['music']=None; d['shots'][0]['speed']=.5
            self.assertEqual(m.suggest(d)['selected']['timeline_time'],16)

    def test_empty_candidates_and_music(self):
        d=fixture(); d['music']=None; d['candidates']=[]
        self.assertIsNone(m.suggest(d)['selected'])

    def test_ties_are_deterministic(self):
        d=fixture(); d['music']=None; c=copy.deepcopy(d['candidates'][1]); c['id']='aaa'; d['candidates'].append(c)
        self.assertEqual(m.suggest(d)['selected']['id'],'aaa')

    def test_derived_overflow_rejected(self):
        d=fixture()
        d['assets'][0]['duration']=1e308
        d['events'][0]['evidence'][0]['source_end']=1e308
        d['shots'][0]['source_end']=1e308
        d['shots'][0]['speed']=.25
        with self.assertRaises(m.Invalid): m.validate(d)
        d=fixture(); d['shots'][0]['timeline_start']=1e308
        with self.assertRaises(m.Invalid): m.validate(d)

    def test_v2_explicit_constant_preserves_v1_result(self):
        old = fixture(); old['music'] = None
        self.assertEqual(m.suggest(old), m.suggest(mapped_fixture()))

    def test_curve_mapping_integrates_speed_before_music_ranking(self):
        d = mapped_fixture('speed_curve')
        # At output-local 3 seconds, source offset is 3 + .2*3**2.
        d['candidates'] = [dict(d['candidates'][1], source_time=14.8)]
        d['protected'] = []
        d['music'] = fixture()['music']
        r = m.suggest(d)
        self.assertAlmostEqual(r['selected']['timeline_time'], 7)
        self.assertAlmostEqual(r['selected']['distance_to_music_beat'], .08)
        # Treating the average speed 2 as constant would produce 6.4.
        self.assertNotAlmostEqual(r['selected']['timeline_time'], 6.4)

    def test_curve_does_not_snap_into_protected_action(self):
        d = mapped_fixture('speed_curve')
        d['candidates'] = [dict(d['candidates'][1], source_time=14.8)]
        r = m.suggest(d)
        self.assertIsNone(r['selected'])
        self.assertIn('PROTECTED_INTERIOR', r['rejected'][0]['reasons'])

    def test_curve_off_grid_stays_rejected(self):
        d = mapped_fixture('speed_curve')
        d['protected'] = []
        d['candidates'] = [dict(d['candidates'][1], source_time=14.9)]
        self.assertIn('NOT_FRAME_ALIGNED', m.suggest(d)['rejected'][0]['reasons'])

    def test_curve_consumption_endpoints_and_fields_validated(self):
        for change in ('span', 'endpoint', 'unknown'):
            d = mapped_fixture('speed_curve')
            if change == 'span': d['shots'][0]['source_end'] = 19
            elif change == 'endpoint': d['shots'][0]['time_map']['knots'][-1]['time'] = 4
            else: d['shots'][0]['time_map']['assume_constant'] = True
            with self.subTest(change=change), self.assertRaises(m.Invalid): m.validate(d)

    def test_vfr_uses_explicit_pts_samples_not_nominal_source_fps(self):
        d = mapped_fixture('pts')
        self.assertAlmostEqual(m.suggest(d)['selected']['timeline_time'], 4.04)
        d['candidates'][0]['source_time'] = 10.1
        self.assertAlmostEqual(m.suggest(d)['selected']['timeline_time'], 4.08)
        d['candidates'][0]['source_time'] = 10.05
        with self.assertRaisesRegex(m.Invalid, 'exact PTS'): m.validate(d)

    def test_pts_requires_review_and_monotonic_frame_aligned_samples(self):
        for change in ('review', 'source_order', 'output_grid', 'end'):
            d = mapped_fixture('pts'); mapping = d['shots'][0]['time_map']
            if change == 'review': mapping['review_ref'] = ''
            elif change == 'source_order': mapping['points'][2]['source_time'] = 10.02
            elif change == 'output_grid': mapping['points'][1]['output_time'] = .041
            else: mapping['points'][-1]['output_time'] = 4.96
            with self.subTest(change=change), self.assertRaises(m.Invalid): m.validate(d)

    def test_v2_overlap_uses_declared_output_duration(self):
        d = mapped_fixture('speed_curve')
        shot = copy.deepcopy(d['shots'][0]); shot.update(shot_id='s2', timeline_start=8)
        d['shots'].append(shot)
        with self.assertRaisesRegex(m.Invalid, 'overlap'): m.validate(d)
        shot['timeline_start'] = 9
        m.validate(d)

    def test_reverse_and_freeze_require_derived_asset(self):
        for kind in ('reverse', 'freeze', 'guess_curve'):
            d = mapped_fixture(); d['shots'][0]['time_map'] = {'kind': kind}
            with self.subTest(kind=kind), self.assertRaisesRegex(m.Invalid, 'derived asset'):
                m.validate(d)


if __name__=='__main__': unittest.main()
