"""Read-only views over the stages' stores. Every derived status comes from the stage's own function (staleness:
personalfit.run.is_stale, opportunitygenerator.run.stale_inputs; links: ProblemExtractor's state). A record that
fails to load is reported in `errors` as (file, message, fix) and the other records are still returned."""
import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from challengeinvestigator.config import CIPaths
from challengeinvestigator.run import _headline
from economicvalue.config import EVPaths
from noveltyinvestigator.config import NIPaths
from opportunitygenerator.config import OGPaths, load_config as og_config
from opportunitygenerator.run import OGStores, stale_inputs
from personalfit.config import PFPaths, load_config as pf_config
from personalfit.profile import Profile, load_profile
from personalfit.run import is_stale
from problemextractor.config import PEPaths
from problemextractor.extract import read_candidates
from problemextractor.records import SORT_KEYS, best_payment, best_tier, due_passed
from problemextractor.state import PEState
from rqd.errors import RqdError
from rqd.records import read_yaml
from rqd.timeutil import deadline_summary, today
from sourcescout.store import Store

Error = tuple[str, str, str]  # (file, message, fix)
READ_ERRORS = (yaml.YAMLError, KeyError, TypeError, ValueError, AttributeError)


@dataclass
class Table:
    rows: list[dict]
    total: int
    page: int
    pages: int
    errors: list[Error] = field(default_factory=list)


TRIAGE_NONE = {"status": "none", "note": ""}
TRIAGE_FILTERS = ("shortlist", "reject", "not_rejected", "untriaged")


def _triaged(rows: list[dict], key: str, triage: dict | None, wanted: str | None) -> list[dict]:
    """Attach each row's triage (frontend-owned) and keep the rows the triage filter asks for."""
    if wanted and wanted not in TRIAGE_FILTERS:
        raise RqdError(f"unknown triage filter {wanted!r}", fix=f"Use one of: {', '.join(TRIAGE_FILTERS)}")
    for r in rows:
        r["triage"] = (triage or {}).get(r[key], TRIAGE_NONE)
    keep = {"shortlist": lambda s: s == "shortlist", "reject": lambda s: s == "reject",
            "not_rejected": lambda s: s != "reject", "untriaged": lambda s: s == "none"}.get(wanted, lambda s: True)
    return [r for r in rows if keep(r["triage"]["status"])]


def _page(rows: list[dict], page: int, page_size: int, errors: list[Error]) -> Table:
    pages = max(1, math.ceil(len(rows) / page_size))
    page = min(max(1, page), pages)
    return Table(rows[(page - 1) * page_size: page * page_size], len(rows), page, pages, errors)


def _index(directory: Path, read, fix: str, errors: list[Error]) -> dict[str, tuple[dict, object]]:
    """{record id (file stem): (record, read(record))} for every readable record; the others go to `errors`.
    `read` touches the keys a view shows, so a malformed record fails here, not halfway through a page."""
    out = {}
    for path in sorted(directory.glob("*.yaml")) if directory.is_dir() else []:
        try:
            record = read_yaml(path)
            out[path.stem] = (record, read(record))
        except READ_ERRORS as e:
            errors.append((str(path), f"unreadable record ({type(e).__name__}: {e})", fix.format(id=path.stem, dir=directory)))
    return out


def _search(text: str, q: str | None) -> bool:
    return not q or q.casefold() in text.casefold()


# --- per-stage readers: the keys the pages show -----------------------------------------------------------------

def _read_problem(r: dict) -> dict:
    return {"statement": r["problem"]["precise_statement"], "n_sources": len(r["sources"]), "best_tier": best_tier(r),
            "payment": best_payment(r), "due_passed": due_passed(r, today()), "revision": r["revision"]}


def _read_novelty(r: dict) -> dict:
    return {"status": r["novelty"]["status"], "confidence": r["confidence"]}


def _read_ev(r: dict) -> dict:
    pv = r["economic_value"]["potential_value"]
    return {"value": pv if pv == "unknown" else (pv["low"], pv["high"]),
            "status": None if pv == "unknown" else pv["status"]}


