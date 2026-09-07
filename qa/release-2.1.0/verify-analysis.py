#!/usr/bin/env python3
"""Bind measured separator/role evidence to exact released assets.
Run after evaluate-separation.py, evaluate-roles.cjs and the parity/WASM probes.
Public-browser inference is a separate, mandatory release gate.
"""
import argparse, datetime, hashlib, json, pathlib, statistics, sys
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[2];OUT=pathlib.Path(__file__).parent
parser=argparse.ArgumentParser();parser.add_argument('--evidence-dir',type=pathlib.Path,required=True);args=parser.parse_args();lab=args.evidence_dir
sha=lambda p:hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
sources=['web/analysis/'+n for n in ['ASSET_MANIFEST.json','worker.js','separator-deux.js','game.js','vocal-detail.js','vocal.js','stem-cache.js','wav-reader.js','models/deux/manifest.json','models/game/manifest.json']]+['tools/prepare_deux.py','tools/prepare_game.py','qa/release-2.1.0/evaluate-roles.cjs','qa/release-2.1.0/verify-analysis.py','qa/release-2.1.0/test-source-clock.cjs']
receipt={'release':'2.1.0','passed':False,'errors':[],'checks':[],'source_hashes':{p:sha(ROOT/p) for p in sources},'scope':'Original-weight PyTorch separation on 18 source-reference cases with exact production context; actual JS/WASM Falcon separator parity; production role components on estimated sources. Public worker/OPFS integration is a separate gate. Not human note annotations, device performance or vehicle timing.'}
try:
 results=json.loads((lab/'deux-context-results.json').read_text());roles=json.loads((lab/'role-results.json').read_text());baseline=json.loads((ROOT/'qa/release-1.6.0/separator-quality-comparison.json').read_text());model=json.loads((ROOT/'web/analysis/models/deux/manifest.json').read_text())
 clock=json.loads((OUT/'source-clock-verification.json').read_text());assert clock['passed'] and clock['contiguousSourceSamples'] and clock['maxAbsError']<.000002
 for rel,h in clock['source_hashes'].items():assert sha(ROOT/rel)==h
 assert len(results)==len(roles)==18
 assert all(r['lengthMatch'] and r['nonFiniteSamples']==0 and r['sampleRate']==44100 for r in results)
 prior={r['track']:r for r in baseline['results'] if r['model']=='UVR MDX-Net Voc FT polarity ensemble'}
 mix=[r for r in results if r['track'].endswith('-mix')];control=[r for r in results if r['track'].endswith('-controlled')]
 assert len(mix)==len(control)==6 and all(r['siSdrDb']>prior[r['track']]['siSdrDb'] for r in mix)
 negative=[r for r in roles if r['track'].endswith('-instrumental')];positive=[r for r in roles if not r['track'].endswith('-instrumental')]
 assert len(negative)==6 and all(r['phraseCount']==r['noteCount']==r['accentCount']==0 for r in negative)
 assert len(positive)==12 and all(r['phraseCount']>0 and r['noteCount']>0 for r in positive)
 for r in roles:
  assert sha(lab/(r['track']+'-deux-vocals.wav'))==r['inputVoiceSHA256']
  assert sha(lab/(r['track']+'-deux-accompaniment.wav'))==r['inputAccompanimentSHA256']
 runtime=json.loads((lab/'deux-wasm-result.json').read_text())
 if runtime.get('graphManifestSHA256'):assert runtime['graphManifestSHA256']==sha(ROOT/'web/analysis/models/deux/manifest.json')
 for name,item in model['files'].items():
  assert item['sha256']==sha(ROOT/'web/analysis/models/deux'/name)
  if not runtime.get('graphManifestSHA256'):assert sha(lab/'deux-onnx'/name)==item['sha256']
 ref=np.load(lab/'deux-reference.npy')[0].mean(0)[66150:66150+300032]
 actual=np.fromfile(lab/'falcon-wasm-vocals.f32',dtype='<f4');assert len(actual)==len(ref) and np.isfinite(actual).all()
 maximum=float(np.max(np.abs(actual-ref)));rms=float(np.sqrt(np.mean((actual-ref)**2)))
 assert maximum<.0005 and rms<.00003
 parity=json.loads((lab/'deux-parity.json').read_text());assert parity['maxAbsError']<.0022 and parity['rmsError']<.0001
 summary={'naturalMix':{'oldMdxMeanSiSdrDb':statistics.mean(prior[r['track']]['siSdrDb'] for r in mix),'deuxMeanSiSdrDb':statistics.mean(r['siSdrDb'] for r in mix),'deuxMeanEnvelopeCorrelation':statistics.mean(r['vocalEnvelopeRmsPearson'] for r in mix)},'controlledMix':{'deuxMeanSiSdrDb':statistics.mean(r['siSdrDb'] for r in control),'deuxMeanEnvelopeCorrelation':statistics.mean(r['vocalEnvelopeRmsPearson'] for r in control),'deuxMeanOutsideVoiceEnergyFraction':statistics.mean(r['outsideVoiceWindowEnergyFraction'] for r in control),'oldMdxMeanOutsideVoiceEnergyFraction':baseline['summary']['UVR MDX-Net Voc FT polarity ensemble']['controlled']['outsideVoiceWindowEnergyFraction']},'tradeoff':'Deux improves separation SI-SDR on all six natural mixtures but has more residual estimated-voice energy outside the controlled voice windows than MDX. No universal superiority or human note accuracy is claimed.'}
 receipt.update(summary=summary,wasm={'samples':len(actual),'vocalPcmSHA256':sha(lab/'falcon-wasm-vocals.f32'),'maxAbsErrorVsOriginalModel':maximum,'rmsErrorVsOriginalModel':rms,'allGraphBytesMatchPublishedManifest':True,'singleThreadSeconds':json.loads((lab/'deux-wasm-result.json').read_text())['elapsedMs']/1000},roles={'positiveCases':len(positive),'instrumentalCasesWithZeroVoiceEvents':len(negative),'transcriptionReuse':'The unchanged GAME adapter/graphs were run once on each source estimate. Classifier, source detail and fusion were rerun after the admission fix, using source-hash-validated cached neural predictions.'},limitations=['Six short excerpts; possible training overlap; not statistically representative or verified held-out data.','Source stems are scoring references, never separator inputs. Reference estimates use the original PyTorch model with production context, not the public worker.','No human note/pitch annotations, phone installation, thermal/memory endurance or physical Tesla validation.','Bass remains a combined-accompaniment harmonic estimate.'])
 receipt['checks']=['All six natural-mixture vocal SI-SDR values improve over the declared MDX baseline.','All 18 reference outputs preserve source sample counts and finite audio.','All 12 positive role cases retain phrases and notes; all six instrument-only cases produce zero voice phrases, notes and accents.','Actual production JS/WASM output agrees with the original model within declared numeric tolerance; every graph matches the released model manifest.']
 for name in ['deux-context-results.json','deux-parity.json','deux-wasm-result.json']:(OUT/name).write_bytes((lab/name).read_bytes())
 (OUT/'role-component-results.json').write_bytes((lab/'role-results.json').read_bytes())
 receipt['evidence_hashes']={n:sha(OUT/n) for n in ['deux-context-results.json','deux-parity.json','deux-wasm-result.json','role-component-results.json','reference-evaluation-capture.txt','wasm-evaluation-capture.txt','musdb-fixture-provenance.json','source-clock-verification.json']}
 assert receipt['source_hashes']=={p:sha(ROOT/p) for p in sources}
 receipt['passed']=True
except Exception as e:receipt['errors'].append(repr(e))
receipt['completedAt']=datetime.datetime.now(datetime.timezone.utc).isoformat();(OUT/'analysis-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2));sys.exit(0 if receipt['passed'] else 1)
