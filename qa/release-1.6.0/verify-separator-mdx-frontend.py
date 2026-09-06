"""Independent PyTorch reference for the packaged exact-geometry MDX frontend.
Run test-separator-mdx-frontend.cjs first to capture the JavaScript values.
"""
import numpy as np
import torch
import json
import pathlib
import hashlib
root=pathlib.Path(__file__).resolve().parents[2]
p=pathlib.Path(__file__).resolve().parent
x=np.stack([np.fromfile(p/'fixtures'/f'mdx-frontend-input-{c}.f32',dtype=np.float32) for c in [0,1]])
nfft=7680
hop=1024
win=torch.hann_window(nfft,periodic=True,dtype=torch.float64)
a=torch.stft(torch.tensor(x,dtype=torch.float64),n_fft=nfft,hop_length=hop,window=win,center=True,return_complex=True)
a[:,:3]=0
a[:,3072:]=0
packed=torch.view_as_real(a[:,:3072]).permute(0,3,1,2).reshape(4,3072,256).numpy().astype(np.float32)
actual=np.fromfile(p/'fixtures/mdx-frontend-encoded.f32',dtype=np.float32).reshape(4,3072,256)
diff=np.abs(actual-packed)
decoded=torch.istft(a,n_fft=nfft,hop_length=hop,window=win,center=True).mean(dim=0).numpy()
got=np.fromfile(p/'fixtures/mdx-frontend-decoded.f32',dtype=np.float32)
r={'passed':bool(diff.max()<1e-3 and np.max(np.abs(decoded-got))<1e-6),'reference':'PyTorch torch.stft/torch.istft float64, exact trained 7680-point FFT geometry','spectrumMaxAbsError':float(diff.max()),'spectrumRMSE':float(np.sqrt(np.mean(diff**2))),'decodedMaxAbsError':float(np.max(np.abs(decoded-got))),'decodedRMSE':float(np.sqrt(np.mean((decoded-got)**2))),'samples':int(len(got)),'source_hashes':{'web/analysis/separator-mdx.js':hashlib.sha256((root/'web/analysis/separator-mdx.js').read_bytes()).hexdigest()}}
print(json.dumps(r,indent=2))
(p/'separator-mdx-frontend-verification.json').write_text(json.dumps(r,indent=2))
assert r['passed']
