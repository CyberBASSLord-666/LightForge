# Singing-detector candidate evaluation

EfficientAT `mn10_as` was evaluated with the authors’ original preprocessing and pretrained checkpoint. This is comparison evidence, not an app runtime dependency. The detector was not selected for short vocal phrasing because inference on three-second snippets elevated false singing/choir/chant activations on the negative fixtures. The trained frame-level Frame-MN10 model is being validated separately.

- Primary source: https://github.com/fschmid56/EfficientAT
- Source commit: `a425fdce92572e602a1d5634799bd9f1f2efa806`
- Checkpoint: https://github.com/fschmid56/EfficientAT/releases/download/v0.0.1/mn10_as_mAP_471.pt
- License: MIT; original license is included in `EfficientAT/LICENSE`.
- Evaluation program: `EfficientAT/eval_candidate.py`
- Evaluation receipt: `qa/release-1.5.0/efficientat-candidate-verification.json` in the project root.
- Checkpoint bytes were removed after evaluation because this candidate is not delivered in the APK; the receipt retains their SHA-256 and upstream loading code retrieves the same named checkpoint.

## Findings

Ten-second original model windows produced a maximum singing score of 0.1411 on the folk singing fixture, compared with 0.0014 on jazz, 0.0017 on speech and 0.00094 on percussion. At three seconds, false singing maxima increased to 0.159 on jazz and 0.122 on percussion; some choir/chant scores were higher still. The different window lengths cannot be treated as interchangeable. These are limited local fixture results, not a general accuracy benchmark or evidence for tuning a threshold to those fixtures.