def _read_fit(r: dict) -> dict:
    return {"score": r["personal_advantage"]["score"], "problem_revision": r["problem_revision"],
            "profile_digest": r["profile_digest"]}


def _read_opp(r: dict) -> dict:
    p = r["opportunity_profile"]
    return {"id": r["id"], "problem_id": r["problem_id"], "recommendation": r["recommendation"], "title": r["title"],
            "scores": (p["novelty"], p["economic_value"], p["tractability"], p["personal_advantage"]), "inputs": r["inputs"]}


FIX_PROBLEM = "Inspect {dir}/{id}.yaml (written by `problemextractor run`); move it out of {dir} if it is broken"
FIX_NOVELTY = "Re-run `noveltyinvestigator investigate {id}` or remove the file"
FIX_EV = "Re-run `economicvalue assess {id}` or remove the file"
FIX_FIT = "Re-run `fit assess {id}`"
FIX_OPP = "Re-run `opportunities generate` for its problem, or move {id}.yaml out of {dir}"
FIX_CHALLENGE = "Re-run `challenges headroom {id}`"


@dataclass
class Stores:
    """Everything the problem funnel shows, loaded once per request."""
    problems: dict
    novelty: dict
    ev: dict
    fits: dict
    opps_by_problem: dict
    profile: Profile | None
    og: OGStores
    errors: list[Error]


def _profile(pf_root: Path, errors: list[Error]) -> Profile | None:
    cfg = pf_config(PFPaths(pf_root).config)
    try:
        return load_profile((pf_root / cfg.profile_dir).resolve(), cfg.profile_max_chars)
    except RqdError as e:
        errors.append((str((pf_root / cfg.profile_dir).resolve()), f"fit staleness unknown: {e}", e.fix))
        return None


def _stores(roots: dict[str, Path]) -> Stores:
    errors: list[Error] = []
    og_root = roots["opportunitygenerator"]
    opps = _index(OGPaths(og_root).opportunities, _read_opp, FIX_OPP, errors)
    return Stores(problems=_index(PEPaths(roots["problemextractor"]).problems, _read_problem, FIX_PROBLEM, errors),
                  novelty=_index(NIPaths(roots["noveltyinvestigator"]).investigations, _read_novelty, FIX_NOVELTY, errors),
                  ev=_index(EVPaths(roots["economicvalue"]).assessments, _read_ev, FIX_EV, errors),
                  fits=_index(PFPaths(roots["personalfit"]).fits, _read_fit, FIX_FIT, errors),
                  opps_by_problem={v["problem_id"]: (r, v) for r, v in opps.values()},
                  profile=_profile(roots["personalfit"], errors),
                  og=OGStores.open(OGPaths(og_root), og_config(OGPaths(og_root).config)), errors=errors)


def _fit_stale(s: Stores, pid: str) -> bool | None:
    if pid not in s.fits or pid not in s.problems or s.profile is None:
        return None
    return is_stale(s.fits[pid][0], s.problems[pid][0], s.profile)


def _opp_stale(s: Stores, record: dict) -> list[str]:
    try:
        return stale_inputs(s.og, record)
    except READ_ERRORS as e:
        s.errors.append((str(s.og.opportunities.path(record["id"])), f"stale check failed ({type(e).__name__}: {e})",
                         FIX_OPP.format(id=record["id"], dir=s.og.opportunities.dir)))
        return []


# --- views -------------------------------------------------------------------------------------------------------

def _candidate_row(c: dict, processed: dict[str, tuple[str, str]]) -> dict:
    ps = c["payment_signal"]
    problem_id, decision = processed.get(c["candidate_id"], (None, None))
    return {"candidate_id": c["candidate_id"], "source_id": c["source_id"], "category": c["source"].get("category"),
            "tier": c["source"]["tier"], "title": c["source"]["title"], "url": c["source"]["url"],
            "statement": c["candidate_problem"]["statement"], "payment": ps.get("stated") or ps["type"],
            "deadline": ps.get("deadline"), "due_passed": deadline_summary([ps.get("deadline")], today())[1],
            "problem_id": problem_id or None, "decision": decision, "at": c["extracted_with"]["at"]}


