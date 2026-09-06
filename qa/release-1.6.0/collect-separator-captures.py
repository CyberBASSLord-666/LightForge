"""Collect actual raw model output files, without changing their samples."""
import json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[2];QA=ROOT/'qa/release-1.6.0';captures=[]
for p in sorted((QA/'fixtures').glob('*-separated-vocals.f32')):
 stem=p.name.removesuffix('-separated-vocals.f32')
 if stem.endswith('-mdx-demucs4-blend50'):model='Fixed equal MDX/Demucs4 ensemble';track=stem.removesuffix('-mdx-demucs4-blend50')
 elif stem.endswith('-demucs4'):model='HTDemucs FT four deterministic shifts';track=stem.removesuffix('-demucs4')
 elif stem.endswith('-demucs'):model='HTDemucs FT vocals specialist';track=stem.removesuffix('-demucs')
 elif stem.endswith('-mdx-single'):model='UVR MDX-Net Voc FT single pass';track=stem.removesuffix('-mdx-single')
 elif stem.endswith('-mdx'):model='UVR MDX-Net Voc FT polarity ensemble';track=stem.removesuffix('-mdx')
 else:model='Spleeter 2 stems';track=stem
 captures.append({'model':model,'track':track,'path':str(p.relative_to(ROOT)),'sampleRate':44100,'channels':1})
(QA/'separator-captures.json').write_text(json.dumps({'captures':captures},indent=2)+'\n');print(f'{len(captures)} actual model outputs indexed')
