"""Independent reference-stem measurements of actual separator outputs.
Input manifest: {captures:[{model,track,path,sampleRate:44100,channels:1}]}
Track naming matches fixture <id>-{mix,instrumental,controlled}. No output lag,
scale, or oracle masks are corrected before scoring. SI-SDR's projection is
reported only as the conventional scale-invariant metric, beside plain SDR.
"""
import argparse,hashlib,json,math,pathlib,warnings
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly,correlate,correlation_lags
ROOT=pathlib.Path(__file__).resolve().parents[2];QA=ROOT/'qa/release-1.6.0';FIX=QA/'fixtures'
def read(path,rate=None,channels=1):
 path=pathlib.Path(path)
 if path.suffix=='.wav':
  with warnings.catch_warnings():warnings.simplefilter('ignore');r,y=wavfile.read(path)
  if y.dtype.kind in 'iu':y=y.astype(np.float64)/(2**(np.iinfo(y.dtype).bits-1))
 else:r=rate or 44100;y=np.fromfile(path,dtype='<f4').reshape((-1,channels))
 y=y.astype(np.float64);return r,y.mean(axis=1) if y.ndim>1 else y

def si_sdr(estimate,reference):
 estimate=estimate-np.mean(estimate);reference=reference-np.mean(reference);energy=np.dot(reference,reference)
 if energy<1e-15:return None
 target=reference*np.dot(estimate,reference)/energy;noise=estimate-target
 return float(10*np.log10((np.dot(target,target)+1e-15)/(np.dot(noise,noise)+1e-15)))
def sdr(estimate,reference):
 energy=np.dot(reference,reference)
 return float(10*np.log10((energy+1e-15)/(np.sum((estimate-reference)**2)+1e-15))) if energy>=1e-15 else None

def envelope(y,rate,step=.02):
 out=[]
 for at in np.arange(0,len(y)/rate,step):
  a=max(0,round((at-step/2)*rate));b=min(len(y),round((at+step/2)*rate));out.append(np.sqrt(np.mean(y[a:b]**2)) if b>a else 0)
 return np.array(out)
def pearson(a,b):return float(np.corrcoef(a,b)[0,1]) if np.std(a)>1e-10 and np.std(b)>1e-10 else 0

