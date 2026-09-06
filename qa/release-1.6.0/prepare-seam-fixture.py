"""Known-silence source-clock regression using existing licensed real stems."""
import hashlib,json,pathlib,warnings
import numpy as np
from scipy.io import wavfile
QA=pathlib.Path(__file__).resolve().parent;FIX=QA/'fixtures';RATE=44100;DURATION=41.531;STARTS=[2.317,11.839,22.131,33.371]
with warnings.catch_warnings():
 warnings.simplefilter('ignore');rate,mix=wavfile.read(FIX/'stella-mix.wav');_,voice=wavfile.read(FIX/'stella-vocals.wav');_,backing=wavfile.read(FIX/'stella-instrumental.wav')
assert rate==RATE
n=round(DURATION*RATE);out={k:np.zeros((n,2),np.float32) for k in ['mix','vocals','instrumental']};length=min(len(mix),len(voice),len(backing));gain=np.ones((length,1),np.float32);ramp=round(.01*RATE);gain[:ramp,0]=np.linspace(0,1,ramp);gain[-ramp:,0]=np.linspace(1,0,ramp)
windows=[]
for start in STARTS:
 at=round(start*RATE);windows.append([at/RATE,(at+length)/RATE])
 for role,pcm in [('mix',mix),('vocals',voice),('instrumental',backing)]:out[role][at:at+length]=pcm[:length]*gain
for role,pcm in out.items():wavfile.write(FIX/f'seam-{role}.wav',RATE,pcm)
receipt={'description':'Four separate copies of the original Stella excerpt at non-grid offsets, with10ms fades and exactdigital-silence gaps. A chunk/clock regression fixture, not a natural fullsong or subjective choreography evaluation.','sourceFixture':'stella','duration':n/RATE,'sampleRate':RATE,'sourceWindows':windows,'knownNoVoiceOutsideWindows':True,'derivedFiles':{f'seam-{role}.wav':hashlib.sha256((FIX/f'seam-{role}.wav').read_bytes()).hexdigest() for role in out}}
(QA/'seam-fixture-provenance.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
