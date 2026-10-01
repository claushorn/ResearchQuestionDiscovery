"""FastAPI app: server-rendered pages over the stages' stores. Deliberate failures (RqdError) render as a page with
the message and fix; never a traceback page."""
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from frontend import actions, views
from frontend.config import FEConfig, load_config
from frontend.db import Triage
from rqd.errors import RqdError

HERE = Path(__file__).resolve().parent
NAV = [("/", "Overview"), ("/candidates", "Candidates"), ("/problems", "Problems"),
       ("/opportunities", "Opportunities"), ("/challenges", "Challenges"), ("/tasks", "Agent Tasks")]
PAGING = ("page", "sort")


def money(x: float) -> str:
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(x) >= size:
            return f"${x / size:.1f}{suffix}"
    return f"${x:,.0f}"


def qs(request: Request, **changes) -> str:
    """The current query string with some parameters changed (None removes one)."""
    params = {**request.query_params, **changes}
    return "?" + urlencode({k: v for k, v in params.items() if v not in (None, "")})


def create_app(root: Path) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals.update(nav=NAV, qs=qs)
    templates.env.filters["money"] = money
    triage = Triage(root / "data" / "frontend.db")

    def setup() -> tuple[FEConfig, dict[str, Path]]:
        cfg = load_config(root / "config.yaml")
        return cfg, cfg.stage_roots(root)

    def query(request: Request) -> tuple[dict, int]:
        filters = {k: v for k, v in request.query_params.items() if k not in PAGING and v}
        try:
            page = int(request.query_params.get("page") or 1)
        except ValueError:
            raise RqdError(f"page must be a whole number, got {request.query_params['page']!r}", fix="Use e.g. page=2") from None
        return filters, page

    def render(request: Request, name: str, **context):
        return templates.TemplateResponse(request, name, context)

    @app.exception_handler(RqdError)
    async def rqd_error(request: Request, exc: RqdError):
        return templates.TemplateResponse(request, "error.html", {"message": str(exc), "fix": exc.fix},
                                          status_code=500)

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        _, roots = setup()
        return render(request, "overview.html", **views.overview(roots))

    @app.get("/candidates", response_class=HTMLResponse)
    def candidates(request: Request):
        cfg, roots = setup()
        filters, page = query(request)
        table = views.candidates(roots, filters, page, cfg.page_size, triage.get_all("candidate"))
        return render(request, "candidates.html", table=table, filters=filters, actions=actions.for_page("candidates"))

    @app.get("/problems", response_class=HTMLResponse)
    def problems(request: Request):
        cfg, roots = setup()
        filters, page = query(request)
        sort = request.query_params.get("sort") or "sources"
        table = views.problems(roots, filters, sort, page, cfg.page_size, triage.get_all("problem"))
        return render(request, "problems.html", table=table, filters=filters, sort=sort,
                      sorts=list(views.PROBLEM_SORTS), actions=actions.for_page("problems"))

    @app.get("/problems/{problem_id}", response_class=HTMLResponse)
    def dossier(request: Request, problem_id: str):
        _, roots = setup()
        d = views.dossier(roots, problem_id)
        return render(request, "dossier.html", d=d, actions=actions.for_page("problems"),
                      t=triage.get_many("problem", [problem_id]).get(problem_id))

    @app.get("/opportunities", response_class=HTMLResponse)
    def opportunities(request: Request):
        cfg, roots = setup()
        filters, page = query(request)
        table = views.opportunities(roots, filters, page, cfg.page_size, triage.get_all("opportunity"))
        return render(request, "opportunities.html", table=table, filters=filters)

    @app.get("/opportunities/{opp_id}/brief", response_class=HTMLResponse)
    def brief(request: Request, opp_id: str):
        _, roots = setup()
        return render(request, "brief.html", opp_id=opp_id, text=views.brief(roots, opp_id))

    @app.get("/challenges", response_class=HTMLResponse)
    def challenges(request: Request):
        cfg, roots = setup()
        filters, page = query(request)
        table = views.challenges(roots, filters, page, cfg.page_size, triage.get_all("challenge"))
        return render(request, "challenges.html", table=table, filters=filters, actions=actions.for_page("challenges"))

    @app.get("/challenges/{item_id}", response_class=HTMLResponse)
    def challenge(request: Request, item_id: str):
        _, roots = setup()
        return render(request, "challenge.html", c=views.challenge(roots, item_id), actions=actions.for_page("challenges"),
                      t=triage.get_many("challenge", [item_id]).get(item_id))

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