def _candidate_errors(unreadable: list[tuple[Path, Exception]]) -> list[Error]:
    return [(str(p), f"unreadable candidate file ({type(e).__name__}: {e})",
             f"Inspect {p}; move it out of {p.parent} if it is not a SourceScout candidate") for p, e in unreadable]


def _processed(pe_root: Path) -> dict[str, tuple[str, str]]:
    db = PEPaths(pe_root).db
    return PEState(db).all() if db.exists() else {}


def candidates(roots: dict[str, Path], filters: dict, page: int, page_size: int, triage: dict | None = None) -> Table:
    found, unreadable = read_candidates(roots["sourcescout"])
    errors = _candidate_errors(unreadable)
    processed = _processed(roots["problemextractor"])
    rows = []
    for c in found:
        try:
            rows.append(_candidate_row(c, processed))
        except READ_ERRORS as e:
            errors.append((c["candidate_id"], f"unreadable candidate ({type(e).__name__}: {e})",
                           "Inspect the candidate file under SourceScout/output/"))
    f = filters
    rows = [r for r in rows
            if _search(f"{r['candidate_id']} {r['statement']} {r['title']}", f.get("q"))
            and (not f.get("category") or r["category"] == f["category"])
            and (not f.get("tier") or r["tier"] == f["tier"])
            and (not f.get("processed") or (r["decision"] is not None) == (f["processed"] == "yes"))
            and (not f.get("due") or r["due_passed"] == (f["due"] == "passed"))]
    rows = _triaged(rows, "candidate_id", triage, f.get("triage"))
    rows.sort(key=lambda r: (r["tier"], r["at"], r["candidate_id"]))  # ProblemExtractor's processing order
    return _page(rows, page, page_size, errors)


def _waiting(pid: str, s: Stores) -> list[str]:
    out = [name for name, store in (("novelty", s.novelty), ("economic value", s.ev), ("fit", s.fits)) if pid not in store]
    if pid in s.fits and pid not in s.opps_by_problem:
        out.append("opportunity")
    return out


def _problem_row(pid: str, s: Stores) -> dict:
    record, p = s.problems[pid]
    nov = s.novelty.get(pid, (None, None))[1]
    ev = s.ev.get(pid, (None, None))[1]
    fit = s.fits.get(pid, (None, None))[1]
    opp_record, opp = s.opps_by_problem.get(pid, (None, None))
    stale = ["fit"] if _fit_stale(s, pid) else []
    if opp_record is not None:
        changed = _opp_stale(s, opp_record)
        if changed:
            stale.append(f"opportunity: {', '.join(changed)}")
    return {"problem_id": pid, **p, "novelty": nov["status"] if nov else None,
            "novelty_confidence": nov["confidence"] if nov else None,
            "value": ev["value"] if ev else None, "value_status": ev["status"] if ev else None,
            "fit": fit["score"] if fit else None, "opp_id": opp["id"] if opp else None,
            "recommendation": opp["recommendation"] if opp else None, "stale": stale, "waiting": _waiting(pid, s),
            "_record": record}


PROBLEM_SORTS = {"sources": lambda r: SORT_KEYS["sources"](r["_record"]),
                 "tier": lambda r: SORT_KEYS["tier"](r["_record"]),
                 "fit": lambda r: (r["fit"] is None, -(r["fit"] or 0), r["problem_id"]),
                 "value": lambda r: (not isinstance(r["value"], tuple), -(r["value"][1] if isinstance(r["value"], tuple) else 0)),
                 "id": lambda r: r["problem_id"]}


def _problem_filter(r: dict, f: dict) -> bool:
    return (_search(f"{r['problem_id']} {r['statement']}", f.get("q"))
            and (not f.get("has_fit") or (r["fit"] is not None) == (f["has_fit"] == "yes"))
            and (not f.get("fit_min") or (r["fit"] is not None and r["fit"] >= int(f["fit_min"])))
            and (not f.get("novelty") or r["novelty"] == f["novelty"])
            and (not f.get("stale") or bool(r["stale"]) == (f["stale"] == "yes"))
            and (not f.get("waiting") or f["waiting"] in r["waiting"])
            and (not f.get("tier") or r["best_tier"] == f["tier"])
            and (not f.get("recommendation") or r["recommendation"] == f["recommendation"]))


