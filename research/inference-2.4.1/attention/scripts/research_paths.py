"""Research paths: generated models/data stay in an ignored work directory."""
import os
from pathlib import Path
REPO = Path(__file__).resolve().parents[4]
MODELS = Path(os.environ.get("LIGHTFORGE_DEUX_MODELS_DIR", REPO / "web/analysis/models/deux"))
WORK = Path(os.environ.get("LIGHTFORGE_ATTENTION_WORK_DIR", REPO / "build/attention-research"))
DEMO = Path(os.environ.get("LIGHTFORGE_ATTENTION_DEMO_WAV", REPO / "web/demo/glass-castle.wav"))
WORK.mkdir(parents=True, exist_ok=True)
