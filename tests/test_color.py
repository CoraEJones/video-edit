"""Color mathematics, declarations, cache integrity, and real render checks.

Set VIDEO_EDIT_FFMPEG to run integration checks. LUT golden samples were
exported from the user's original generator before integration, not from the
new transform implementation. Synthetic tests do not certify aesthetic quality.
"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_edit.color import (RECIPE_PATH, apply_look, assert_native_color_supported,
                              catalog, effective_color, generate_lut, input_color_filter,
                              is_active, normalize, transform_rgb, validate_color)
from video_edit.common import EditError, read, run, sha256


class ColorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('VIDEO_EDIT_QA_ROOT'))
        self.addCleanup(self.temp.cleanup)
        # The delivery path intentionally includes spaces and Chinese text.
        self.root = Path(self.temp.name) / '调色 with spaces'
        self.root.mkdir()
        self.row = {'id': 'video', 'color_transfer': 'bt709', 'color_primaries': 'bt709', 'color_space': 'bt709'}
        self.shot = {'id': 'video', 'index': 1, 'start': 0, 'source_in': 0, 'speed': 1, 'duration': .2}
        self.plan = {'shots': [self.shot]}
        self.samples = np.array([[0,0,0],[.18,.18,.18],[.4,.25,.18],[.1,.55,.15],[.1,.3,.8],[1,1,1]])

    def errors(self, plan=None, row=None):
        errors = []
        validate_color(plan or self.plan, [row or self.row], lambda *args: errors.append(args))
        return errors

    def test_original_twenty_look_reference_samples(self):
        golden = read(RECIPE_PATH.parent / 'reference_samples.json')
        self.assertEqual(len(catalog()), 20)
        self.assertEqual(len({p['slug'] for p in catalog()}), 20)
        for recipe in catalog():
            with self.subTest(look=recipe['slug']):
                actual = apply_look(np.array(golden['input_rgb']), recipe)
                np.testing.assert_allclose(actual, golden['looks'][recipe['slug']], atol=1e-13, rtol=0)

    def test_identity_strength_zero_and_disabled(self):
        for settings in ({}, {'look': 4, 'strength': 0},
                         {'look': 4, 'enabled': False, 'exposure_ev': 2, 'saturation': .2}):
            np.testing.assert_array_equal(transform_rgb(self.samples, settings), self.samples)
        self.assertEqual(input_color_filter(self.plan, self.shot, {'source_metadata': {}}, self.root), '')
        self.assertFalse((self.root / 'assets/color').exists())

    def test_strength_mixes_only_look_after_base_correction(self):
        correction = {'exposure_ev': .4, 'white_balance': [1.05,1,.95], 'contrast': 1.05}
        base = transform_rgb(self.samples, correction)
        zero = transform_rgb(self.samples, dict(correction, look=3, strength=0))
        full = transform_rgb(self.samples, dict(correction, look=3, strength=1))
        half = transform_rgb(self.samples, dict(correction, look=3, strength=.5))
        np.testing.assert_allclose(zero, base, atol=1e-14)
        np.testing.assert_allclose(half, (base+full)/2, atol=1e-14)
        self.assertGreater(float(base[1,0]), .18)
        self.assertGreater(float(base[1,0]), float(base[1,2]))

    def test_exposure_ev_is_linear_light_multiplier(self):
        value=.18
        expected=1.099 * ((((value+.099)/1.099) ** (1/.45))*2) ** .45 - .099
        actual=transform_rgb(np.array([[value,value,value]]), {'exposure_ev': 1})
        np.testing.assert_allclose(actual, expected, atol=1e-12)

    def test_black_white_has_equal_rgb_at_full_strength(self):
        for look in (19,20):
            image=transform_rgb(self.samples, {'look': look})
            np.testing.assert_allclose(image[:,0], image[:,1], atol=1e-13)
            np.testing.assert_allclose(image[:,1], image[:,2], atol=1e-13)

    def test_inheritance_panel_override_and_disable(self):
        self.plan['color']={'look': 4, 'strength': .6, 'input_space': 'bt709_sdr'}
        self.shot['color']={'exposure_ev': .5, 'strength': .4}
        panel={'id':'video','index':1,'color':{'look':19}}
        settings=effective_color(self.plan,panel,self.shot)
        self.assertEqual(settings['look'],'monochrome_crisp')
        self.assertEqual(settings['exposure_ev'],.5)
        self.assertEqual(settings['strength'],.4)
        self.assertFalse(is_active(effective_color(self.plan,{'color':{'enabled':False}},self.shot)))

    def test_rejects_nonfinite_bool_unknown_fields_and_bad_ranges(self):
        for settings in ({'strength': float('nan')}, {'exposure_ev': float('inf')},
                         {'strength': True}, {'strength': 1.01}, {'look': 21},
                         {'look': False}, {'white_balance': [.9,1,1.26]},
                         {'white_balance': [1,1]}, {'gamma': 0}, {'contrast': 2},
                         {'temperature': 6500}, {'input_space': 'slog3'}, {'enabled': 0}):
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):normalize(settings)

    def test_unknown_input_requires_explicit_declaration_and_log_is_rejected(self):
        self.plan['color']={'look':1}
        self.assertEqual(self.errors(row={'id':'video'})[0][0], 'COLOR_INPUT_SPACE')
        self.plan['color']['input_space']='bt709_sdr'
        self.assertFalse(self.errors(row={'id':'video'}))
        self.assertEqual(self.errors(row={'id':'video','color_transfer':'log100'})[0][0], 'COLOR_INPUT_SPACE')
        self.assertFalse(self.errors())
        self.plan['color']['enabled']=False
        self.assertFalse(self.errors(row={'id':'video','color_transfer':'log100'}))

    def test_hdr_is_tonemapped_before_look_and_cannot_be_bypassed(self):
        self.plan['color']={'look':3, 'input_space':'bt709_sdr'}
        hdr={'source_metadata':{'color_transfer':'smpte2084','color_primaries':'bt2020','color_space':'bt2020nc'}}
        filters=input_color_filter(self.plan,self.shot,hdr,self.root)
        self.assertLess(filters.index('tonemap='),filters.index('lut3d='))
        incomplete={'id':'video','color_transfer':'smpte2084'}
        self.assertEqual(self.errors(row=incomplete)[0][0],'COLOR_INPUT_SPACE')

    def test_cache_is_deterministic_and_detects_tampering(self):
        path, first=generate_lut({'look':2},self.root)
        digest=sha256(path);mtime=path.stat().st_mtime_ns
        again, second=generate_lut({'look':2},self.root)
        self.assertEqual(path,again);self.assertEqual(first,second)
        self.assertEqual(path.stat().st_mtime_ns,mtime)
        path.write_bytes(b'corrupted cube')
        repaired, third=generate_lut({'look':2},self.root)
        self.assertEqual(sha256(repaired),digest)
        alternate,_=generate_lut({'look':2,'strength':.5},self.root)
        self.assertNotEqual(alternate,path)
        values=np.loadtxt(path,skiprows=5)
        self.assertEqual(values.shape,(33**3,3))
        self.assertTrue(np.isfinite(values).all())

    def test_report_records_different_per_shot_grades_and_relative_hash_paths(self):
        self.plan['color']={'look':1}
        asset={'source_metadata':self.row}
        first=input_color_filter(self.plan,self.shot,asset,self.root)
        second_shot=dict(self.shot,index=2,start=.2,color={'look':19})
        second=input_color_filter(self.plan,second_shot,asset,self.root)
        self.assertNotEqual(first,second)
        self.assertNotIn(str(self.root),first)
        self.assertIn("file='assets/color/",first)
        report=read(self.root/'color-report.json')
        self.assertEqual(len(report['clips']),2)
        for clip in report['clips']:
            self.assertEqual(clip['lut_sha256'],sha256(self.root/clip['lut']))

    def test_native_rejects_active_color_without_loading_editor(self):
        self.plan['color']={'look':1}
        with self.assertRaises(EditError) as error:assert_native_color_supported(self.plan)
        self.assertEqual(error.exception.code,'COLOR_NATIVE_UNSUPPORTED')
        self.plan['color']['strength']=0
        assert_native_color_supported(self.plan)
        self.plan['color']['exposure_ev']=1
        with self.assertRaises(EditError):assert_native_color_supported(self.plan)

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG'),'Set VIDEO_EDIT_FFMPEG for real LUT render')
    def test_real_ffmpeg_lut_strength_monochrome_and_alpha(self):
        from PIL import Image
        ffmpeg=os.environ['VIDEO_EDIT_FFMPEG']
        # 64x32: colored left half, transparent right half. CUBE interpolation
        # and alpha survive the actual filter rather than just Python math.
        pixels=np.zeros((32,64,4),np.uint8)
        pixels[:,:32]=[80,145,205,255];pixels[:,32:]=[80,145,205,0]
        source=self.root/'source.png';Image.fromarray(pixels).save(source)
        before=sha256(source)
        asset={'source_metadata':{},'kind':'image'}
        def render(settings):
            plan={'color':dict(settings,input_space='bt709_sdr')}
            prefix=input_color_filter(plan,self.shot,asset,self.root)
            raw=run([ffmpeg,'-v','error','-i',source,'-vf',prefix+'format=rgba',
                     '-frames:v',1,'-f','rawvideo','-pix_fmt','rgba','pipe:1'],cwd=self.root).stdout
            return np.frombuffer(raw,np.uint8).reshape(32,64,4)
        identity=render({'look':4,'strength':0})
        np.testing.assert_array_equal(identity,pixels)
        full=render({'look':19})
        self.assertLess(int(full[12,12,:3].max())-int(full[12,12,:3].min()),2)
        half=render({'look':19,'strength':.5})
        np.testing.assert_allclose(half[12,12,:3],(pixels[12,12,:3].astype(float)+full[12,12,:3])/2,atol=2)
        np.testing.assert_array_equal(full[:,:,3],pixels[:,:,3])
        self.assertEqual(sha256(source),before)

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG'),'Set VIDEO_EDIT_FFMPEG for real shot producer')
    def test_real_stream_producer_different_shot_corrections(self):
        from PIL import Image
        from video_edit.stream_render import producer
        ffmpeg=os.environ['VIDEO_EDIT_FFMPEG']
        source=self.root/'gray.png';Image.new('RGB',(64,32),(70,70,70)).save(source)
        before=sha256(source)
        work=self.root/'render-work';work.mkdir()
        plan=dict(self.plan,width=64,height=32,fps=25,color={'input_space':'bt709_sdr'})
        assets={'video':{'kind':'image','video':str(source),'source_metadata':{}}}
        means=[]
        for i,ev in enumerate((0,1)):
            shot=dict(self.shot,color={'exposure_ev':ev})
            cmd,_=producer(plan,assets,shot,{'ffmpeg':ffmpeg},work,i)
            raw=run(cmd,cwd=self.root).stdout
            # yuv444p10le has three equally sized planar 16-bit components.
            plane=np.frombuffer(raw,'<u2').reshape(5,3,32,64)
            means.append(float(plane[:,0].mean()))
        self.assertGreater(means[1],means[0]+40)
        self.assertEqual(sha256(source),before)

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),
                         'Set VIDEO_EDIT_FFMPEG and VIDEO_EDIT_FFPROBE for preview/final parity')
    def test_real_preview_and_final_apply_same_grade(self):
        from PIL import Image
        import wave
        from video_edit.assets import prepare_assets
        from video_edit.preview import render_preview
        from video_edit.stream_render import render
        ffmpeg=os.environ['VIDEO_EDIT_FFMPEG'];ffprobe=os.environ['VIDEO_EDIT_FFPROBE']
        source=self.root/'colored.png';Image.new('RGB',(64,32),(80,145,205)).save(source)
        rows=[{'id':'video','kind':'image','absolute_path':str(source),'duration':0,'width':64,'height':32}]
        plan=dict(self.plan,width=64,height=32,fps=25,duration=.2,
                  color={'look':4,'strength':.6,'exposure_ev':.2,'input_space':'bt709_sdr'})
        cfg={'ffmpeg':ffmpeg,'ffprobe':ffprobe,'ffmpeg_threads':2,'preview_mode':'full_quality'}
        assets=prepare_assets(plan,rows,self.root,cfg,copy_originals=False)
        with wave.open(str(self.root/'混音.wav'),'wb') as audio:
            audio.setnchannels(2);audio.setsampwidth(2);audio.setframerate(48000)
            audio.writeframes(bytes(9600*4))
        report=render(plan,assets,self.root,cfg,self.root/'final.mp4')
        preview=render_preview(plan,assets,self.root,cfg)
        def first_frame(path):
            raw=run([ffmpeg,'-v','error','-i',path,'-frames:v',1,'-f','rawvideo','-pix_fmt','rgb24','pipe:1']).stdout
            return np.frombuffer(raw,np.uint8).astype(float)
        np.testing.assert_allclose(first_frame(preview),first_frame(self.root/'final.mp4'),atol=2)
        self.assertIsNotNone(report['color_report'])
        self.assertEqual(len(read(self.root/'color-report.json')['clips']),1)


if __name__=='__main__':
    unittest.main()
