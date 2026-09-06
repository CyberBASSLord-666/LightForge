"""Predeclared equal-weight waveform blend; never reads a reference stem."""
from pathlib import Path
import numpy as np,json
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];FIX=ROOT/'qa/release-1.6.0/fixtures'
entries=[]
for slug in ['nightowl','stella','meaxic','grunge','falcon','sdrnr']:
 for variant in ['mix','instrumental']:
  track=slug+'-'+variant;mdx=FIX/(track+'-mdx-separated-vocals.f32');demucs=FIX/(track+'-demucs4-separated-vocals.f32')
  if not mdx.exists() or not demucs.exists():continue
  a=np.fromfile(mdx,dtype='<f4');b=np.fromfile(demucs,dtype='<f4');assert len(a)==len(b)==300032
  output=((a+b)*.5).astype('<f4');path=FIX/(track+'-mdx-demucs4-blend50-separated-vocals.f32');output.tofile(path)
  entries.append({'model':'MDX FT + HTDemucs FT4shift fixed50/50','track':track,'path':str(path.relative_to(ROOT)),'channels':1,'sampleRate':44100,'samples':len(output),'weights':[.5,.5],'referencesRead':False})
(HERE/'demucs-mdx-blend-captures.json').write_text(json.dumps({'captures':entries},indent=2));print('Captured',len(entries),'fixed50/50 blends')
