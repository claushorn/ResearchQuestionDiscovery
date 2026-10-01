import threading
import webbrowser
from pathlib import Path

import typer
import uvicorn

from frontend.app import create_app
from frontend.config import DEFAULT_ROOT, load_config
from rqd.cli import clean_errors

app = typer.Typer(help="Frontend: local web app over the pipeline's stores; runs stages as Agent Tasks.")


@app.command()
@clean_errors
def main(root: Path = typer.Option(DEFAULT_ROOT, "--root", help="Frontend directory (config.yaml, data/)"),
         port: int = typer.Option(None, help="Port (default: config.yaml)"),
         no_browser: bool = typer.Option(False, "--no-browser", help="Do not open the browser")):
    """Serve the frontend on 127.0.0.1 and open it in the browser."""
    cfg = load_config(root / "config.yaml")
    cfg.stage_roots(root)  # fail before serving when a stage directory is missing
    port = port or cfg.port
    if not no_browser:
        threading.Timer(1.0, webbrowser.open, args=[f"http://{cfg.host}:{port}/"]).start()
    uvicorn.run(create_app(root, port), host=cfg.host, port=port)
