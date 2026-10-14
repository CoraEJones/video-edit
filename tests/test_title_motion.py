"""Synthetic, asymmetric-pixel tests; no user media and no UI claim."""
import math
import unittest
from pathlib import Path
import sys
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from render_titles import motion_table, transformed_image, source_geometry


def layer(**motion):
    m=dict(type='curved_path',easing='linear',enter_s=1,exit_s=.5,stagger_s=0,
        dx_px=0,dy_px=0,exit_dx_px=0,exit_dy_px=0,from_scale=1,
        from_rotation_deg=0,rotation_deg=0,overshoot_px=0,overshoot_rotation_deg=0,
        settle_s=0,cubic_bezier_points_px=[[-120,50],[-40,-80],[50,-60],[0,0]])
    m.update(motion)
    return dict(motion=m,layer_duration_s=4,start_s=0,pivot_px=[100,100],canvas_size_px=[200,200])


class MotionTests(unittest.TestCase):
    def test_source_sar_display_fit(self):
        c=dict(width=854,height=480)
        g=source_geometry(dict(width=854,height=480,sample_aspect_ratio='2:1',rotation=0),c)
        self.assertEqual((g['raster_width'],g['raster_height'],g['raster_y']),(854,240,120))
        self.assertEqual(g['native_scale_y'],.5)
        small=source_geometry(dict(width=854,height=480,sample_aspect_ratio='853:854',rotation=0),c)
        self.assertEqual((small['raster_width'],small['raster_height']),(853,480))
        self.assertAlmostEqual(small['native_scale_x'],853/854)

    def test_cubic_actual_midpoint_and_end(self):
        rows=motion_table(layer(),60)
        self.assertAlmostEqual(rows[30]['path_dx_px'],-11.25)
        self.assertAlmostEqual(rows[30]['path_dy_px'],-46.25)
        self.assertEqual(rows[60]['path_dx_px'],0)
        self.assertEqual(rows[60]['path_dy_px'],0)

    def test_overshoot_settle_has_bounded_return(self):
        rows=motion_table(layer(type='rotate_settle',dx_px=-40,from_rotation_deg=-10,
             settle_s=.4,overshoot_px=12,overshoot_rotation_deg=3),60)
        self.assertAlmostEqual(rows[60]['path_dx_px'],12)
        self.assertAlmostEqual(rows[60]['rotation_deg'],3)
        self.assertAlmostEqual(rows[84]['path_dx_px'],0)
        self.assertAlmostEqual(rows[84]['rotation_deg'],0)
        self.assertTrue(all(-40<=r['path_dx_px']<=12 for r in rows))

    def test_clockwise_positive_angle_with_asymmetric_pixels(self):
        image=Image.new('RGBA',(200,200));ImageDraw.Draw(image).rectangle((138,98,142,102),fill='white')
        row=dict(scale=1,dx_px=0,dy_px=0,rotation_deg=90,opacity=1)
        result=transformed_image(image,row,dict(width=200,height=200))
        a=result.getchannel('A');bbox=a.getbbox()
        # Rightward marker rotates downward for +90°, not upward.
        self.assertTrue(bbox[0]<103 and bbox[1]>130,bbox)
        self.assertEqual(a.getpixel((100,60)),0)

    def test_custom_pivot_stays_fixed_when_rotating(self):
        item=layer(type='rotate_settle',rotation_deg=90,from_rotation_deg=90)
        item['pivot_px']=[60,70]
        row=motion_table(item,60)[120]
        image=Image.new('RGBA',(200,200));ImageDraw.Draw(image).rectangle((58,68,62,72),fill='white')
        result=transformed_image(image,row,dict(width=200,height=200))
        x0,y0,x1,y1=result.getchannel('A').getbbox()
        self.assertLessEqual(abs((x0+x1)/2-60),1)
        self.assertLessEqual(abs((y0+y1)/2-70),1)

    def test_explicit_rotation_keyframes_override_defaults(self):
        item=layer(type='rotate_settle',rotation_keyframes=[
            dict(time_s=0,rotation_deg=-12),dict(time_s=1,rotation_deg=6),dict(time_s=2,rotation_deg=0)])
        rows=motion_table(item,60)
        self.assertEqual(rows[0]['rotation_deg'],-12)
        self.assertEqual(rows[60]['rotation_deg'],6)
        self.assertEqual(rows[120]['rotation_deg'],0)
        self.assertAlmostEqual(rows[30]['rotation_deg'],-3)

    def test_start_mid_end_alpha_are_explicit(self):
        rows=motion_table(layer(type='slide_fade'),60)
        self.assertEqual(rows[0]['opacity'],0)
        self.assertEqual(rows[120]['opacity'],1)
        self.assertGreater(rows[-1]['opacity'],0)
        self.assertLess(rows[-1]['opacity'],.05)


if __name__=='__main__':unittest.main(verbosity=2)
