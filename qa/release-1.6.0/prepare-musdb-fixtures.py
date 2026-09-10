"""Decode six CC-licensed public MUSDB 7s examples; keep audio QA-only.
Reference stems are acoustic references, not word/phrase or human-voicing labels.
"""
import csv,hashlib,json,pathlib,subprocess,zipfile
import numpy as np
from scipy.io import wavfile
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'qa/release-1.6.0/fixtures'
ARCHIVE=OUT/'MUSDB18-7-STEMS.zip'
TRACKS=[('nightowl','train','A Classic Education - NightOwl'),('stella','train','Clara Berry And Wooldog - Stella'),('meaxic','train','Meaxic - You Listen'),('grunge','train','Music Delta - Grunge'),('falcon','test','The Easton Ellises - Falcon 69'),('sdrnr','test','The Easton Ellises (Baumi) - SDRNR')]


def retain_or_write_provenance(path, fresh):
 """Verify regenerated fixtures without changing an immutable record's layout.

 Directory iteration and JSON key order are not fixture content. Existing
 evidence remains byte-identical only when every newly computed metadata
 field and waveform hash matches; differences fail without rewriting it.
 """
 path=pathlib.Path(path)
 if path.exists():
  recorded=json.loads(path.read_text())
  if recorded!=fresh:
   raise ValueError('Regenerated MUSDB fixtures differ from recorded provenance; do not rebaseline without reviewing the decoder, source archive and waveform hashes.')
  return False
 path.write_text(json.dumps(fresh,indent=2,sort_keys=True)+'\n')
 return True


def main():
 licenses={r['Track Name']:r for r in csv.DictReader((ROOT/'research/evaluation-1.6/musdb-tracklist.csv').open())}
 receipt={'archive':{'url':'https://github.com/sigsep/sigsep-mus-db/releases/download/v0.4.0/MUSDB18-7-STEMS.zip','sha256':hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),'bytes':ARCHIVE.stat().st_size},'limitations':['Seven-second excerpts cannot establish full-song/genre accuracy.','Model training overlap is possible: train/test below refers to the dataset split, not a held-out app evaluation.','Decoded original vocal/bass tracks contain production effects; amplitude is not a human singing or word annotation.','Audio fixtures are QA-only and excluded from APK/private source package.'],'tracks':[]}
 with zipfile.ZipFile(ARCHIVE) as z:
  for slug,split,title in TRACKS:
   meta=licenses[title];assert meta['License'].startswith('CC BY-NC-SA')
   member=f'{split}/{title}.stem.mp4';mp4=OUT/f'{slug}.stem.mp4';mp4.write_bytes(z.read(member));streams={}
   for i,name in enumerate(['mix','drums','bass','other','vocals']):
    dest=OUT/f'{slug}-{name}.wav';subprocess.run(['ffmpeg','-v','error','-y','-i',str(mp4),'-map',f'0:a:{i}','-c:a','pcm_f32le',str(dest)],check=True)
    rate,pcm=wavfile.read(dest);streams[name]=pcm
   duration=len(streams['mix'])/rate
   # Sum decoded backing stems: an objective no-vocal counterfactual from this very arrangement.
   backing=sum(streams[n] for n in ['drums','bass','other'])
   wavfile.write(OUT/f'{slug}-instrumental.wav',rate,backing.astype(np.float32))
   # A controlled real-stem remix with a known silent lead-in/out and one internal vocal gap.
   gate=np.zeros(len(backing),np.float32)
   for a,b in [(1.25,3.15),(4.2,6.0)]:
    first,last=round(a*rate),min(round(b*rate),len(gate));gate[first:last]=1
    ramp=min(round(.01*rate),(last-first)//2);gate[first:first+ramp]=np.linspace(0,1,ramp);gate[last-ramp:last]=np.linspace(1,0,ramp)
   edited=streams['vocals']*gate[:,None]
   wavfile.write(OUT/f'{slug}-controlled.wav',rate,(backing+edited).astype(np.float32));wavfile.write(OUT/f'{slug}-controlled-vocals.wav',rate,edited.astype(np.float32))
   entry={'id':slug,'title':title,'datasetSplit':split,'license':meta['License'],'source':meta['Source'],'duration':duration,'sampleRate':rate,'channels':2,'archiveMember':member,'pcmSHA256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.glob(slug+'-*.wav'))},'controlledEdit':{'vocalWindows':[[1.25,3.15],[4.2,6.0]],'edgeRampSeconds':.01,'definition':'Original vocals gated in time and summed with original drums, bass and other stems; this does not assert continuous singing throughout either window.'}}
   receipt['tracks'].append(entry)
   print(slug,duration,flush=True)
 retain_or_write_provenance(OUT.parent/'musdb-fixture-provenance.json',receipt)


if __name__=='__main__':main()
