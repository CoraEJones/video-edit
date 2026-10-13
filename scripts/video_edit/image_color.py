"""Explicit photograph color bridge into the technique BT.709 SDR domain.

JPEG YCbCr matrix tags describe decoding, not the RGB transfer function. A
caller must declare sRGB or select an actual embedded ICC profile; untagged
photographs are never silently certified as sRGB. This is not a Log converter.
"""
from pathlib import Path
import io
import numpy as np
from PIL import Image,ImageCms,ImageOps,PngImagePlugin
from .common import EditError,sha256,write

def convert_image(source,output,input_space):
    source=Path(source).resolve();output=Path(output).resolve();report_path=output.with_suffix('.color.json')
    if input_space not in ('srgb','embedded_icc'):raise ValueError('input_space requires srgb or embedded_icc; no guessing')
    if output.suffix.lower()!='.png':raise ValueError('Use a new PNG output to preserve alpha and avoid another JPEG generation')
    if output.exists() or report_path.exists():raise EditError('OUTPUT_EXISTS','转换输出或报告已存在，请使用新文件名。')
    digest=sha256(source)
    with Image.open(source) as opened:
        im=ImageOps.exif_transpose(opened)
        rgba=im.convert('RGBA');alpha=rgba.getchannel('A');rgb=rgba.convert('RGB');icc=im.info.get('icc_profile')
        if input_space=='embedded_icc':
            if not icc:raise ValueError('No embedded ICC profile is present')
            profile=ImageCms.ImageCmsProfile(io.BytesIO(icc))
            description=ImageCms.getProfileDescription(profile).strip()
            managed=im if im.mode in ('CMYK','L') else rgb
            rgb=ImageCms.profileToProfile(managed,profile,ImageCms.createProfile('sRGB'),outputMode='RGB')
        else:
            description=None
            if im.mode=='CMYK':raise ValueError('CMYK requires an embedded ICC transform; it is not an sRGB declaration')
            if icc:
                profile=ImageCms.ImageCmsProfile(io.BytesIO(icc));description=ImageCms.getProfileDescription(profile).strip()
                if 'srgb' not in description.casefold():raise ValueError('Embedded profile is not identified as sRGB; use embedded_icc instead of overriding it')
        encoded=np.asarray(rgb,dtype=np.float64)/255
        linear=np.where(encoded<=.04045,encoded/12.92,((encoded+.055)/1.055)**2.4)
        bt709=np.where(linear<.018,4.5*linear,1.099*linear**.45-.099)
        result=Image.fromarray(np.round(np.clip(bt709,0,1)*255).astype(np.uint8),'RGB').convert('RGBA');result.putalpha(alpha)
        output.parent.mkdir(parents=True,exist_ok=True)
        info=PngImagePlugin.PngInfo();info.add_text('video_edit_input_space','bt709_sdr')
        result.save(output,pnginfo=info)
    if sha256(source)!=digest:raise EditError('SOURCE_CHANGED','照片在转换期间变化。')
    report={'source':str(source),'source_sha256':digest,'output':str(output),'output_sha256':sha256(output),
        'input_space':input_space,'embedded_profile_description':description,
        'input_declaration_verified_by_metadata':bool(icc),'output_space':'bt709_sdr',
        'order':['decode image/JPEG into RGB','embedded ICC to sRGB if explicitly selected','sRGB EOTF to linear','BT.709 OETF','8-bit PNG quantization; alpha unchanged'],
        'original_unchanged':True,'alpha_preserved':True,'visual_reviewed':False,
        'note':'srgb without ICC is an explicit caller interpretation, not recovered camera metadata.'}
    write(report_path,report);return report