def problems(roots: dict[str, Path], filters: dict, sort: str, page: int, page_size: int,
             triage: dict | None = None) -> Table:
    if sort not in PROBLEM_SORTS:
        raise RqdError(f"unknown sort {sort!r}", fix=f"Use one of: {', '.join(PROBLEM_SORTS)}")
    s = _stores(roots)
    rows = []
    for pid in s.problems:
        rows.append(_problem_row(pid, s))
    rows = _triaged([r for r in rows if _problem_filter(r, filters)], "problem_id", triage, filters.get("triage"))
    rows.sort(key=PROBLEM_SORTS[sort])
    return _page(rows, page, page_size, s.errors)


def _candidate_file(ss_root: Path, candidate_id: str) -> dict | None:
    paths = sorted((ss_root / "output").glob(f"*/{candidate_id}.yaml"))
    return read_yaml(paths[-1]) if paths else None


def dossier(roots: dict[str, Path], problem_id: str) -> dict:
    """Everything about one problem in pipeline order: source candidates -> problem -> novelty -> economic value ->
    fit -> opportunity."""
    s = _stores(roots)
    if problem_id not in s.problems:
        bad = [e for e in s.errors if Path(e[0]).stem == problem_id]
        if bad:
            raise RqdError(f"{problem_id}: {bad[0][1]}", fix=bad[0][2])
        raise RqdError(f"no problem {problem_id}", fix="See the Problems page (`uv run problemextractor list`)")
    record = s.problems[problem_id][0]
    cands = []
    for src in record["sources"]:
        c = _candidate_file(roots["sourcescout"], src["candidate_id"])
        cands.append({"candidate_id": src["candidate_id"], "source": c["source"] if c else src,
                      "candidate": c, "payment_signal": src["payment_signal"], "source_id": src["source_id"]})
    opp_record = s.opps_by_problem.get(problem_id, (None, None))[0]
    return {"problem_id": problem_id, "problem": record, "candidates": cands,
            "row": _problem_row(problem_id, s),
            "novelty": s.novelty.get(problem_id, (None,))[0], "ev": s.ev.get(problem_id, (None,))[0],
            "fit": s.fits.get(problem_id, (None,))[0], "fit_stale": _fit_stale(s, problem_id),
            "opportunity": opp_record,
            "opportunity_stale": _opp_stale(s, opp_record) if opp_record else None,
            "errors": s.errors}


def opportunities(roots: dict[str, Path], filters: dict, page: int, page_size: int,
                  triage: dict | None = None) -> Table:
    s = _stores(roots)
    rows = []
    for pid, (record, o) in s.opps_by_problem.items():
        problem = s.problems.get(pid)
        rows.append({**{k: v for k, v in o.items() if k != "inputs"},
                     "stale": _opp_stale(s, record),
                     "statement": problem[1]["statement"] if problem else None})
    f = filters
    rows = [r for r in rows if _search(f"{r['id']} {r['problem_id']} {r['title']}", f.get("q"))
            and (not f.get("recommendation") or r["recommendation"] == f["recommendation"])
            and (not f.get("stale") or bool(r["stale"]) == (f["stale"] == "yes"))]
    rows = _triaged(rows, "id", triage, f.get("triage"))
    rows.sort(key=lambda r: r["id"])
    return _page(rows, page, page_size, s.errors)


def brief(roots: dict[str, Path], opp_id: str) -> str:
    path = OGPaths(roots["opportunitygenerator"]).briefs / f"{opp_id}.md"
    if not path.exists():
        raise RqdError(f"no brief for {opp_id} ({path})", fix=f"Re-run `opportunities generate` for its problem")
    return path.read_text(encoding="utf-8")


def _scout_store(ss_root: Path) -> Store:
    db = ss_root / "data" / "scout.db"
    if not db.exists():
        raise RqdError(f"SourceScout store not found at {db}", fix="Run `uv run sourcescout scan` first, or set roots.sourcescout")
    return Store(db)


