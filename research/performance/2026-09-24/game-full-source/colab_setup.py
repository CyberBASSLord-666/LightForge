#!/usr/bin/env python3
"""Fresh free-GPU setup using unchanged, hash-pinned original notebook cells.

Execute this once in a fresh Colab/Kaggle runtime. It never starts inference.
The resulting RUN path is passed explicitly to colab_run.py. If the same reviewed
cells have already completed, do not rerun this script: use that fresh RUN.
"""
import hashlib
import json
from pathlib import Path
import urllib.request

NOTEBOOK_COMMIT = "3d525cd16ae7688777a2ca677db7fecbf76c4e9e"
NOTEBOOK_PATH = "notebooks/LightForge_Colab_Kaggle_GAME_GPU_Qualification.ipynb"
NOTEBOOK_SHA256 = "eb274157af3ea1e6d78c5803ffe3bccbbd2765683abed6d5618746c3e6555445"
SETUP_CELLS = (2, 4, 6, 8, 10, 12, 14, 16, 18)
base = Path("/kaggle/working" if Path("/kaggle/working").is_dir() else "/content" if Path("/content").is_dir() else Path.cwd())
assert not (base / "lightforge-game-gpu-qualification").exists(), "Preserve existing setup; pass its actual RUN to colab_run.py, or use a fresh runtime."
url = f"https://raw.githubusercontent.com/CyberBASSLord-666/LightForge/{NOTEBOOK_COMMIT}/{NOTEBOOK_PATH}"
with urllib.request.urlopen(url, timeout=90) as response:
    notebook_bytes = response.read(2_000_001)
assert len(notebook_bytes) <= 2_000_000 and hashlib.sha256(notebook_bytes).hexdigest() == NOTEBOOK_SHA256
notebook = json.loads(notebook_bytes)
namespace = {"__name__": "__lightforge_pinned_setup__"}
completed = []
try:
    for index in SETUP_CELLS:
        cell = notebook["cells"][index]
        assert cell["cell_type"] == "code"
        source = "".join(cell["source"])
        print("Running unchanged setup cell", index, flush=True)
        exec(compile(source, f"{NOTEBOOK_COMMIT}/{NOTEBOOK_PATH}:cell-{index}", "exec"), namespace)
        completed.append({"index": index, "sourceSha256": hashlib.sha256(source.encode()).hexdigest()})
finally:
    if "RUN" in namespace and namespace["RUN"].is_dir():
        run = namespace["RUN"]
        (run / "setup-notebook.ipynb").write_bytes(notebook_bytes)
        (run / "setup-cell-execution.json").write_text(json.dumps({
            "schema": "lightforge.game-source-setup-cells.v1", "notebookCommit": NOTEBOOK_COMMIT,
            "notebookPath": NOTEBOOK_PATH, "notebookSha256": NOTEBOOK_SHA256,
            "completedCells": completed, "allSelectedCellsCompleted": len(completed) == len(SETUP_CELLS),
            "selectedCellsUnchanged": True, "inferenceExecuted": False,
            "qualityApproved": False, "target75Proven": False,
        }, indent=2) + "\n")
print("Fresh setup RUN:", namespace["RUN"], flush=True)
print("Setup complete. No model inference or speed/quality approval.", flush=True)
