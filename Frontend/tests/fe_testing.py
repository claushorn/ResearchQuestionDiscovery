"""Synthetic stage directories and a Frontend directory pointing at them (tests use synthetic data only)."""
from pathlib import Path

import yaml

STAGES = {"sourcescout": "SourceScout", "problemextractor": "ProblemExtractor", "noveltyinvestigator": "NoveltyInvestigator",
          "economicvalue": "EconomicValueInvestigator", "challengeinvestigator": "ChallengeInvestigator",
          "personalfit": "PersonalFitInvestigator", "opportunitygenerator": "OpportunityGenerator"}


def make_frontend(tmp: Path, port: int = 8765, **overrides) -> Path:
    """<tmp>/Frontend/config.yaml with relative roots to <tmp>/<Stage>; the stage directories are created."""
    root = tmp / "Frontend"
    root.mkdir(parents=True, exist_ok=True)
    for d in STAGES.values():
        (tmp / d).mkdir(exist_ok=True)
    cfg = {"port": port, "page_size": 50, "roots": {k: f"../{v}" for k, v in STAGES.items()}} | overrides
    (root / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return root


REPO = Path(__file__).resolve().parents[2]
TODAY_PASSED, FUTURE = "2020-01-01", "2099-01-01"


def candidate(n: int, tier: str = "A", source_id: str = "grants-gov-ml", category: str = "gov_solicitation",
              deadline: str | None = FUTURE, statement: str | None = None) -> dict:
    from sourcescout.store import item_id_for
    url = f"https://g.example/{n}"
    item = item_id_for(url)
    return {"source_id": source_id, "item_id": item, "candidate_id": f"cand-{item}-r1-0", "revision": 1,
            "source": {"url": url, "title": f"Call {n}", "date": None, "tier": tier, "category": category},
            "candidate_problem": {"statement": statement or f"Synthetic problem statement {n}."},
            "why_interesting": "Agency funds it.", "explicit_unsolved_signal": {"present": True, "evidence": "open"},
            "payment_signal": {"type": "grant", "stated": f"${n + 1}00k", "evidence": "up to", "deadline": deadline},
            "technical_area": ["planning"], "entities": {"organizations": [], "researchers": []},
            "referenced_urls": [], "evidence_verified": True, "length_violations": [],
            "extracted_with": {"model": "m", "run_id": "R", "output_tokens": 400, "at": f"2026-09-{10 + n:02d}T00:00:00+00:00"}}


def problem(pid: str, cands: list[dict], revision: int = 1, statement: str | None = None) -> dict:
    from problemextractor.records import source_entry
    return {"problem_id": pid, "revision": revision,
            "problem": {"precise_statement": statement or f"Precise statement of {pid}."},
            "current_state": {"known_solution": "not stated", "known_solution_inferred": "heuristics"},
            "failure": {"what_current_methods_cannot_do": "not stated", "what_current_methods_cannot_do_inferred": "scale"},
            "desired_capability": "a method that scales", "why_it_matters": "it costs money",
            "unsolvedness": {"explicit": True, "explicit_evidence": "remains open", "inferred": True, "evidence_verified": True},
            "sources": [source_entry(c) for c in cands],
            "merge_log": [{"candidate_id": c["candidate_id"], "decision": "new" if i == 0 else "merged", "reason": "r"}
                          for i, c in enumerate(cands)]}


def novelty(pid: str, status: str = "likely_open") -> dict:
    return {"problem_id": pid, "revision": 1, "novelty": {"status": status}, "confidence": 0.7,
            "strongest_counterargument": "A lab may have solved it.",
            "closest_work": [{"title": "Paper", "url": "https://n.example/p", "quote": "we leave this open",
                              "verification": "verified"}]}


def ev(pid: str) -> dict:
    return {"problem_id": pid, "revision": 1, "confidence": 0.6, "gate": "passed",
            "economic_value": {"beneficiary": {"type": "company", "description": "logistics firms"}, "buyer": "COO",
                               "potential_value": {"low": 1_000_000, "high": 5_000_000, "unit": "USD/year",
                                                   "status": "supported", "model": "market", "basis": []}},
            "evidence": [{"title": "Report", "url": "https://e.example/r", "quote": "costs 2M a year",
                          "verification": "unverified"}]}


def fit(pid: str, digest: str, score: int = 8, problem_revision: int = 1) -> dict:
    return {"problem_id": pid, "revision": 1, "problem_revision": problem_revision, "profile_digest": digest,
            "advantages": [{"claim": "built a planner", "file": "notes.md", "quote": "Built a planner",
                            "why_ml_researcher_lacks_it": "x", "basis": "profile"}],
            "gaps": [], "personal_advantage": {"score": score, "confidence": 0.8, "reasoning": "r"}, "warnings": []}


def opportunity(opp_id: str, pid: str, inputs: dict, recommendation: str = "investigate") -> dict:
    return {"id": opp_id, "problem_id": pid, "revision": 1, "title": f"Can we solve {pid}?",
            "opportunity_profile": {"novelty": 8, "economic_value": 7, "tractability": 6, "personal_advantage": 8},
            "recommendation": recommendation, "recommendation_reason": "cheap test", "thesis": "We can.",
            "inputs": inputs, "evidence": [{"title": "Data", "url": "https://d.example", "quote": "free data",
                                            "verification": "verified"}]}


def seed(tmp: Path) -> dict:
    """A small synthetic pipeline in <tmp>: candidates c0..c3 (c0, c1 -> prob-a; c2 -> prob-b; c3 unprocessed,
    deadline passed), problems prob-a/b/c, novelty a (open) b (solved), EV a, fits a (fresh) b (stale),
    OPP-0001 for prob-a with its brief, two finished challenges (one checked). Returns the Frontend root and ids."""
    from opportunitygenerator.run import _inputs
    from personalfit.profile import load_profile
    from problemextractor.state import PEState
    from rqd.records import YamlStore
    from sourcescout.adapters.base import RawItem
    from sourcescout.store import Store, item_id_for

    root = make_frontend(tmp)
    for d in ("ProblemExtractor", "NoveltyInvestigator", "EconomicValueInvestigator", "ChallengeInvestigator",
              "PersonalFitInvestigator", "OpportunityGenerator"):
        (tmp / d / "config.yaml").write_text((REPO / d / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp / "SourceScout" / "sources.yaml").write_text((REPO / "SourceScout" / "sources.yaml").read_text(encoding="utf-8"),
                                                      encoding="utf-8")
    (tmp / "personal_profile").mkdir(exist_ok=True)
    (tmp / "personal_profile" / "notes.md").write_text("Built a planner for synthetic robots.\n", encoding="utf-8")

    cands = [candidate(0, "A"), candidate(1, "C", "rss-x", "tech_blog"), candidate(2, "B"),
             candidate(3, "A", deadline=TODAY_PASSED)]
    store = Store(tmp / "SourceScout" / "data" / "scout.db")
    out = tmp / "SourceScout" / "output" / "2026-09"
    out.mkdir(parents=True, exist_ok=True)
    for c in cands:
        store.upsert(RawItem(c["source_id"], c["source"]["url"], c["source"]["title"], None, "text", ()),
                     "2026-09-30T00:00:00+00:00", 20000)
        (out / f"{c['candidate_id']}.yaml").write_text(yaml.safe_dump(c, sort_keys=False), encoding="utf-8")
    challenge_urls = ["https://www.aicrowd.com/challenges/x", "https://www.aicrowd.com/challenges/y"]
    for i, url in enumerate(challenge_urls):
        store.upsert(RawItem("aicrowd-completed", url, f"Challenge {i}", None, "maximise accuracy", (), finished=True),
                     "2026-09-30T00:00:00+00:00", 20000)

    problems = YamlStore(tmp / "ProblemExtractor" / "problems")
    recs = {"prob-a": problem("prob-a", cands[:2], revision=2), "prob-b": problem("prob-b", [cands[2]]),
            "prob-c": problem("prob-c", [cands[2]])}
    for pid, r in recs.items():
        problems.save(r, pid)
    state = PEState(tmp / "ProblemExtractor" / "data" / "pe.db")
    state.record(cands[0]["candidate_id"], "prob-a", "new", "2026-09-30T00:00:00+00:00")
    state.record(cands[1]["candidate_id"], "prob-a", "merged", "2026-09-30T00:00:00+00:00")
    state.record(cands[2]["candidate_id"], "prob-b", "new", "2026-09-30T00:00:00+00:00")

    YamlStore(tmp / "NoveltyInvestigator" / "investigations").save(novelty("prob-a"), "prob-a")
    YamlStore(tmp / "NoveltyInvestigator" / "investigations").save(novelty("prob-b", "solved"), "prob-b")
    YamlStore(tmp / "EconomicValueInvestigator" / "assessments").save(ev("prob-a"), "prob-a")
    digest = load_profile(tmp / "personal_profile", 200_000).digest
    fits = YamlStore(tmp / "PersonalFitInvestigator" / "fits")
    fits.save(fit("prob-a", digest, 9, problem_revision=2), "prob-a")
    fits.save(fit("prob-b", digest, 5, problem_revision=0), "prob-b")
    opp = opportunity("OPP-0001", "prob-a", _inputs(recs["prob-a"], fits.load("prob-a"), novelty("prob-a"), ev("prob-a")))
    YamlStore(tmp / "OpportunityGenerator" / "opportunities").save(opp, "OPP-0001")
    (tmp / "OpportunityGenerator" / "briefs").mkdir(parents=True, exist_ok=True)
    (tmp / "OpportunityGenerator" / "briefs" / "OPP-0001.md").write_text("# Can we solve prob-a?\n\nSynthetic brief.\n",
                                                                       encoding="utf-8")
    checked = item_id_for(challenge_urls[0])
    YamlStore(tmp / "ChallengeInvestigator" / "challenges").save(
        {"item_id": checked, "revision": 1, "challenge": {"title": "Challenge 0", "url": challenge_urls[0],
                                                          "source_id": "aicrowd-completed"},
         "headroom": {"metric": "Accuracy", "direction": "higher_is_better", "winner": {"value": 0.6}, "ceiling": None,
                      "baseline": None, "normalized_headroom": 0.4, "verdict": "open", "warnings": []},
         "investigation": None, "history": []}, checked)
    return {"root": root, "candidates": [c["candidate_id"] for c in cands],
            "challenges": [item_id_for(u) for u in challenge_urls]}
