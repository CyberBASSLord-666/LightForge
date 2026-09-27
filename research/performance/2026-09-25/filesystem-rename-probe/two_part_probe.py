from pathlib import Path
import hashlib,json,os,time
ROOTS=[Path(p) for p in __import__('sys').argv[1:]]
rows=[]
def observe(root,phase,index):
    files={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mtimeNs':p.stat().st_mtime_ns,'ctimeNs':p.stat().st_ctime_ns} for p in root.glob('sample-*') if p.is_file()}
    row={'root':str(root),'phase':phase,'index':index,'timeNs':time.time_ns(),'files':files}
    rows.append(row);print(json.dumps(row),flush=True)
for root in ROOTS: root.mkdir()
for index in range(2):
    handles=[]
    for root in ROOTS:
        part=root/('sample-'+str(index)+'.partial');stream=part.open('xb');handles.append((root,part,stream))
        stream.write(bytes([31+index])*2293200);stream.flush()
        observe(root,'first_half_written_open',index)
    time.sleep(10)
    for root,part,stream in handles:
        stream.write(bytes([71+index])*2293200);stream.flush();os.fsync(stream.fileno());stream.close()
        os.replace(part,root/('sample-'+str(index)+'.bin'))
        observe(root,'immediately_after_replace',index)
    time.sleep(10)
    for root in ROOTS: observe(root,'ten_seconds_after_replace',index)
for root in ROOTS:
    with (root/'runner-receipt.json').open('x') as stream: json.dump({'rows':rows,'modelInferenceExecuted':False},stream,indent=2)
