from pathlib import Path
import hashlib,json,os,time
ROOTS=[Path(p) for p in __import__('sys').argv[1:]]
rows=[]
def observe(root,phase,index):
    files={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in root.glob('sample-*') if p.is_file()}
    row={'root':str(root),'phase':phase,'index':index,'timeNs':time.time_ns(),'files':files}
    rows.append(row)
    print(json.dumps(row),flush=True)
for index in range(3):
    payload=(('public-synthetic-round-'+str(index)+'|').encode()*50000)[:1000003]
    for root in ROOTS:
        part=root/('sample-'+str(index)+'.partial')
        with part.open('xb') as stream:
            stream.write(payload);stream.flush();os.fsync(stream.fileno())
        observe(root,'created',index)
    time.sleep(5)
    for root in ROOTS:
        part=root/('sample-'+str(index)+'.partial'); final=root/('sample-'+str(index)+'.bin')
        os.replace(part,final)
        observe(root,'immediately_after_replace',index)
    time.sleep(10)
    for root in ROOTS: observe(root,'ten_seconds_after_replace',index)
for root in ROOTS:
    with (root/'runner-receipt.json').open('x') as stream: json.dump({'rows':rows,'modelInferenceExecuted':False},stream,indent=2)
