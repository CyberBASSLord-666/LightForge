from pathlib import Path
import json,importlib.util,numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];FIX=ROOT/'qa/release-1.6.0/fixtures'
spec=importlib.util.spec_from_file_location('scorer',ROOT/'qa/release-1.6.0/compare-separator-quality.py');scorer=importlib.util.module_from_spec(spec);spec.loader.exec_module(scorer)
records=[]
for filename in ['demucs4-fixture-captures.json','demucs-mdx-blend-captures.json']:records+=json.loads((HERE/filename).read_text())['captures']
for slug in ['nightowl','stella','meaxic','grunge','falcon','sdrnr']:
 for variant in ['mix','instrumental']:
  track=slug+'-'+variant;p=FIX/(track+'-mdx-separated-vocals.f32')
  if p.exists():records.append({'model':'MDX FT production','track':track,'path':str(p),'channels':1,'sampleRate':44100})
rows=[scorer.score(c) for c in records];summary={}
for model in sorted({x['model'] for x in rows}):
 summary[model]={}
 for variant in ['mix','instrumental']:
  select=[r for r in rows if r['model']==model and r['track'].endswith('-'+variant)]
  summary[model][variant]={'tracks':len(select),**{k:float(np.mean([x[k] for x in select if x.get(k)is not None])) for k in ['siSdrDb','plainSdrDb','vocalEnvelopeRmsPearson','estimateToMixEnergyDb'] if any(x.get(k)is not None for x in select)}}
r={'summary':summary,'results':rows,'scope':'Six short same-clock reference mixtures and six matching instrumental negatives. Raw acoustic metrics; no gain/lag correction or per-song weights. Not a broad held-out benchmark or a vehicle synchronization test.'};(HERE/'final-candidate-comparison.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(summary,indent=2))