def _read_challenge(r: dict) -> dict:
    h = r["headroom"]
    return {"verdict": h["verdict"], "headline": _headline(h),
            "winner": f"{h['winner']['value']:g} {h['metric']}" if h.get("winner") else None,
            "investigated": bool(r.get("investigation"))}


def challenges(roots: dict[str, Path], filters: dict, page: int, page_size: int,
               triage: dict | None = None) -> Table:
    errors: list[Error] = []
    records = _index(CIPaths(roots["challengeinvestigator"]).challenges, _read_challenge, FIX_CHALLENGE, errors)
    rows = []
    for item in _scout_store(roots["sourcescout"]).finished_items():
        c = records.get(item.item_id, (None, None))[1]
        rows.append({"item_id": item.item_id, "title": item.title, "url": item.url, "source_id": item.source_id,
                     "verdict": c["verdict"] if c else None, "headline": c["headline"] if c else None,
                     "winner": c["winner"] if c else None, "investigated": c["investigated"] if c else False})
    f = filters
    rows = [r for r in rows if _search(f"{r['item_id']} {r['title']}", f.get("q"))
            and (not f.get("checked") or (r["verdict"] is not None) == (f["checked"] == "yes"))
            and (not f.get("verdict") or r["verdict"] == f["verdict"])
            and (not f.get("investigated") or r["investigated"] == (f["investigated"] == "yes"))]
    rows = _triaged(rows, "item_id", triage, f.get("triage"))
    rows.sort(key=lambda r: (r["verdict"] is None, r["title"]))
    return _page(rows, page, page_size, errors)


def challenge(roots: dict[str, Path], item_id: str) -> dict:
    item = _scout_store(roots["sourcescout"]).get(item_id)
    if item is None or not item.finished:
        raise RqdError(f"{item_id} is not a finished challenge in the SourceScout store", fix="See the Challenges page")
    path = CIPaths(roots["challengeinvestigator"]).challenges / f"{item_id}.yaml"
    return {"item": item, "record": read_yaml(path) if path.exists() else None}


def overview(roots: dict[str, Path]) -> dict:
    """Per stage: count, waiting for the next stage, stale; and every load error."""
    found, unreadable = read_candidates(roots["sourcescout"])
    processed = _processed(roots["problemextractor"])
    s = _stores(roots)
    rows = [_problem_row(pid, s) for pid in s.problems]
    ch = challenges(roots, {}, 1, 10**9)
    stages = [
        {"stage": "Candidates", "href": "/candidates", "count": len(found),
         "waiting": sum(c["candidate_id"] not in processed for c in found), "waiting_for": "extraction"},
        {"stage": "Problems", "href": "/problems", "count": len(s.problems),
         "waiting": sum("novelty" in r["waiting"] for r in rows), "waiting_for": "novelty"},
        {"stage": "Novelty", "href": "/problems?novelty=likely_open", "count": len(s.novelty)},
        {"stage": "Economic value", "href": "/problems?waiting=economic+value", "count": len(s.ev),
         "waiting": sum("economic value" in r["waiting"] for r in rows), "waiting_for": "economic value"},
        {"stage": "Fit", "href": "/problems?has_fit=yes", "count": len(s.fits),
         "waiting": sum("fit" in r["waiting"] for r in rows), "waiting_for": "fit",
         "stale": sum("fit" in r["stale"] for r in rows)},
        {"stage": "Opportunities", "href": "/opportunities", "count": len(s.opps_by_problem),
         "waiting": sum("opportunity" in r["waiting"] for r in rows), "waiting_for": "generate",
         "stale": sum(any(x.startswith("opportunity") for x in r["stale"]) for r in rows)},
        {"stage": "Challenges", "href": "/challenges", "count": ch.total,
         "waiting": sum(r["verdict"] is None for r in ch.rows), "waiting_for": "headroom"},
    ]
    return {"stages": stages, "errors": _candidate_errors(unreadable) + s.errors + ch.errors}
