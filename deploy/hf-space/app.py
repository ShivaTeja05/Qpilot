"""qPilot on a Hugging Face Space: the one page as a public sandbox (CPU only, no model).

The Space runs qPilot's own FastAPI server (``qpilot.web``) with hosted mode on: this Space's
host name, framing by huggingface.co, no launch key, a 25 MB upload cap, no language model. The
store lives in ``/tmp`` and is rebuilt on every start: the public demo study (Vermeulen 2009 /
Ruijter 2013, CC BY 4.0, SHA-256 pinned) is downloaded, walked through Studio by the scripted
person of ``qpilot studio demo --check`` and audited, in the background, while the page is up.

ZeroGPU needs one ``@spaces.GPU`` function to start; qPilot never asks for a GPU, so no quota is
used.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / "sim" / "src")]
DATA = Path(os.environ.get("QPILOT_SPACE_DATA", "/tmp/qpilot"))
SPACE_HOST = os.environ.get("SPACE_HOST", "jeevithg-qpilot.hf.space")
ENV = {
    "QPILOT_HOSTED": "1",
    "QPILOT_ALLOWED_HOSTS": SPACE_HOST,
    "QPILOT_FRAME_ANCESTORS": "https://huggingface.co",
    "QPILOT_MODEL_PROVIDER": "none",
    "QPILOT_MAX_UPLOAD_MB": "25",
    "QPILOT_CACHE_DIR": str(DATA / "cache"),
    "QPILOT_STUDIES_DIR": str(DATA / "studies"),
    "MPLBACKEND": "Agg",
    "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "sim" / "src")]),
}
for key, value in ENV.items():
    os.environ.setdefault(key, value)
# Spaces turn on Gradio's server-side rendering, whose Node server takes port 7860; qPilot serves
# its own page, so the Gradio stub must not render (or listen) itself.
os.environ["GRADIO_SSR_MODE"] = "False"

import spaces  # noqa: E402  (before anything that could touch CUDA)


@spaces.GPU
def _no_gpu_needed() -> None:
    """ZeroGPU starts only with a GPU function; qPilot's engine is plain NumPy/SciPy on CPU."""
    return None


def _prepare_demo() -> None:
    """Download, walk and audit the public demo study (about 3 minutes), then log what exists."""
    cli = [sys.executable, "-c", "import sys; from qpilot.cli import main; sys.exit(main())"]
    run = [sys.executable, "-m"]
    env = {**os.environ}
    studies = Path(os.environ["QPILOT_STUDIES_DIR"])
    try:
        subprocess.run([*cli, "fetch-demo"], env=env, check=True)
        subprocess.run(
            [*cli, "studio", "demo", "--check", "--studies", str(studies)], env=env, check=True
        )
        sessions = sorted((studies / "sessions").glob("*/studio.json"))
        study = json.loads(sessions[0].read_text())["current_study"] if sessions else None
        if study:
            subprocess.run([*run, "qpilot.integration", "audit", "--study", study], env=env)
        print("qPilot demo ready:", study, flush=True)
    except Exception as err:  # the page still works: Open says how to fetch the demo
        print("qPilot demo preparation failed:", err, flush=True)


def main() -> None:
    """Serve the one page on 0.0.0.0:7860 and prepare the demo in the background."""
    import gradio as gr
    import uvicorn

    from qpilot.core.store import StudyStore
    from qpilot.studio_service import Studio
    from qpilot.web.context import make_context
    from qpilot.web.security import launch_token
    from qpilot.web.server import create_app

    studies = Path(os.environ["QPILOT_STUDIES_DIR"])
    studies.mkdir(parents=True, exist_ok=True)
    store = StudyStore(studies)
    ctx = make_context(store, Studio(store), token=launch_token())
    app = create_app(ctx)
    with gr.Blocks(title="qPilot") as stub:  # the Space SDK's app; qPilot itself is at /
        gr.Markdown("qPilot runs at the root of this Space.")
    app = gr.mount_gradio_app(app, stub, path="/gradio", ssr_mode=False)
    threading.Thread(target=_prepare_demo, name="qpilot-demo", daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "7860")), log_level="info")


if __name__ == "__main__":
    main()
