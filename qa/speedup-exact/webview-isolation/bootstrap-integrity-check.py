from pathlib import Path
import sys,json,hashlib,tempfile,shutil,io,datetime
ROOT=Path(__file__).resolve().parent.parent/'LightForge';sys.path.insert(0,str(ROOT/'tools'))
import bootstrap_androidx_runtime as b
original_dest=b.DEST; original_root=b.ROOT; original_manifest=b.MANIFEST; manifest=b.prepare(check=True)
results=[]
def rejects(name, call):
 try: call()
 except (RuntimeError,ValueError,OSError) as e: results.append({'name':name,'passed':True,'rejection':str(e)}); return
 raise AssertionError(name+' did not reject')
with tempfile.TemporaryDirectory(prefix='androidx-integrity-',dir=ROOT.parent) as temp:
 temp=Path(temp); b.DEST=temp/'androidx';shutil.copytree(original_dest,b.DEST)
 b.ROOT=temp/'project'
 for lic in manifest['licenses']:
  target=b.ROOT/lic['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original_root/lic['path'],target)
 b.MANIFEST=temp/'manifest.json';shutil.copyfile(original_manifest,b.MANIFEST)
 b.prepare(check=True); assert len(b.jar_paths())==12 and b.d8_jar() not in b.jar_paths(); results.append({'name':'Complete closure, separate compiler, preserved licenses','passed':True})
 stage=temp/'stage'; b.prepare(check=True,stage_java_resources=stage)
 assert {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()}=={r['path'] for r in manifest['javaResources']}
 for item in manifest['javaResources']: assert b._matches(stage/item['path'],item)
 results.append({'name':'All 22 APK-root Java resources staged with exact hashes','passed':True})
 rejects('Nonempty staging destination',lambda:b.prepare(check=True,stage_java_resources=stage))
 archive=b.DEST/manifest['artifacts'][0]['id']/manifest['artifacts'][0]['file']; original=archive.read_bytes();archive.write_bytes(original[:-1]+bytes([original[-1]^1]));rejects('Corrupted original AAR',lambda:b.prepare(check=True));archive.write_bytes(original)
 for name,target in [('Corrupted extracted runtime class JAR',b.jar_paths()[0]),('Corrupted compiled-resource input XML',next(b.resource_dirs()[0].rglob('*.xml'))),('Corrupted cached Java resource',b.DEST/'java-resources'/manifest['javaResources'][0]['path'])]:
  original=target.read_bytes();target.write_bytes(original+b'!');rejects(name,lambda:b.prepare(check=True));b.prepare();assert target.read_bytes()==original
 extra=b.DEST/'java-resources'/'unexpected.service';extra.write_text('unlisted');rejects('Unexpected Java resource',lambda:b.prepare(check=True));extra.unlink()
 extra=b.resource_dirs()[0]/'unexpected.xml';extra.write_text('<resources/>');rejects('Unexpected extracted resource',lambda:b.prepare(check=True));extra.unlink()
 license=b.ROOT/manifest['licenses'][0]['path'];data=license.read_bytes();license.write_bytes(data+b'!');rejects('Changed license notice',lambda:b.prepare(check=True));license.write_bytes(data)
 altered=json.loads(b.MANIFEST.read_text());altered['buildRequirements']['minSdk']=23;b.MANIFEST.write_text(json.dumps(altered));rejects('AAR minSdk disagrees with lock',lambda:b.prepare(check=True));shutil.copyfile(original_manifest,b.MANIFEST)
 stage_link=temp/'stage-link';stage_link.symlink_to(stage,target_is_directory=True);rejects('Symlink staging destination',lambda:b.prepare(check=True,stage_java_resources=stage_link))
 oldurlopen=b.urllib.request.urlopen;b.urllib.request.urlopen=lambda *args,**kwargs:io.BytesIO(b'wrong')
 try: rejects('Downloaded archive hash mismatch',lambda:b._archive(temp/'bad.jar',{'bytes':5,'sha256':'0'*64,'url':'https://dl.google.com/example','file':'bad.jar'},False));assert not (temp/'bad.jar').exists()
 finally:b.urllib.request.urlopen=oldurlopen
 b.prepare(check=True)
b.DEST=original_dest;b.ROOT=original_root;b.MANIFEST=original_manifest
receipt={'passed':True,'completedUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':results,'manifestSha256':hashlib.sha256(original_manifest.read_bytes()).hexdigest(),'bootstrapSha256':hashlib.sha256(Path(b.__file__).read_bytes()).hexdigest()}
(Path(__file__).parent/'bootstrap-integrity-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
