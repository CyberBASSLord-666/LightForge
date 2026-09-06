"""Reference-stem acoustic evaluation; metrics are NOT lyric/word ground truth.
Runs on browser inference receipts produced by capture-music-quality.cjs.
"""
import hashlib,json,pathlib,warnings
import numpy as np
from scipy.io import wavfile
from scipy.signal import find_peaks
from scipy.stats import pearsonr,spearmanr
ROOT=pathlib.Path(__file__).resolve().parents[2];QA=ROOT/'qa/release-1.6.0';FIX=QA/'fixtures';STEP=.02
TRACKS=['nightowl','stella','meaxic','grunge','falcon','sdrnr']
def rms_reference(path,duration):
 with warnings.catch_warnings():
  warnings.simplefilter('ignore');rate,x=wavfile.read(path)
 x=x.astype(np.float64);x=x.mean(axis=1) if x.ndim>1 else x
 if x.max(initial=0)>2:x/=32768
 out=[]
 for t in np.arange(0,duration,STEP):
  a=max(0,round((t-.01)*rate));b=min(len(x),round((t+.01)*rate));out.append(float(np.sqrt(np.mean(x[a:b]**2))) if b>a else 0)
 return np.array(out)
def scale(x):
 q=float(np.percentile(x,95));return np.clip(x/max(q,1e-8),0,1)
def interpolate_envelope(v,duration):
 e=np.array(v.get('envelope',[]),float);st=v.get('envelopeStep',.02)
 return np.interp(np.arange(0,duration,STEP),np.arange(len(e))*st,e,left=0,right=0) if len(e) else np.zeros(int(np.ceil(duration/STEP)))
def corr(a,b):
 if np.std(a)<1e-8 or np.std(b)<1e-8:return 0.
 return float(pearsonr(a,b).statistic)
def overlap_len(a,b,c,d):return max(0,min(b,d)-max(a,c))
def evaluate(mode,track,variant):
 p=QA/(f'detail-candidate-{track}-{variant}.json' if mode=='final_detail' else f'quality-{mode}-{track}-{variant}.json')
 if not p.exists():return None
 d=json.loads(p.read_text());v=d.get('vocals',{});duration=d['duration'];e=interpolate_envelope(v,duration);t=np.arange(len(e))*STEP
 refpath=FIX/f'{track}-{"controlled-vocals" if variant=="controlled" else "vocals"}.wav'
 ref=np.zeros(len(e)) if variant=='instrumental' else rms_reference(refpath,duration);n=min(len(e),len(ref));e=e[:n];ref=ref[:n];t=t[:n]
 confidence=np.array([any(p['start']<=tt<p['end'] for p in v.get('phrases',[])) for tt in t]);active=ref>max(np.percentile(ref,95)*.0316228,1e-5)
 positive=int(np.sum(confidence&active));fp=int(np.sum(confidence&~active));fn=int(np.sum(~confidence&active));precision=positive/max(1,positive+fp);recall=positive/max(1,positive+fn)
 result={'track':track,'variant':variant,'duration':duration,'detected':v.get('presence')=='detected','phraseCount':len(v.get('phrases',[])),'accentCount':len(v.get('accents',[])),'noteCount':len(v.get('notes',[])),'envelopeStemRmsPearson':round(corr(e,ref),4),'normalizedEnvelopeRMSE':round(float(np.sqrt(np.mean((scale(e)-scale(ref))**2))),4),'activeStemPrecision':round(precision,4),'activeStemRecall':round(recall,4),'activeStemF1':round(2*precision*recall/max(1e-8,precision+recall),4),'falseActiveSeconds':round(fp*STEP,3),'missedActiveSeconds':round(fn*STEP,3),'analysisSeconds':round(d['captureSeconds'],3) if 'captureSeconds' in d else None}
 if variant=='controlled':
  windows=[[1.25,3.15],[4.2,6.0]];outside=np.array([not any(a-.04<=tt<=b+.04 for a,b in windows) for tt in t]);result['outsideKnownVocalWindowsSeconds']=round(float(np.sum(confidence&outside)*STEP),3);result['outsideKnownVocalWindowsEnvelopeMass']=round(float(np.sum(e[outside])/max(1e-8,np.sum(e))),4)
  edges=[]
  for a,b in windows:
   matching=[p for p in v.get('phrases',[]) if overlap_len(p['start'],p['end'],a,b)>.1]
   edges.append({'knownWindow':[a,b],'detected':bool(matching),'entryOffsetMs':round((min(p['start'] for p in matching)-a)*1000,1) if matching else None,'releaseOffsetMs':round((max(p['end'] for p in matching)-b)*1000,1) if matching else None})
  result['controlledWindowEdges']=edges
 return result
results={mode:[r for tr in TRACKS for variant in ['mix','instrumental','controlled'] if (r:=evaluate(mode,tr,variant))] for mode in ['baseline','studio','final_detail','final']}
aggregates={}
for mode,rows in results.items():
 for variant in ['mix','instrumental','controlled']:
  subset=[r for r in rows if r['variant']==variant]
  if subset:aggregates[f'{mode}-{variant}']={'tracks':len(subset),'singingDetectedTracks':sum(r['detected'] for r in subset),'tracksWithVoiceCues':sum(r['phraseCount']>0 for r in subset),'accents':sum(r['accentCount'] for r in subset),'notes':sum(r['noteCount'] for r in subset),'meanEnvelopeStemRmsPearson':round(float(np.mean([r['envelopeStemRmsPearson'] for r in subset])),4),'meanActiveStemF1':round(float(np.mean([r['activeStemF1'] for r in subset])),4),'falseActiveSeconds':round(sum(r['falseActiveSeconds'] for r in subset),3),'outsideKnownVocalWindowsSeconds':round(sum(r.get('outsideKnownVocalWindowsSeconds',0) for r in subset),3)}
limitations=['Original stems are acoustic references; RMS agreement is not word, syllable, pitch or human-listener accuracy.','Active-stem threshold is relative -30dB from each reference stem95th-percentile RMS with an absolute1e-5floor; reverb/unvoiced consonants/bleed may affect it.','Controlled remixes preserve real voice and backing audio but deliberately edit vocal entry/exit windows; results are not full natural-song segmentation accuracy.','Six7second excerpts plus the separate genre negatives are too small for broad professional/music-understanding claims.','Dataset split does not guarantee model-held-out evaluation; source separator and classifier training overlap may exist.','No perceptual listening panel, phone or physical Tesla was used for these measurements.']
report={'complete':len(results['final_detail'])==18,'createdBy':'evaluate-musical-detail.py','runScopes':{'baseline':'Frozen1.5 classifier on original mixture.','studio':'Initial full public-worker pass; early cases predate final vocal fallback and remain as audit evidence.','final_detail':'Final production downsampler/classifier/detail replay from actual recorded MDX estimates; no original reference stem is given to production.','final':'Final public-worker regression on originally missed controlled NightOwl voice.'},'referenceMethod':'20ms centered RMS of original MUSDB18 vocal stem, no timing optimization against app output','limitations':limitations,'aggregates':aggregates,'results':results,'source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [pathlib.Path(__file__).resolve(),QA/'musdb-fixture-provenance.json']}}
(QA/'musical-detail-comparison.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(aggregates,indent=2))
