"""FastAPI app: server-rendered pages over the stages' stores. Deliberate failures (RqdError) render as a page with
the message and fix; never a traceback page."""
from html import escape
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from frontend.config import load_config
from frontend.db import Triage
from rqd.errors import RqdError

HERE = Path(__file__).resolve().parent
NAV = [("/", "Overview"), ("/candidates", "Candidates"), ("/problems", "Problems"),
       ("/opportunities", "Opportunities"), ("/challenges", "Challenges"), ("/tasks", "Agent Tasks")]


def create_app(root: Path) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals["nav"] = NAV
    triage = Triage(root / "data" / "frontend.db")

    def roots() -> dict[str, Path]:
        cfg = load_config(root / "config.yaml")
        return cfg.stage_roots(root)

    @app.exception_handler(RqdError)
    async def rqd_error(request: Request, exc: RqdError):
        return templates.TemplateResponse(request, "error.html", {"message": str(exc), "fix": exc.fix},
                                          status_code=500)

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        return templates.TemplateResponse(request, "overview.html", {"roots": roots()})

    @app.post("/triage/{kind}/{item_id}", response_class=HTMLResponse)
    def set_triage(request: Request, kind: str, item_id: str, status: str = Form(""), current: str = Form("none"),
                   note: str = Form("")):
        try:
            triage.set(kind, item_id, status or current, note)
        except ValueError as e:
            return HTMLResponse(f'<span class="chip bad">{escape(str(e))}</span>', status_code=400)
        return templates.TemplateResponse(request, "triage.html", {
            "kind": kind, "item_id": item_id, "t": triage.get_many(kind, [item_id]).get(item_id)})

    return app
