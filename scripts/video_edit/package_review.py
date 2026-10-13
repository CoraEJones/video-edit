"""Bundle selected review evidence without relabeling its viewing scope."""
from copy import deepcopy
import hashlib
from pathlib import Path
import shutil
from .common import EditError, read, write, sha256


def bundle_review(original_plan, local_plan, local_rows, folder, plan_path):
    folder=Path(folder).resolve();base=Path(plan_path).resolve().parent
    rows={r['id']:r for r in local_rows};review=local_plan.get('review',{})
    copied={}
    media={str(Path(r.get('source_provenance',r['absolute_path'])).resolve()):r['absolute_path'] for r in local_rows}
    def copy_file(raw, ident, source_base):
        path=Path(raw);path=path if path.is_absolute() else source_base/path
        key=str(path.resolve())
        if key in media:return media[key]
        if key in copied:return copied[key]
        if not path.is_file():raise EditError('PACKAGE_REVIEW_MISSING','打包审看证据时文件缺失。',{'path':str(path)})
        prefix=hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]
        dest=folder/'evidence'/ident/(prefix+'-'+path.name);dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest)
        if sha256(path)!=sha256(dest):raise EditError('PACKAGE_REVIEW_HASH','审看证据副本哈希不一致。')
        copied[key]=str(dest);return str(dest)
    def rewrite(obj, ident, source_base):
        if isinstance(obj,list):return [rewrite(v,ident,source_base) for v in obj]
        if not isinstance(obj,dict):return obj
        out={}
        for k,v in obj.items():
            if k=='path' and isinstance(v,str):out[k]=copy_file(v,ident,source_base)
            elif k in ('contact_sheets_viewed','derived_contact_sheets_viewed') and isinstance(v,list):
                out[k]=[copy_file(p,ident,source_base) for p in v]
            else:out[k]=rewrite(v,ident,source_base)
        return out
    raw=original_plan.get('review',{}).get('analysis_path')
    if raw:
        source=Path(raw);source=source if source.is_absolute() else base/source
        analysis=deepcopy(read(source));selected=[]
        for item in analysis.get('assets',[]):
            ident=item.get('id')
            if ident not in rows:continue
            item=rewrite(item,ident,source.parent)
            item['packaging_provenance']={'original_fingerprint':item.get('fingerprint'),
                'note':'Same hash-verified source bytes; viewing scope and source seconds retained.'}
            item['fingerprint']=deepcopy(rows[ident].get('fingerprint'))
            selected.append(item)
        analysis['assets']=selected
        dest=folder/'material-analysis.json';write(dest,analysis);review['analysis_path']=str(dest)
    evidence=[]
    for item in review.get('evidence',[]):
        if isinstance(item,dict):
            ident=item.get('asset_id');evidence.append(rewrite(item,ident or 'review',base))
        elif isinstance(item,str) and (base/item).is_file():evidence.append(copy_file(item,'review',base))
        else:evidence.append(item)
    review['evidence']=evidence
    local_plan['review']=review
    return {'copied_evidence_files':len(copied),'analysis_bundled':bool(raw),
            'viewing_claims_changed':False,'selected_assets':len(rows)}
