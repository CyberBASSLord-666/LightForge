import urllib.request,hashlib,pathlib,json,time
from concurrent.futures import ThreadPoolExecutor
OUT=pathlib.Path(__file__).resolve().parent
TASKS=[('StemSplitio/htdemucs-ft-vocals-onnx','2ef0d757d3e226d0da85fb8c71514f464fcabdd0','htdemucs_ft_vocals.onnx','8c5d5e2da1f27050240bb80236673307ee3b40d4b064066d9350f4d64bfd544d'),('StemSplitio/htdemucs-ft-vocals-onnx','2ef0d757d3e226d0da85fb8c71514f464fcabdd0','infer.py',None),('StemSplitio/htdemucs-ft-vocals-onnx','2ef0d757d3e226d0da85fb8c71514f464fcabdd0','README.md',None),('musetric/vocal-separation-roformer-onnx','98064f6e42af945316fd96261a18f1befe3a4536','syhft_core_t1100.onnx','8b624200ac9bfc76c38fbcc9dcde3901f307acd6ee7e95b5b0a6cb3022585758'),('musetric/vocal-separation-roformer-onnx','98064f6e42af945316fd96261a18f1befe3a4536','README.md',None)]
def fetch(task):
 repo,rev,file,expected=task;dest=OUT/(repo.replace('/','--')+'--'+file);url=f'https://huggingface.co/{repo}/resolve/{rev}/{file}'
 start=time.time()
 with urllib.request.urlopen(url,timeout=90) as r,open(str(dest)+'.partial','wb') as f:
  while b:=r.read(1048576):f.write(b)
 pathlib.Path(str(dest)+'.partial').rename(dest);actual=hashlib.file_digest(open(dest,'rb'),'sha256').hexdigest()
 if expected and actual!=expected:raise ValueError('Hash mismatch')
 result={'file':str(dest),'url':url,'bytes':dest.stat().st_size,'sha256':actual,'seconds':time.time()-start};print(json.dumps(result),flush=True);return result
with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(fetch,TASKS))
(OUT/'download-receipt.json').write_text(json.dumps(results,indent=2))
