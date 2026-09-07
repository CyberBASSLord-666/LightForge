#!/usr/bin/env python3
"""Reproduce the bundled GAME Large graphs from the author's pinned release.

Weights and this graph derivative: CC BY-NC-SA 4.0, openvpi contributors.
Only change: expose the sampler's uniform noise as an input for reproducible
inference across platforms. No weight, threshold or precision modification.
Requires onnx==1.20.1. Downloads happen at build time, never on the phone.
"""
from pathlib import Path
import hashlib, json, tempfile, urllib.request, zipfile, shutil, argparse
import onnx
ROOT=Path(__file__).resolve().parents[1]
URL='https://github.com/openvpi/GAME/releases/download/v1.0.3/GAME-1.0.3-large-onnx.zip'
SHA='8a5480539fe7d995800dc0efe149b83a1cd4f4e4a36aa2a1f7665f1765dcac08'
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--archive',type=Path);args=parser.parse_args()
    target=ROOT/'web/analysis/models/game';target.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive=args.archive or Path(tmp)/'game.zip'
        if not args.archive:urllib.request.urlretrieve(URL,archive)
        if digest(archive)!=SHA:raise ValueError('GAME archive hash mismatch')
        with zipfile.ZipFile(archive) as z:
            for name in ['config.json','encoder.onnx','segmenter.onnx','estimator.onnx','bd2dur.onnx','dur2bd.onnx']:
                (target/name).write_bytes(z.read('GAME-1.0.3-large-onnx/'+name))
        p=target/'segmenter.onnx';m=onnx.load(p)
        nodes=[n for n in m.graph.node if n.op_type=='RandomUniformLike']
        assert len(nodes)==1,'Upstream sampling graph changed'
        noise=nodes[0]
        for n in m.graph.node:
            for i,name in enumerate(n.input):
                if name==noise.output[0]:n.input[i]='random_uniform'
        m.graph.node.remove(noise)
        m.graph.input.append(onnx.helper.make_tensor_value_info('random_uniform',onnx.TensorProto.FLOAT,['B','T']))
        onnx.checker.check_model(m);onnx.save(m,p)
        files={p.name:{'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(target.iterdir()) if p.suffix in {'.onnx','.json'} and p.name!='manifest.json'}
        manifest={'id':'game-large-1.0.3-lightforge-1','name':'GAME Large','parameters':'approximately 100 million','origin':URL,'archiveSHA256':SHA,'license':'CC-BY-NC-SA-4.0','licenseURL':'https://creativecommons.org/licenses/by-nc-sa/4.0/','author':'openvpi and GAME contributors','modification':'Uniform diffusion noise supplied as an explicit deterministic input; original float32 weights unchanged.','sampleRate':44100,'frameSeconds':.01,'steps':8,'boundaryThreshold':.2,'presenceThreshold':.2,'radius':2,'files':files}
        (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(json.dumps({'model':manifest['id'],'bytes':sum(f['bytes'] for f in files.values())}))
if __name__=='__main__':main()