def score(c):
 slug,variant=c['track'].rsplit('-',1);path=pathlib.Path(c['path']);path=path if path.is_absolute() else ROOT/path
 sr,y=read(path,c.get('sampleRate'),c.get('channels',1));rate,mix=read(FIX/f"{c['track']}.wav")
 if sr!=rate:
  factor=math.gcd(sr,rate);y=resample_poly(y,rate//factor,sr//factor)
 reference=np.zeros_like(mix) if variant=='instrumental' else read(FIX/f'{slug}-{"controlled-vocals" if variant=="controlled" else "vocals"}.wav')[1]
 lengthMatch=len(y)==len(reference);n=min(len(y),len(reference),len(mix));y=y[:n];reference=reference[:n];mix=mix[:n];e=envelope(y,rate);r=envelope(reference,rate);ep=float(np.sum(y*y));mp=float(np.sum(mix*mix));rp=float(np.sum(reference*reference));sisi=si_sdr(y,reference);base=si_sdr(mix,reference)
 result={k:c[k] for k in ['model','track']};result.update({'samples':n,'sampleRate':rate,'lengthMatch':lengthMatch,'estimateSHA256':hashlib.sha256(path.read_bytes()).hexdigest(),'siSdrDb':sisi,'plainSdrDb':sdr(y,reference),'inputMixSiSdrDb':base,'siSdrImprovementDb':sisi-base if sisi is not None and base is not None else None,'vocalEnvelopeRmsPearson':pearson(e,r),'estimateToMixEnergyDb':float(10*np.log10((ep+1e-15)/(mp+1e-15))),'estimateToReferenceEnergyDb':float(10*np.log10((ep+1e-15)/(rp+1e-15))) if rp>1e-15 else None,'nonFiniteSamples':int(np.sum(~np.isfinite(y)))})
 if rp>1e-15:
  fine=envelope(y,rate,.005);refFine=envelope(reference,rate,.005);xc=correlate(fine-np.mean(fine),refFine-np.mean(refFine),method='fft');lags=correlation_lags(len(fine),len(refFine));allowed=abs(lags)<=50;i=np.argmax(xc[allowed]);result['diagnosticEnvelopeLagMs']=float(lags[allowed][i]*5)
 if slug=='seam':
  windows=json.loads((QA/'seam-fixture-provenance.json').read_text())['sourceWindows'];at=np.arange(n)/rate;outside=np.ones(n,dtype=bool)
  for a,b in windows:outside&=~((at>=a-.04)&(at<=b+.04))
  result['knownSilenceEnergyFraction']=float(np.sum(y[outside]**2)/max(ep,1e-15));result['knownSilencePeakAmplitude']=float(np.max(np.abs(y[outside]),initial=0));result['sourceWindowEnvelopeLagMs']=[]
  for a,b in windows:
   lo,hi=round(a*rate),min(n,round(b*rate));ee=envelope(y[lo:hi],rate,.005);rr=envelope(reference[lo:hi],rate,.005);cc=correlate(ee-ee.mean(),rr-rr.mean(),method='fft');ll=correlation_lags(len(ee),len(rr));ok=abs(ll)<=50;result['sourceWindowEnvelopeLagMs'].append(float(ll[ok][np.argmax(cc[ok])]*5))
 if variant=='controlled':
  at=np.arange(n)/rate;outside=~(((at>=1.21)&(at<=3.19))|((at>=4.16)&(at<=6.04)));result['outsideVoiceWindowEnergyFraction']=float(np.sum(y[outside]**2)/max(ep,1e-15));result['outsideVoiceWindowMeanAmplitude']=float(np.sqrt(np.mean(y[outside]**2)))
 for k,v in list(result.items()):
  if isinstance(v,float):result[k]=round(v,10 if 'Fraction' in k else 5)
 return result

def main():
 parser=argparse.ArgumentParser();parser.add_argument('manifest',nargs='?',default=str(QA/'separator-captures.json'));args=parser.parse_args();manifest=json.loads(pathlib.Path(args.manifest).read_text());results=[score(c) for c in manifest['captures']];summary={}
 for model in sorted({r['model'] for r in results}):
  summary[model]={}
  for variant in ['mix','instrumental','controlled']:
   rows=[r for r in results if r['model']==model and not r['track'].startswith('seam-') and r['track'].endswith('-'+variant)]
   if rows:summary[model][variant]={'tracks':len(rows),**{key:round(float(np.mean(vals)),5) for key in ['siSdrDb','plainSdrDb','siSdrImprovementDb','vocalEnvelopeRmsPearson','estimateToMixEnergyDb','outsideVoiceWindowEnergyFraction'] if (vals:=[r[key] for r in rows if r.get(key)is not None])}}
 report={'createdBy':'compare-separator-quality.py','method':'Same-clock, decoded-original-vocal-stem comparison of actual model estimates; no manual latency/gain alignment or reference-derived mask applied','limitations':['SI-SDR and envelope agreement are objective acoustic metrics, not subjective perceived sound or choreography quality.','Six short CC-licensed excerpts are not a statistically representative or verified held-out benchmark.','Original stems contain production effects and AAC artifacts. Their RMS is not a word/phrase annotation.','Low output on a no-vocal mixture is desirable, but aggressive silencing alone cannot prove good positive separation.','Diagnostic envelope lag is measured and reported without correcting output before any metric.'],'summary':summary,'results':results,'source_hashes':{str(pathlib.Path(__file__).resolve().relative_to(ROOT)):hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()}};(QA/'separator-quality-comparison.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
