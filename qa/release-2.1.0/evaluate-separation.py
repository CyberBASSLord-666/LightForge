import sys,pathlib,time,json,importlib.util,hashlib
import argparse
parser=argparse.ArgumentParser(description='Evaluate original Deux weights with the exact production 13s context against 18 licensed reference cases.');parser.add_argument('--checkpoint',type=pathlib.Path,required=True);parser.add_argument('--output',type=pathlib.Path,required=True);args=parser.parse_args()
root=pathlib.Path(__file__).resolve().parents[2];p=args.output;p.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(root/'research/upstream/deux'))
with args.checkpoint.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()=='10255c02295bf3e3865d4ee50ff752d7b19b124ed5fd93b147babc4333eda3aa'
import torch,yaml,numpy as np,soundfile as sf
from models.bs_roformer.mel_band_roformer import MelBandRoformer
spec=importlib.util.spec_from_file_location('score',root/'qa/release-1.6.0/compare-separator-quality.py');sc=importlib.util.module_from_spec(spec);spec.loader.exec_module(sc)
torch.set_num_threads(6);cfg=yaml.load((root/'research/upstream/deux/config.yaml').read_text(),Loader=yaml.FullLoader);m=MelBandRoformer(**cfg['model']).eval();m.load_state_dict(torch.load(args.checkpoint,map_location='cpu',weights_only=True),strict=True);results=[]
for variant in ['mix','instrumental','controlled']:
 for slug in ['nightowl','stella','meaxic','grunge','falcon','sdrnr']:
  file=root/'qa/release-1.6.0/fixtures'/f'{slug}-{variant}.wav';audio,rate=sf.read(file,dtype='float32');length=len(audio);audio=np.pad(audio.T,((0,0),(66150,573300-66150-length)));start=time.time()
  with torch.inference_mode():out=m(torch.from_numpy(audio)[None])[0].numpy()
  for i,name in enumerate(['vocals','accompaniment']):
   pcm=out[i].mean(0)[66150:66150+length];sf.write(p/f'{slug}-{variant}-deux-{name}.wav',pcm,rate,subtype='FLOAT')
  r=sc.score({'model':'Deux Float32, production 13s context / 1.5s halo (PyTorch reference)','track':f'{slug}-{variant}','path':str(p/f'{slug}-{variant}-deux-vocals.wav')});r['inferenceSeconds']=time.time()-start;results.append(r);print(slug,variant,r['siSdrDb'],r['vocalEnvelopeRmsPearson'],r['estimateToMixEnergyDb'],flush=True);(p/'deux-context-results.json').write_text(json.dumps(results,indent=2))
