#!/usr/bin/env python3
"""Reuse numeric evidence only when every measured model/source hash is unchanged."""
import argparse,datetime,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--from-release',required=True);args=parser.parse_args()
if not all(part.isdigit() for part in args.from_release.split('.')) or len(args.from_release.split('.'))!=3:raise SystemExit('Invalid prior release')
version=json.loads((ROOT/'version.json').read_text())['name'];prior=ROOT/('qa/release-'+args.from_release+'/analysis-verification.json')
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
old=json.loads(prior.read_text());assert old['passed'] is True and not old.get('errors') and old['release']==args.from_release
assert old.get('source_hashes')
for relative,expected in old['source_hashes'].items():
    path=(ROOT/relative).resolve();assert path.is_relative_to(ROOT) and digest(path)==expected, 'Measured model/source changed: '+relative
receipt={'release':version,'passed':True,'errors':[],
 'checks':['Every source bound to the prior numeric model evaluation is byte-identical. The verified numeric evidence is retained without claiming a new evaluation.','Actual public model runtime and Android background execution require separate current release gates.'],
 'source_hashes':{**old['source_hashes'],str(prior.relative_to(ROOT)):digest(prior),'tools/verify_retained_analysis.py':digest(Path(__file__))},
 'retained_evidence':{'release':args.from_release,'path':str(prior.relative_to(ROOT)),'sha256':digest(prior)},
 'scope':'Strict unchanged-source reuse of prior numeric model evidence; not a fresh quality benchmark. Current browser/model and Android lifecycle checks are separate mandatory gates.',
 'completedAt':datetime.datetime.now(datetime.timezone.utc).isoformat()}
output=ROOT/('qa/release-'+version+'/analysis-verification.json');output.parent.mkdir(exist_ok=True);output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({'passed':True,'retained_release':args.from_release,'release':version}))
