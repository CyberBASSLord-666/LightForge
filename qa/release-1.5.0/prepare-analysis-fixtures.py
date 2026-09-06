#!/usr/bin/env python3
"""Prepare private supplied-audio test inputs; never changes their originals."""
from pathlib import Path
import hashlib,json,subprocess,sys,wave
p=Path(__file__).resolve().parent
upload=Path(sys.argv[1]) if len(sys.argv)>1 else p.parents[3]/'upload'
fixtures=p/'fixtures';fixtures.mkdir(exist_ok=True)
receipt={'files':[],'note':'Glass Castle has a truncated data chunk; only physically available PCM is used as a recovered-prefix test, never represented as the full song.'}
for name,target in [('Sample.wav','sample.wav'),('Glass Castle.wav','glass-castle.wav')]:
 source=upload/name;dest=fixtures/target
 with wave.open(str(source)) as w:
  declared=w.getnframes()/w.getframerate();actual=len(w.readframes(w.getnframes()))/w.getsampwidth()/w.getnchannels()/w.getframerate()
 subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source),'-ar','44100','-ac','2','-c:a','pcm_s16le',str(dest)],check=True)
 with wave.open(str(dest)) as w:duration=w.getnframes()/w.getframerate()
 receipt['files'].append({'source':name,'sourceSHA256':hashlib.sha256(source.read_bytes()).hexdigest(),'declaredSeconds':declared,'availableSeconds':actual,'truncated':actual<declared-.001,'prepared':target,'preparedSHA256':hashlib.sha256(dest.read_bytes()).hexdigest(),'preparedSeconds':duration})
with wave.open(str(fixtures/'silence.wav'),'wb') as w:w.setparams((2,2,44100,0,'NONE','not compressed'));w.writeframes(bytes(44100*2*4))
(p/'audio-fixture-provenance.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
