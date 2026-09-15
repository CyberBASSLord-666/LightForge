#!/usr/bin/env python3
"""Publish an update-compatible APK only after current source-bound release gates."""
from pathlib import Path
import json, os, re, zipfile
from apk_archive import verify_native_libraries
from package_release import sha_file, sha_stream, require, atomic, atomic_copy, SIGNING_SHA256

ROOT=Path(__file__).resolve().parents[1]

def release_gate_names(version):
    gates=['regression-verification.json','browser-verification.json','native-verification.json']
    if version['code']>=20100:
        gates+=['analysis-browser-verification.json','analysis-verification.json']
    if version['code']>=20205:
        from verification_evidence_manifest import RECEIPTS as verification_receipts
        gates=list(verification_receipts)
    if version['code']>=20200:
        gates+=['android-background-verification.json']
    if version['code']>=20202:
        gates+=['android-diagnostics-verification.json']
    return gates


def main():
    version=json.loads((ROOT/'version.json').read_text());name=version['name'];qa=ROOT/('qa/release-'+name)
    evidence={}
    gates=release_gate_names(version)
    for filename in gates:
        p=qa/filename;require(p.is_file(),'Missing current release gate: '+str(p))
        data=json.loads(p.read_text());require(data.get('passed') is True and not data.get('errors') and data.get('release')==name,'Release gate did not pass: '+filename)
        require(bool(data.get('source_hashes')),'Release gate has no source binding: '+filename)
        for rel,digest in data['source_hashes'].items():
            require((ROOT/rel).is_file() and sha_file(ROOT/rel)==digest,'Source changed since '+filename+': '+rel)
        evidence[filename]={'sha256':sha_file(p),'result':data}
    apk=ROOT/'dist'/('LightForge-'+name+'.apk');receipt=json.loads(apk.with_suffix('.apk.json').read_text())
    require(sha_file(apk)==receipt['sha256'],'APK checksum changed since its build.')
    require(receipt.get('version_name')==name and receipt.get('version_code')==version['code'],'APK version does not match source.')
    require(receipt.get('update_compatible') is True and receipt.get('signing_certificate_sha256')==SIGNING_SHA256,'This APK cannot update the original LightForge installation.')
    signature=(ROOT/'build/signature-verification.txt').read_text();require('certificate SHA-256 digest: '+SIGNING_SHA256 in signature,'Original signing certificate was not verified.')
    web=[p for p in (ROOT/'web').rglob('*') if p.is_file() and not any(x.startswith('.') or x in {'node_modules','__pycache__'} for x in p.relative_to(ROOT/'web').parts)]
    with zipfile.ZipFile(apk) as z:
        verify_native_libraries(z, ROOT/'android/native-runtime.json')
        require(z.testzip() is None,'APK has a ZIP CRC failure.')
        packaged={n for n in z.namelist() if n.startswith('assets/') and not n.endswith('/')}
        expected={'assets/'+p.relative_to(ROOT/'web').as_posix() for p in web}
        require(packaged==expected,'APK asset inventory differs from current web source.')
        for p in web:
            with z.open('assets/'+p.relative_to(ROOT/'web').as_posix()) as stream:require(sha_stream(stream)==sha_file(p),'APK contains stale source: '+str(p))
    record={'release':receipt,'signing_certificate_sha256':SIGNING_SHA256,'apk_source_assets_matched':len(web),'current_release_receipts':evidence,
            'model_analysis_evidence':{'status':'Current model runtime and reference scoring are separate, source-bound gates. Quality scores are from six short reference excerpts, not a general accuracy guarantee.','path':'qa/release-'+name+'/analysis-verification.json'} if version['code']>=20100 else {'status':'Historical 1.6.0 model evidence; not a fresh accuracy measurement.','path':'qa/release-1.6.0/analysis-verification.json'},
            'physical_android_device_install_and_launch':'NOT PERFORMED','android_emulator_install_and_lifecycle':'PASSED with CI signing identity; original release signature verified separately' if version['code']>=20200 else 'NOT PERFORMED','vehicle_test':'NOT PERFORMED','browser_scope':'Chromium with actual workers/WebGL and a simulated Android bridge.'}
    record['physical_validation']={'requirement':'optional','status':'unverified','reason':'No signed physical phone or Tesla observations supplied.'}
    atomic(ROOT/'release-verification.json',(json.dumps(record,indent=2)+'\n').encode())
    out=ROOT/'output';out.mkdir(exist_ok=True);result=atomic_copy(apk,out/apk.name,receipt['sha256'])
    atomic(out/(apk.name+'.sha256'),(receipt['sha256']+'  '+apk.name+'\n').encode())
    print(json.dumps({'apk':result,'update_compatible':True,'gates':list(evidence)},indent=2))

if __name__=='__main__':main()
