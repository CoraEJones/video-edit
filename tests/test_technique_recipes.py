"""Recipe contracts and actual temporal/spatial composition, not aesthetic scores."""
import os,sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from video_edit.technique_recipes import build
from video_edit.common import EditError
import test_technique_spec as fixture


class RecipeUnitTests(unittest.TestCase):
    def test_bad_inputs_never_silently_become_guessed_recipes(self):
        for name,params in [('freeze',{'source':'x','source_at':0,'fps':0}),('grid',{'sources':['x'],'rows':2,'columns':1}),
             ('beat-shake',{'source':'x','cues':[float('nan')]}),('danmaku',{'messages':[{'text':'x','start':'later'}],'font_path':'x'})]:
            with self.subTest(name=name),self.assertRaises((ValueError,TypeError)):build(name,params)
        with self.assertRaises(EditError):build('invented-preset',{})


class RecipeRenderTests(fixture.TechniqueSpecTests):
    # Inherit useful fixture helpers without running the parent suite twice.
    pass

for _name in list(vars(fixture.TechniqueSpecTests)):
    if _name.startswith('test_'):setattr(RecipeRenderTests,_name,None)

def _test_wipe_and_four_way_grid(self):
    from PIL import Image
    from video_edit.technique_spec import render
    colors=['#FF0000','#00FF00','#0000FF','#FFFF00'];paths=[]
    for i,color in enumerate(colors):
        path=self.root/f'color{i}.png';Image.new('RGB',(160,96),color).save(path);paths.append(str(path))
    canvas={'width':160,'height':96,'fps':25,'duration':.2}
    spec=build('compare-wipe',{'before':paths[0],'after':paths[2],**canvas})
    frames=self.rgba(render(spec,self.root,self.cfg,self.root/'wipe')['output'])
    np.testing.assert_allclose(frames[0,48,80,:3],[255,0,0],atol=2)
    np.testing.assert_allclose(frames[-1,48,80,:3],[0,0,255],atol=2)
    spec=build('grid',{'sources':paths,'rows':2,'columns':2,**canvas})
    frame=self.rgba(render(spec,self.root,self.cfg,self.root/'grid')['output'])[0]
    for (x,y),color in zip([(40,24),(120,24),(40,72),(120,72)],[(255,0,0),(0,255,0),(0,0,255),(255,255,0)]):
        np.testing.assert_allclose(frame[y,x,:3],color,atol=2)

def _test_play_then_hold_has_no_gap_and_preserves_selected_frame(self):
    from video_edit.technique_spec import render
    source=str(self.make_movie())
    spec=build('grid',{'sources':[source],'rows':1,'columns':1,'hold_at':[.08],'width':160,'height':96,'fps':25,'duration':.2})
    frames=self.rgba(render(spec,self.root,self.cfg,self.root/'playhold')['output'])
    self.assertTrue(np.all(frames[:,:,:,3]==255))
    np.testing.assert_allclose(frames[2,48,80,:3],[0,0,255],atol=2)
    np.testing.assert_array_equal(frames[2:],np.repeat(frames[2:3],3,axis=0))

_real=unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
RecipeRenderTests.test_wipe_and_four_way_grid=_real(_test_wipe_and_four_way_grid)
RecipeRenderTests.test_play_then_hold_has_no_gap_and_preserves_selected_frame=_real(_test_play_then_hold_has_no_gap_and_preserves_selected_frame)

if __name__=='__main__':unittest.main()
