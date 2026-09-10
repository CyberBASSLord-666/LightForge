#!/usr/bin/env python3
"""Bounded synthetic dense-boundary memory stress; no quality or timing claim."""
from pathlib import Path
import json, os, signal, subprocess, time
ROOT=Path(__file__).resolve().parent
CEILING=int(2.5*1024**3)
CGROUP_CEILING=19*1024**3
TIMEOUT=180
watchdog=ROOT/'dense-memory-rss-watchdog.json'
watchdog.unlink(missing_ok=True)
receipt={'scope':'Original production five-model GAME pipeline, sixteen-second geometry and eight diffusion steps; synthetic dense boundaries substituted only for bd2dur/estimator allocation stress. Not an analysis output or a quality comparison.','rssCeilingBytes':CEILING,'cgroupCeilingBytes':CGROUP_CEILING,'timeoutSeconds':TIMEOUT,'boundaryStride':1,'maxObservedRssBytes':0,'status':'running'}
started=time.monotonic();started_wall=time.time()
with (ROOT/'dense-memory-demo-20s.log').open('w') as log:
    child=subprocess.Popen(['node','--require',str(ROOT/'rss-watchdog.cjs'),str(ROOT/'dense-memory.cjs'),'demo-20s'],stdout=log,stderr=subprocess.STDOUT,cwd=ROOT,env={**os.environ,'GAME_BOUNDARY_STRIDE':'1','GAME_RSS_CEILING':str(CEILING),'GAME_RSS_RECEIPT':str(watchdog)},start_new_session=True)
    receipt['pid']=child.pid
    reason=None
    while child.poll() is None:
        if watchdog.exists():
            try:
                guard=json.loads(watchdog.read_text())
                receipt['maxObservedRssBytes']=max(receipt['maxObservedRssBytes'],guard['maxObservedRssBytes'])
                if guard['safetyStop']:reason='Process RSS safety ceiling exceeded'
            except json.JSONDecodeError:pass
        current=Path('/sys/fs/cgroup/memory.current')
        if current.exists() and int(current.read_text())>CGROUP_CEILING:reason='Container memory safety ceiling exceeded'
        if time.monotonic()-started>TIMEOUT:reason='Time ceiling exceeded'
        if reason:
            receipt['status']='safety-stop';receipt['reason']=reason
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=1)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            break
        time.sleep(.025)
    receipt['returnCode']=child.wait()
receipt['wallSeconds']=time.monotonic()-started
if watchdog.exists():
    guard=json.loads(watchdog.read_text())
    receipt['watchdog']=guard
    receipt['maxObservedRssBytes']=max(receipt['maxObservedRssBytes'],guard['maxObservedRssBytes'])
    if guard['safetyStop']:receipt['status']='safety-stop';receipt['reason']='Process RSS safety ceiling exceeded'
if receipt['status']=='running':receipt['status']='completed' if receipt['returnCode']==0 else 'failed'
output=ROOT/'dense-memory-demo-20s.json'
if output.exists() and output.stat().st_mtime>=started_wall:
    result=json.loads(output.read_text())
    receipt['processReportedPeakRssBytes']=result.get('maxRss')
    inputs=json.loads((ROOT/'inputs.json').read_text())
    receipt['fixture']=next(x for x in inputs['fixtures'] if x['id']=='demo-20s')
    receipt['stressGraphs']=[x for x in result['records'] if x['type']=='synthetic-boundaries']
    receipt['estimatorGraph']=[x for x in result['records'] if x['type']=='graph' and x['name']=='estimator']
    receipt['models']=[{'name':x['name'],'sha256':x['modelSha256']} for x in result['records'] if x['type']=='load']
    receipt['graphCalls']=[x['name'] for x in result['records'] if x['type']=='graph']
    peak=max(receipt['maxObservedRssBytes'],result.get('maxRss',0))
    receipt['conservativeTwoLanePlus512MiBBytes']=2*peak+512*1024**2
    receipt['fitsFresh4GiBWith512MiBReserve']=receipt['conservativeTwoLanePlus512MiBBytes']<=4*1024**3
(ROOT/'dense-memory-safety-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2),flush=True)
