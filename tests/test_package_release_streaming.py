#!/usr/bin/env python3
"""Exercise packaging helpers only; never build or publish the release APK."""
from pathlib import Path
import hashlib,importlib.util,io,json,os,stat,tempfile,tracemalloc,unittest,zipfile
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('package_release',ROOT/'tools/package_release.py')
pack=importlib.util.module_from_spec(spec);spec.loader.exec_module(pack)

class BoundedReader(io.BytesIO):
 def read(self,size=-1):
  if size<0 or size>pack.CHUNK_BYTES:raise AssertionError('Unbounded source read')
  return super().read(size)

class PackagingStreamingTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def file(self,name,data):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
 def test_bounded_hash_and_exact_comparison(self):
  data=b'actual bytes\0'*200000
  self.assertEqual(pack.sha_stream(BoundedReader(data)),hashlib.sha256(data).hexdigest())
  self.assertTrue(pack.streams_match(BoundedReader(data),BoundedReader(data)))
  self.assertFalse(pack.streams_match(BoundedReader(data),BoundedReader(data[:-1])))
  changed=bytearray(data);changed[pack.CHUNK_BYTES+5]^=1
  self.assertFalse(pack.streams_match(BoundedReader(data),BoundedReader(changed)))
 def test_streamed_zip_preserves_manifest_permissions_and_exclusions(self):
  # Build-evidence logs are retained only for 1.6.0, with all QA exclusions intact.
  for name,expected in [('qa/release-1.6.0/build.log',True),('qa/release-1.5.0/build.log',False),
                        ('qa/release-1.6.0/fixtures/build.log',False),('qa/release-1.6.0/.private/build.log',False),
                        ('qa/release-1.6.0/node_modules/build.log',False),('qa/release-1.6.0/generated/build.log',False),
                        ('qa/release-1.6.0/example-classes/build.log',False)]:
   p=self.file('qa-selection/'+name,b'controlled build evidence')
   root=self.root/'qa-selection';qa_root=root.joinpath(*Path(name).parts[:2])
   self.assertEqual(pack.qa_distributable(p,root,qa_root),expected,name)
  source=self.root/'source';source.mkdir();files={
   'web/app.js':b'console.log("fixture");\n','signing/private.key':b'FAKE TEST KEY',
   '.hidden':b'excluded','web/.private/config.json':b'excluded',
   'web/node_modules/dependency.js':b'excluded','tools/__pycache__/test.pyc':b'excluded',
   'android/classes/Example.class':b'excluded'}
  for name,data in files.items():self.file('source/'+name,data)
  large=source/'web/model.bin';large.parent.mkdir(exist_ok=True)
  block=os.urandom(65536)
  with large.open('wb') as stream:
   for _ in range(128):stream.write(block)
  prefix='LightForge-test/'
  selected={prefix+'app/lightforge/'+p.relative_to(source).as_posix():p for p in source.rglob('*') if pack.distributable(p,source)}
  selected[prefix+'START_HERE.md']=b'# Test-only source archive\n'
  destination=self.file('result.zip',b'PREVIOUS SOURCE ARCHIVE')
  expected_names={prefix+'app/lightforge/web/app.js',prefix+'app/lightforge/web/model.bin',prefix+'app/lightforge/signing/private.key',prefix+'START_HERE.md',prefix+'SHA256SUMS.txt'}
  tracemalloc.start()
  with mock.patch.object(Path,'read_bytes',side_effect=AssertionError('Production helper must stream source bytes')):
   staged=pack.stage_source_archive(destination,prefix,selected)
  _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
  self.assertLess(peak,12*1024*1024,'Packaging an8MiB incompressible asset retained too much Python heap')
  self.assertEqual(destination.read_bytes(),b'PREVIOUS SOURCE ARCHIVE','Staging must not publish before checks finish')
  temporary=staged['temporary_path'];self.assertEqual(staged['sha256'],pack.sha_file(temporary))
  self.assertEqual(staged['entries'],len(expected_names));self.assertEqual(staged['bytes'],temporary.stat().st_size)
  with zipfile.ZipFile(temporary) as archive:
   self.assertIsNone(archive.testzip());self.assertEqual(set(archive.namelist()),expected_names)
   manifest=archive.read(prefix+'SHA256SUMS.txt').decode().splitlines()
   self.assertEqual(len(manifest),len(expected_names)-1)
   for row in manifest:
    digest,relative=row.split('  ',1)
    self.assertEqual(digest,hashlib.sha256(archive.read(prefix+relative)).hexdigest())
   self.assertEqual(archive.read(prefix+'app/lightforge/signing/private.key'),b'FAKE TEST KEY')
   self.assertEqual(stat.S_IMODE(archive.getinfo(prefix+'app/lightforge/signing/private.key').external_attr>>16),0o600)
   self.assertEqual(stat.S_IMODE(archive.getinfo(prefix+'app/lightforge/web/app.js').external_attr>>16),0o644)
   self.assertTrue(all(archive.getinfo(n).date_time==(1980,1,1,0,0,0) for n in archive.namelist()))
  os.replace(temporary,destination)
  self.assertFalse(temporary.exists())
  with zipfile.ZipFile(destination) as archive:self.assertIsNone(archive.testzip())
  print(json.dumps({'streamedFixtureBytes':large.stat().st_size,'archiveBytes':staged['bytes'],'peakPythonHeapBytes':peak,'manifestEntries':len(manifest)}))
 def test_changed_source_aborts_and_cleans_staging(self):
  source=self.file('source.dat',b'original');destination=self.file('result.zip',b'PREVIOUS')
  original=pack.sha_file
  def change_after_hash(path):
   value=original(path)
   if path==source:path.write_bytes(b'changed!')
   return value
  before=set(self.root.iterdir())
  with mock.patch.object(pack,'sha_file',side_effect=change_after_hash):
   with self.assertRaisesRegex(SystemExit,'Source changed while packaging'):
    pack.stage_source_archive(destination,'Test/',{'Test/source.dat':source})
  self.assertEqual(destination.read_bytes(),b'PREVIOUS');self.assertEqual(set(self.root.iterdir()),before)
 def test_crc_failure_never_publishes_source(self):
  source=self.file('source.dat',b'source bytes');destination=self.file('result.zip',b'PREVIOUS');before=set(self.root.iterdir())
  with mock.patch.object(zipfile.ZipFile,'testzip',return_value='Test/source.dat'):
   with self.assertRaisesRegex(SystemExit,'Source archive ZIP CRC check failed'):
    pack.stage_source_archive(destination,'Test/',{'Test/source.dat':source})
  self.assertEqual(destination.read_bytes(),b'PREVIOUS');self.assertEqual(set(self.root.iterdir()),before)
 def test_atomic_apk_copy_rejects_changed_bytes(self):
  source=self.file('built.apk',os.urandom(pack.CHUNK_BYTES+73));destination=self.file('published.apk',b'PREVIOUS APK');before=set(self.root.iterdir())
  with self.assertRaisesRegex(SystemExit,'APK changed while publishing'):
   pack.atomic_copy(source,destination,'0'*64)
  self.assertEqual(destination.read_bytes(),b'PREVIOUS APK');self.assertEqual(set(self.root.iterdir()),before)
  expected=pack.sha_file(source)
  with mock.patch.object(Path,'read_bytes',side_effect=AssertionError('APK copy must be streamed')):
   result=pack.atomic_copy(source,destination,expected)
  self.assertEqual(result,{'path':str(destination),'bytes':source.stat().st_size,'sha256':expected})
  self.assertEqual(pack.sha_file(destination),expected);self.assertEqual(set(self.root.iterdir()),before)

if __name__=='__main__':unittest.main(verbosity=2)
