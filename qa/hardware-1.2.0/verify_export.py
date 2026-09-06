"""Verify the actual ZIP downloaded by the production browser export flow."""
from pathlib import Path
import dataclasses, hashlib, importlib.util, io, json, struct, subprocess, sys, wave, zipfile

root=Path(__file__).resolve().parents[2]
path=root/'qa/mobile/ui-export.zip'
spec=importlib.util.spec_from_file_location('tesla_validator',root/'research/hardware-1.2.0/commands-official-validator.py')
validator=importlib.util.module_from_spec(spec);sys.modules[spec.name]=validator;spec.loader.exec_module(validator)
with zipfile.ZipFile(path) as z:
    assert z.testzip() is None
    expected=['LightShow/lightshow.fseq','LightShow/lightshow.wav','README.txt','Validation.json','Review/LightForge_Project.json']
    assert sorted(z.namelist())==sorted(expected)
    fseq=z.read(expected[0]);audio=z.read(expected[1]);project=z.read(expected[4])
    report=json.loads(z.read(expected[3]));assert report['valid'] and not report['errors']
result=validator.validate(io.BytesIO(fseq))
with wave.open(io.BytesIO(audio)) as wav:
    assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())==(2,2,44100)
    duration=wav.getnframes()/wav.getframerate()
assert abs(result.duration_s-duration)<=result.step_time/1000+1e-6
assert audio==(root/'web/demo/glass-castle.wav').read_bytes()
offset=struct.unpack_from('<H',fseq,4)[0]
assert len(fseq)==offset+result.frame_count*200 and not any(fseq[-200:])
# Regenerate from the saved editable project, using the actual production engine.
code="const E=require(process.argv[1]);let s='';process.stdin.on('data',x=>s+=x).on('end',()=>{const p=JSON.parse(s);process.stdout.write(Buffer.from(E.fseq(E.generate(p.music,p.settings))));});"
again=subprocess.run(['node','-e',code,str(root/'web/engine/show-engine.js')],input=project,stdout=subprocess.PIPE,check=True).stdout
assert again==fseq
receipt={
    'release':'1.2.0','passed':True,
    'checks':['ZIP CRC and matching Tesla LightShow filenames','PCM16 stereo 44.1 kHz audio byte-identical to imported demo','Tesla official FSEQ format validator','Full sequence payload and terminal dark frame','Music and sequence duration within one frame','Saved project regenerates byte-identical export'],
    'files':expected,'fseq_bytes':len(fseq),'audio_sha256':hashlib.sha256(audio).hexdigest(),
    'official_validator':dataclasses.asdict(result),'errors':[]
}
(root/'qa/mobile/export-3d-release.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
