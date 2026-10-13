"""Observable technique semantics; synthetic checks do not certify aesthetics."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from video_edit.common import EditError,run,sha256
from video_edit.technique_spec import validate,render,tween


class TechniqueSpecTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('VIDEO_EDIT_QA_ROOT'));self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"技巧 with spaces '";self.root.mkdir()
        self.font=ROOT/'assets/fonts/ZhiMangXing-Regular/ZhiMangXing-Regular.ttf'
        self.cfg={'font_path':str(self.font),'ffmpeg':os.environ.get('VIDEO_EDIT_FFMPEG'),'ffprobe':os.environ.get('VIDEO_EDIT_FFPROBE')}
        self.spec={'schema_version':'technique.2.0','input_space':'bt709_sdr',
            'canvas':{'width':160,'height':96,'fps':25,'duration':.2,'background_opacity':0},
            'layers':[{'id':'red','source':{'kind':'solid','color':'#FF0000'},'duration':.2}]}

    def errors(self,spec):return validate(spec,self.root,self.cfg,inspect_files=False)['errors']

    def test_invalid_types_unknown_fields_and_frame_grid_fail_before_render(self):
        for field,value in [('duration','one'),('start',float('nan')),('blend',[]),('speed',0),('opacity',2),('unknown_operator',True)]:
            spec=copy.deepcopy(self.spec);spec['layers'][0][field]=value
            with self.subTest(field=field):self.assertTrue(self.errors(spec))
        spec=copy.deepcopy(self.spec);spec['layers'][0]['start']=.01
        self.assertTrue(self.errors(spec))
        spec=copy.deepcopy(self.spec);spec['layers'][0]['keyframes']=[None]
        self.assertTrue(self.errors(spec))

    def test_semantically_unused_source_fields_are_rejected(self):
        spec=copy.deepcopy(self.spec);spec['layers'][0]['source']['path']='ignored.mp4'
        self.assertTrue(self.errors(spec))
        spec=copy.deepcopy(self.spec);spec['layers'][0]['mask']={'type':'linear','x':.2}
        self.assertTrue(self.errors(spec))
        spec=copy.deepcopy(self.spec);spec['layers'][0]['source']={'kind':'text','text':'A','font_size_px':48.5}
        self.assertTrue(self.errors(spec))
        spec=copy.deepcopy(self.spec);spec['layers'][0]['freeze_at']=0
        self.assertTrue(self.errors(spec))

    def test_last_visible_frame_keyframe_required_and_properties_inherit(self):
        spec=copy.deepcopy(self.spec)
        spec['layers'][0]['keyframes']=[{'time':0,'x':-1},{'time':.16,'x':1}]
        self.assertFalse(self.errors(spec))
        spec['layers'][0]['keyframes'][-1]['time']=.2
        self.assertTrue(self.errors(spec))
        self.assertIn('0.5',tween([{'time':0,'opacity':.5},{'time':.16,'x':1}],'opacity',1))

    def test_color_space_and_duplicate_layer_ids_explicit(self):
        spec=copy.deepcopy(self.spec);spec.pop('input_space')
        self.assertTrue(self.errors(spec))
        spec=copy.deepcopy(self.spec);spec['layers']*=2
        self.assertTrue(self.errors(spec))

    def rgba(self,path):
        data=run([self.cfg['ffmpeg'],'-v','error','-i',path,'-f','rawvideo','-pix_fmt','rgba','pipe:1']).stdout
        return np.frombuffer(data,np.uint8).reshape((-1,96,160,4))

    def make_movie(self):
        path=self.root/'six colors.mkv'
        colors=[(255,0,0),(0,255,0),(0,0,255),(255,255,0),(0,255,255),(255,0,255)]
        frames=np.array([np.tile(np.array(color,np.uint8),(96,160,1)) for color in colors])
        run([self.cfg['ffmpeg'],'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','160x96','-r','25','-i','pipe:0','-an','-c:v','ffv1','-pix_fmt','bgra','-y',path],input=frames.tobytes())
        return path

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_real_freeze_exact_source_frame_and_unchanged_original(self):
        source=self.make_movie();before=sha256(source)
        self.spec['layers']=[{'id':'held','source':{'path':str(source)},'freeze_at':.08,'duration':.2}]
        report=render(self.spec,self.root,self.cfg,self.root/'freeze')
        frames=self.rgba(report['output'])
        self.assertEqual(len(frames),5);self.assertTrue(np.all(frames==frames[0]))
        np.testing.assert_allclose(frames[0,48,80,:3],[0,0,255],atol=2)
        self.assertEqual(sha256(source),before)
        self.assertTrue(report['full_decode_verified']);self.assertFalse(report['viewed_by_agent'])

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_real_geometric_mask_feather_and_inversion(self):
        self.spec['layers'][0]['mask']={'type':'rect','width':.5,'height':.5,'feather_px':8}
        report=render(self.spec,self.root,self.cfg,self.root/'mask')
        frame=self.rgba(report['output'])[0]
        self.assertEqual(frame[48,80,3],255);self.assertEqual(frame[0,0,3],0)
        self.assertTrue(10<frame[48,40,3]<245)
        self.spec['layers'][0]['mask']['invert']=True
        inverse=self.rgba(render(self.spec,self.root,self.cfg,self.root/'mask-inverse')['output'])[0]
        self.assertEqual(inverse[48,80,3],0);self.assertEqual(inverse[0,0,3],255)
        self.assertLessEqual(int(np.max(np.abs(frame[:,:,3].astype(int)+inverse[:,:,3].astype(int)-255))),1)

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_real_opacity_animation_reaches_transparent_last_frame(self):
        self.spec['layers'][0]['keyframes']=[{'time':0,'opacity':1},{'time':.16,'opacity':0}]
        report=render(self.spec,self.root,self.cfg,self.root/'opacity')
        frames=self.rgba(report['output'])
        self.assertEqual(frames[0,48,80,3],255);self.assertEqual(frames[-1,48,80,3],0)
        self.assertTrue(np.all(np.diff(frames[:,48,80,3].astype(int))<0))

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_real_screen_blend_only_within_foreground_interval(self):
        self.spec['canvas']['background_opacity']=1
        self.spec['layers']=[{'id':'base','source':{'kind':'solid','color':'#204060'},'duration':.2},
            {'id':'screen','source':{'kind':'solid','color':'#808080'},'start':.04,'duration':.08,'blend':'screen'}]
        frames=self.rgba(render(self.spec,self.root,self.cfg,self.root/'screen')['output'])
        np.testing.assert_allclose(frames[0,48,80,:3],[32,64,96],atol=3)
        np.testing.assert_array_equal(frames[0],frames[-1])
        self.assertTrue(np.all(frames[1,48,80,:3]>frames[0,48,80,:3]))

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_real_text_alpha_mask_and_glow_asset(self):
        self.spec['layers'][0]['mask']={'type':'text','text':'夏','font_path':str(self.font),'font_size_px':48}
        frames=self.rgba(render(self.spec,self.root,self.cfg,self.root/'text-mask')['output'])
        self.assertTrue(np.any(frames[0,:,:,3]==255));self.assertTrue(np.any(frames[0,:,:,3]==0))
        self.spec['layers']=[{'id':'glow','source':{'kind':'text','text':'夏','font_path':str(self.font),'font_size_px':48,'glow_radius_px':4,'color':'#FFFFFF'},'duration':.2}]
        frames=self.rgba(render(self.spec,self.root,self.cfg,self.root/'text-glow')['output'])
        self.assertTrue(np.any((frames[0,:,:,3]>0)&(frames[0,:,:,3]<255)))

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_real_curve_compiler_matches_constant_speed_and_nonflat_changes_frames(self):
        source=self.make_movie();self.spec['canvas']['duration']=.12
        self.spec['layers']=[{'id':'ramp','source':{'path':str(source)},'duration':.12,'speed':2}]
        constant=self.rgba(render(self.spec,self.root,self.cfg,self.root/'constant')['output'])
        self.spec['layers'][0].pop('speed')
        self.spec['layers'][0]['speed_curve']=[{'time':0,'speed':2},{'time':.12,'speed':2}]
        curved=self.rgba(render(self.spec,self.root,self.cfg,self.root/'constant-curve')['output'])
        np.testing.assert_array_equal(curved,constant)
        self.spec['canvas']['duration']=.2;self.spec['layers'][0]['duration']=.2
        self.spec['layers'][0]['speed_curve']=[{'time':0,'speed':.5},{'time':.2,'speed':1.5}]
        ramp=self.rgba(render(self.spec,self.root,self.cfg,self.root/'ramp')['output'])
        self.assertEqual(len(ramp),5)
        self.assertGreaterEqual(len(np.unique(ramp[:,48,80,:3],axis=0)),3)

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_real_image_matte_multiplies_existing_alpha_and_key_removes_green(self):
        matte=self.root/'matte.png';Image.new('L',(160,96),128).save(matte)
        self.spec['layers'][0]['opacity']=.5
        self.spec['layers'][0]['mask']={'type':'asset','path':str(matte),'mode':'luma'}
        frames=self.rgba(render(self.spec,self.root,self.cfg,self.root/'matte')['output'])
        self.assertAlmostEqual(int(frames[0,48,80,3]),64,delta=2)
        self.spec['layers']=[{'id':'green','source':{'kind':'solid','color':'#00FF00'},'duration':.2,'key':{'color':'#00FF00','similarity':.1,'softness':0}}]
        keyed=self.rgba(render(self.spec,self.root,self.cfg,self.root/'key')['output'])
        self.assertTrue(np.all(keyed[:,:,:,3]==0))

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_real_color_uses_existing_lut_and_preserves_transparency(self):
        self.spec['layers'][0].update(opacity=.5,color={'saturation':0,'input_space':'bt709_sdr'})
        frames=self.rgba(render(self.spec,self.root,self.cfg,self.root/'grade')['output'])
        pixel=frames[0,48,80]
        self.assertLessEqual(int(np.max(pixel[:3]))-int(np.min(pixel[:3])),2)
        self.assertAlmostEqual(int(pixel[3]),128,delta=2)

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_known_log_tag_cannot_be_overridden_by_sdr_declaration(self):
        source=self.make_movie();tagged=self.root/'known-log.mp4'
        run([self.cfg['ffmpeg'],'-v','error','-i',source,'-an','-c:v','libx264','-pix_fmt','yuv420p','-bsf:v','h264_metadata=colour_primaries=1:transfer_characteristics=9:matrix_coefficients=1','-y',tagged])
        from video_edit.common import probe
        self.assertEqual(probe(tagged,self.cfg)['color_transfer'],'log100')
        self.spec['layers']=[{'id':'log','source':{'path':str(tagged)},'duration':.2}]
        report=validate(self.spec,self.root,self.cfg)
        self.assertFalse(report['valid']);self.assertTrue(any('Log' in e['message'] for e in report['errors']))

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_contain_respects_anamorphic_display_aspect_ratio(self):
        source=self.make_movie();anamorphic=self.root/'anamorphic.mov'
        run([self.cfg['ffmpeg'],'-v','error','-i',source,'-vf','setsar=2/1','-an','-c:v','qtrle','-y',anamorphic])
        from video_edit.common import probe
        self.assertEqual(probe(anamorphic,self.cfg)['sample_aspect_ratio'],'2:1')
        self.spec['layers']=[{'id':'anamorphic','source':{'path':str(anamorphic)},'duration':.2}]
        frame=self.rgba(render(self.spec,self.root,self.cfg,self.root/'sar')['output'])[0]
        ys,xs=np.where(frame[:,:,3]>0)
        self.assertEqual((int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1),(0,24,160,72))


if __name__=='__main__':unittest.main()
