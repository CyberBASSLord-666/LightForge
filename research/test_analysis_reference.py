from pathlib import Path
import sys,json, numpy as np, soundfile as sf, scipy.signal, scipy.fft, onnxruntime as ort
root=Path(__file__).resolve().parents[1]
config=json.loads((root/'web/analysis/models/features.json').read_text())
audio_path=sys.argv[1] if len(sys.argv)>1 else '/workspace/scratch/9b34d7a394e6/output/Glass_Castle_Model3_2025/LightShow/lightshow.wav'
y,sr=sf.read(audio_path,dtype='float32')
assert sr==44100, 'Use the corrected 44100 Hz WAV for this reference fixture'
y=y.mean(axis=1)
y=scipy.signal.resample_poly(y,1,2).astype('float32')
# Reference uses already22050audio so resampler implementation does not obscure feature equivalence.
y.astype('float32').tofile(root/'research/test_audio22050.f32')
sf.write(root/'research/test_audio22050.wav',y,22050,subtype='PCM_16')
window=np.hanning(1411);padded=np.pad(y,(705,705))
f=np.lib.stride_tricks.sliding_window_view(padded,1411)[::441]
mag=np.abs(scipy.fft.fft(f*window)[:,:705]).astype('float32')
fb=np.zeros((705,136),dtype='float32')
for i,b in enumerate(config['bands']):fb[b['start']:b['start']+len(b['weights']),i]=b['weights']
x=np.log10(1+mag@fb).astype('float32');d=np.zeros_like(x);d[1:]=np.maximum(0,np.diff(x,axis=0));x=np.hstack((x,d))
x[:80].astype('float32').tofile(root/'research/reference_features80.f32')
s=ort.InferenceSession(str(root/'web/analysis/models/beatnet-v1.onnx'),providers=['CPUExecutionProvider']);s.disable_fallback()
h=np.zeros((2,1,150),dtype='float32');c=h.copy();p=[]
for i in range(0,len(x),500):
 out=s.run(None,{'features':x[i:i+500][None], 'h':h,'c':c});p.append(out[0][0]);h,c=out[1:]
p=np.concatenate(p);np.save(root/'research/reference_probabilities.npy',p)
print(json.dumps({'samples':len(y),'frames':len(x),'duration':len(y)/22050,'meanBeat':float(p[:,0].mean()),'maxBeat':float(p[:,0].max()),'meanDown':float(p[:,1].mean()),'maxDown':float(p[:,1].max())}))
