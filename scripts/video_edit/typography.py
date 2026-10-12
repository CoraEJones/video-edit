"""Curated/local font selection, glyph checks, and portable font assets."""
from pathlib import Path
from functools import lru_cache
import unicodedata
from .common import *

PRESETS={'自动搭配':'auto','清爽现代':'clean','温暖手写':'warm','安静电影感':'cinema','洒脱书法':'brush'}

def fonts(cfg):
    from PIL import ImageFont
    roots=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts',Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Microsoft/Windows/Fonts']
    roots += [Path(p) for p in cfg.get('font_dirs',[])]
    bundled=ROOT/'assets/fonts';roots.append(bundled)
    entries=read(bundled/'catalog.json')['fonts'] if (bundled/'catalog.json').is_file() else []
    curated={str((bundled/r['file']).resolve()).casefold():r for r in entries}
    found={}
    for root in roots:
        if not root.is_dir():continue
        for p in sorted(root.rglob('*') if root in roots[2:] else root.iterdir()):
            if p.suffix.lower() not in ('.ttf','.ttc','.otf'):continue
            try:
                family,style=ImageFont.truetype(str(p),24).getname()
                extra=curated.get(str(p.resolve()).casefold(),{})
                if extra:family,style=extra['family'],extra['style']
                found[p.name.casefold()]={'path':str(p.resolve()),'family':family,'style':style,
                    'preview_family':extra.get('preview_family',family),
                    'id':extra.get('id',p.name),'label':extra.get('label',family),'curated':bool(extra),
                    'packable':bool(extra) or root in roots[2:-1],
                    'simplified_sample_missing':extra.get('simplified_sample_missing','')}
            except OSError:pass
    return found

@lru_cache(maxsize=96)
def _coverage(path,mtime,size):
    from fontTools.ttLib import TTFont
    with TTFont(path,fontNumber=0,lazy=True) as font:return frozenset((font.getBestCmap() or {}).keys())

@lru_cache(maxsize=24)
def _raster_face(path,mtime,size):
    from PIL import ImageFont
    return ImageFont.truetype(path,40)

def missing_glyphs(font,text):
    p=Path(font['path']);s=p.stat();coverage=_coverage(str(p),s.st_mtime_ns,s.st_size)
    chars=dict.fromkeys(c for c in text if not c.isspace() and unicodedata.category(c)!='Cf')
    face=_raster_face(str(p),s.st_mtime_ns,s.st_size)
    return ''.join(c for c in chars if ord(c) not in coverage or face.getmask(c).getbbox() is None)

def select_font(catalog,names,fallback,text,requested=None):
    candidates=[]
    if requested:
        candidates=[f for f in catalog.values() if requested.casefold() in (f['id'].casefold(),f['family'].casefold())]
        if not candidates:raise EditError('FONT_NOT_INSTALLED','没有找到所选字体，请从可用字体列表中选择。',{'font':requested})
        candidates.sort(key=lambda f:(not f['curated'],'regular' not in f['style'].casefold()))
    for name in names:
        if name.casefold() in catalog:candidates.append(catalog[name.casefold()])
    for name in (Path(fallback).name,'msyh.ttc','simsun.ttc','arial.ttf','seguisym.ttf'):
        if name.casefold() in catalog:candidates.append(catalog[name.casefold()])
    if not candidates:raise EditError('FONT_MISSING','没有找到可用字体。')
    rejected=[]
    for font in candidates:
        missing=missing_glyphs(font,text)
        if not missing:return dict(font),rejected
        rejected.append({'id':font['id'],'label':font['label'],'missing':missing})
    raise EditError('FONT_GLYPHS_MISSING','可用字体无法完整显示这段文字，请换字体或调整特殊字符。',{'text':text,'candidates':rejected})

def bundle_font(font,folder):
    """Only user supplied fonts travel; Windows fonts remain on the machine."""
    if not font.get('packable'):return font
    source=Path(font['path']);digest=sha256(source);dest=folder/'assets/fonts'/source.name
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists() and sha256(dest)!=digest:dest=dest.with_name(digest[:12]+'_'+dest.name)
    if not dest.exists():shutil.copy2(source,dest)
    notices=folder/'assets/font-notices'/digest[:12];notices.mkdir(parents=True,exist_ok=True)
    for p in source.parent.iterdir():
        if p.is_file() and p.suffix.lower() in ('.txt','.pdf'):shutil.copy2(p,notices/p.name)
    return dict(font,path=str(dest.resolve()),bundled=True,sha256=digest)

