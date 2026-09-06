from pathlib import Path
import numpy as np,soundfile as sf,json
r=Path(__file__).resolve().parent
p=np.load(r/'reference_probabilities.npy');y,sr=sf.read(r/'test_audio22050.wav',dtype='float32');f=np.lib.stride_tricks.sliding_window_view(np.pad(y,(705,705)),1411)[::441];rms=np.sqrt((f*f).mean(axis=1));(r/'rhythm_input.json').write_text(json.dumps({'beat':p[:,0].tolist(),'down':p[:,1].tolist(),'rms':rms.tolist()}))
