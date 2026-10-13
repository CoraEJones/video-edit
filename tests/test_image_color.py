import hashlib,sys,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageCms
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from video_edit.image_color import convert_image
from video_edit.common import EditError

class ImageColorTests(unittest.TestCase):
    def test_explicit_srgb_transfer_preserves_alpha_and_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.png';output=root/'converted.png'
            im=Image.new('RGBA',(3,1));im.putdata([(0,0,0,0),(128,128,128,73),(255,255,255,255)]);im.save(source)
            before=hashlib.sha256(source.read_bytes()).hexdigest();report=convert_image(source,output,'srgb')
            with Image.open(output) as actual:self.assertEqual(np.asarray(actual).reshape(-1,4).tolist(),[[0,0,0,0],[115,115,115,73],[255,255,255,255]])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
            self.assertFalse(report['input_declaration_verified_by_metadata'])
            with self.assertRaises(EditError):convert_image(source,output,'srgb')

    def test_icc_requires_actual_profile_and_unknown_space_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.png';Image.new('RGB',(2,2),'red').save(source)
            with self.assertRaises(ValueError):convert_image(source,root/'missing.png','embedded_icc')
            with self.assertRaises(ValueError):convert_image(source,root/'guessed.png','unknown')
            profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
            Image.new('RGB',(2,2),'red').save(source,icc_profile=profile)
            report=convert_image(source,root/'icc.png','embedded_icc')
            self.assertTrue(report['input_declaration_verified_by_metadata'])

    def test_exif_display_orientation_survives_color_conversion(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'rotated.png';output=root/'display.png'
            image=Image.fromarray(np.array([[[255,0,0],[0,0,255]]],dtype=np.uint8));exif=Image.Exif();exif[274]=3;image.save(source,exif=exif)
            convert_image(source,output,'srgb')
            with Image.open(output) as actual:self.assertEqual(actual.getpixel((0,0)),(0,0,255,255));self.assertEqual(actual.getpixel((1,0)),(255,0,0,255))

if __name__=='__main__':unittest.main()