def prepare(plan,assets,folder,cfg):
    from PIL import Image
    import numpy as np
    catalog=fonts(cfg);request=plan.get('request',{})
    style=request.get('text_style','自动搭配');preset=PRESETS.get(style,style)
    if preset=='auto':
        preset='warm' if request.get('category')=='家庭' else 'clean' if request.get('rhythm')=='轻快活泼' else 'cinema'
    choices={'clean':['nishiki-teki.ttf','NotoSansSC-VF.ttf','msyh.ttc'],
        'warm':['江西拙楷2.0.ttf','ZhiMangXing-Regular.ttf','STKAITI.TTF','simkai.ttf'],
        'cinema':['汇文明朝体.otf','LingDongQiCheChunTang-2.ttf','STSONG.TTF','simsun.ttc'],
        'brush':['YunFengFeiYunTi-2.ttf','SanJiXingKaiJianTi-Cu-2.ttf','ZhiMangXing-Regular.ttf']}
    latin_choices={'clean':['Womby-Regular-2.otf','calibri.ttf'],'warm':['KaushanScript-Regular-1.otf','georgia.ttf'],
        'cinema':['happy-times-at-the-ikob-italic-2.otf','Cramaten-2.ttf','georgia.ttf'],
        'brush':['KaushanScript-Regular-1.otf','Timoteo-1.ttf','georgia.ttf']}
    subtitle_names=['msyh.ttc','NotoSansSC-Regular.otf','NotoSansSC-VF.ttf']
    decisions=[];work=folder/'typography-review';work.mkdir(exist_ok=True)
    for group in ('captions','titles'):
        for i,item in enumerate(plan.get(group,[])):
            t=(item['start']+item['end'])/2;s=next((s for s in plan['shots'] if s['start']<=t<s['start']+s['duration']),None)
            bright=False;stats={}
            if s and s['id'] in assets:
                asset=assets[s['id']];frame=work/f'{group}_{i}.jpg'
                args=[cfg['ffmpeg'],'-v','error']
                if asset['kind']!='image':args+=['-ss',s['source_in']+(t-s['start'])*s['speed']]
                args+=['-i',asset['video'],'-frames:v','1','-vf','scale=480:-2','-y',frame]
                run(args)
                with Image.open(frame) as im:
                    # Subtitles live near the bottom; titles near the centre.
                    a=np.asarray(im.convert('L'));region=a[int(len(a)*(.80 if group=='captions' else .35)):int(len(a)*(.97 if group=='captions' else .65))]
                    stats={'brightness':round(float(region.mean()),2),'texture_std':round(float(region.std()),2)}
                    bright=stats['brightness']>180 and stats['texture_std']<48
            color=[.10,.13,.15] if bright else ([.98,.95,.88] if preset in ('warm','cinema') else [.98,.98,.97])
            outline=[.98,.97,.93] if bright else [.04,.055,.07]
            from .text import text_items
            language_fonts={};fallbacks=[]
            for lang,text in text_items(item):
                latin=lang.startswith(('en','es'))
                names=(['calibri.ttf','msyh.ttc'] if latin else subtitle_names) if group=='captions' else (latin_choices if latin else choices).get(preset,choices['clean'])
                requested=item.get('font_id') or item.get('font_family')
                if latin:requested=item.get('font_family_en') or requested
                selected,rejected=select_font(catalog,names,cfg['font_path'],text,requested)
                language_fonts[lang]=bundle_font(selected,folder)
                if rejected:fallbacks.append({'language':lang,'rejected':rejected,'selected':selected['label']})
            base=next(iter(language_fonts.values()))
            if item.get('color'):color=[int(item['color'][i:i+2],16)/255 for i in (1,3,5)]
            item.setdefault('size',3.75 if group=='captions' else 10)
            item['_typography']={'font':base,'latin_font':language_fonts.get('en',base),'fonts_by_language':language_fonts,
                'color':color,'outline':outline,'border_width':2.5 if group=='captions' else 0,
                'bold':group=='titles' and preset=='clean'}
            decisions.append({'group':group,'index':i,'start':item['start'],'end':item['end'],'preset':preset,'font':base,
                'fonts_by_language':language_fonts,'fallbacks':fallbacks,'color':color,'background_sample':stats,
                'review_note':'单个抽样仅做初选，助手须复查移动背景、脸部遮挡与可读性。'})
    used=[f for d in decisions for f in d['fonts_by_language'].values()]
    family_paths={}
    for f in used:family_paths.setdefault((f['family'],f['style']),set()).add(f.get('sha256',f['path']))
    if any(len(paths)>1 for paths in family_paths.values()):raise EditError('FONT_AMBIGUOUS','同一片中使用了同名字体的不同版本，请只保留一个版本，以保证预览和工程一致。')
    write(folder/'typography-report.json',{'preset':preset,'decisions':decisions,'font_files_bundled':any(f.get('bundled') for f in used),
        'curated_font_count':sum(f['curated'] for f in catalog.values())})
    return plan

def text_style(item,caption,line,lang):
    typography=item.get('_typography',{})
    font=typography.get('fonts_by_language',{}).get(lang) or typography.get('latin_font' if lang.startswith(('en','es')) else 'font',{})
    return {'font':font,'color':typography.get('color',[.98,.97,.93]),'outline':typography.get('outline',[.04,.055,.07]),
            'border_width':typography.get('border_width',2.5),'bold':typography.get('bold',not caption),
            'size':item.get('size',3.75 if caption else 10),'y':(-.79-line*.13) if caption else item.get('y',0)}

def caption_line(plan,item,lang):
    """Two separate bilingual objects must occupy the same rows as {zh,en}."""
    languages=set()
    for other in plan.get('captions',[]):
        if min(item['end'],other['end'])<=max(item['start'],other['start']):continue
        values=[other.get('language','zh')] if other.get('text') else [k for k in ('zh','en','es') if other.get(k)]
        languages.update(v.split('-')[0] for v in values)
    ordered=sorted(languages,key=lambda v:({'zh':0,'en':1,'es':2}.get(v,3),v))
    return ordered.index(lang.split('-')[0])
