"""Review evidence remains valid after the external analysis is removed."""
from copy import deepcopy
from pathlib import Path
import shutil,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from video_edit.common import write,read,EditError
from video_edit.package_review import bundle_review
from video_edit.plan import validate

class PackageReviewTests(unittest.TestCase):
    def test_selected_dense_evidence_survives_external_directory_removal(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'external';source.mkdir();dest=root/'package';dest.mkdir()
            original=source/'source.mp4';original.write_bytes(b'Synthetic structural fixture, not real playback')
            copied=dest/'source.mp4';shutil.copy2(original,copied)
            ev=[]
            for i in range(3):
                f=source/f'{i}.jpg';f.write_bytes(b'path validation fixture')
                ev.append({'kind':'frame','asset_id':'v1','path':str(f),'time':i})
            row={'id':'v1','absolute_path':str(copied),'source_provenance':str(original),'kind':'video','duration':3,'width':640,'height':360,'fps':30,'has_audio':False,'fingerprint':{'size':copied.stat().st_size,'mtime_ns':copied.stat().st_mtime_ns},'frames':[]}
            asset={'id':'v1','status':'reviewed','fingerprint':deepcopy(row['fingerprint']),'coverage':{'frame_times_viewed':[0,1,2],'contact_sheets_viewed':[ev[0]['path']]},'segments':[{'segment_id':'v1_s1','source_in':0,'source_out':2,'decision':'candidate','evidence':ev}]}
            write(source/'analysis.json',{'schema_version':'material-analysis-1.0','time_basis':'source_seconds','assets':[asset,dict(asset,id='not_selected')]})
            plan={'schema_version':'1.0','width':640,'height':360,'fps':30,'duration':2,'request':{'voiceover':False},'shots':[{'index':1,'id':'v1','segment_id':'v1_s1','source_in':0,'duration':2,'speed':1,'start':0}],'review':{'status':'reviewed','analysis_path':str(source/'analysis.json'),'evidence':ev}}
            local=deepcopy(plan);local['inventory']=[row]
            report=bundle_review(plan,local,[row],dest,source/'plan.json')
            self.assertFalse(report['viewing_claims_changed']);self.assertEqual(len(read(dest/'material-analysis.json')['assets']),1)
            shutil.rmtree(source)
            result=validate(local,dest/'plan.json',{},inspect_files=False)
            self.assertTrue(result['valid'],result)
            # Hosted Windows temp roots may be junctions; compare resolved paths.
            self.assertTrue(all(Path(e['path']).resolve().is_relative_to(dest.resolve()) for e in local['review']['evidence']))
            self.assertEqual(plan['review']['analysis_path'],str(source/'analysis.json'))

    def test_missing_evidence_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);plan={'review':{'evidence':[{'asset_id':'v1','kind':'frame','path':'missing.jpg','time':0}]}}
            with self.assertRaises(EditError):bundle_review(plan,deepcopy(plan),[],p,p/'plan.json')
