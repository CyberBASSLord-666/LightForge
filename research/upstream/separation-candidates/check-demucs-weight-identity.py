"""Compare exported learned initializers with exact official checkpoint using weights-only loading."""
import torch,onnx,numpy as np,pathlib,fractions,json,hashlib
class CheckpointClassPlaceholder:pass
HERE=pathlib.Path(__file__).resolve().parent
p=HERE/'demucs-ft-vocals-04573f0d-f3cf25b2.th'
with torch.serialization.safe_globals([(CheckpointClassPlaceholder,'demucs.htdemucs.HTDemucs'),fractions.Fraction,(np._core.multiarray.scalar,'numpy.core.multiarray.scalar'),np.dtype,type(np.dtype('float64'))]):x=torch.load(p,map_location='cpu',weights_only=True)
print('keys',list(x),flush=True);print('statekeys',list(x.get('state',{}))[:10],flush=True)
state=x['state'];m=onnx.load(HERE/'StemSplitio--htdemucs-ft-vocals-onnx--htdemucs_ft_vocals.onnx');params={i.name:onnx.numpy_helper.to_array(i) for i in m.graph.initializer};print('onnxkeys',list(params)[:10],flush=True)
matched=[];mismatches=[];missing=[]
for key,value in state.items():
 candidates=[key,'model.'+key,'model.model.'+key]
 found=next((k for k in candidates if k in params),None)
 if found is None:missing.append(key);continue
 a=value.numpy();b=params[found]
 if a.shape==b.shape and np.array_equal(a.astype(b.dtype),b):matched.append(key)
 else:mismatches.append({'key':key,'checkpointShape':list(a.shape),'onnxShape':list(b.shape),'maxDiff':float(np.max(np.abs(a-b))) if a.shape==b.shape else None})
r={'checkpointURL':'https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/04573f0d-f3cf25b2.th','checkpointSHA256':hashlib.file_digest(open(p,'rb'),'sha256').hexdigest(),'onnxSHA256':hashlib.file_digest(open(HERE/'StemSplitio--htdemucs-ft-vocals-onnx--htdemucs_ft_vocals.onnx','rb'),'sha256').hexdigest(),'stateTensors':len(state),'matchedTensors':len(matched),'mismatches':mismatches,'unmatchedKeys':missing,'matchedKeys':matched,'method':'Match direct tensor names with optionalmodelprefix; exact float32 values. Export folding/transposedweights may remainunmatched.'}
(HERE/'demucs-weight-identity.json').write_text(json.dumps(r,indent=2));print(json.dumps({k:v for k,v in r.items() if k not in ['matchedKeys','unmatchedKeys']},indent=2),flush=True)
