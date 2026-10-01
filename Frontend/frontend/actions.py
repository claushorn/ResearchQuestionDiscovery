"""Next-stage actions per page: each runs the stage's own CLI on the selected ids (an Agent Task). The confirmation's
refusals come from the stages' own pre-spend checks (the functions the CLIs call), its caps from the stages' configs."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from challengeinvestigator.config import CIPaths, load_config as ci_config
from challengeinvestigator.run import refusal, scout_store
from economicvalue.assess import gate, investigations_store, problems_store
from economicvalue.config import EVPaths, load_config as ev_config
from noveltyinvestigator.config import NIPaths, load_config as ni_config
from noveltyinvestigator.investigate import problems_store as ni_problems_store, refusal as ni_refusal
from opportunitygenerator.config import OGPaths, load_config as og_config
from opportunitygenerator.ids import opp_id_for
from opportunitygenerator.run import OGStores, load_inputs
from personalfit.config import PFPaths, load_config as pf_config
from personalfit.run import problems_store as pf_problems_store, refusal as pf_refusal
from problemextractor.config import PEPaths, load_config as pe_config
from problemextractor.extract import check_candidate_ids, read_candidates
from problemextractor.state import PEState
from rqd.errors import RqdError
from rqd.records import YamlStore

Check = Callable[[str, bool], RqdError | None]  # (item id, force) -> the stage's refusal, or None when runnable


def _refused(fn: Callable[[], object]) -> RqdError | None:
    try:
        fn()
    except RqdError as e:
        return e
    return None


def _extract(root: Path) -> tuple[Check, Callable[[str], bool]]:
    ss_root = (root / pe_config(PEPaths(root).config).sourcescout_root).resolve()
    found, _ = read_candidates(ss_root)
    db = PEPaths(root).db
    processed = PEState(db).all() if db.exists() else {}
    known = {c["candidate_id"] for c in found}
    return (lambda i, force: _refused(lambda: check_candidate_ids([i], known, processed.__contains__, ss_root)),
            lambda i: False)


def _novelty(root: Path) -> tuple[Check, Callable[[str], bool]]:
    problems = ni_problems_store(NIPaths(root), ni_config(NIPaths(root).config))
    return lambda i, force: ni_refusal(problems, i), YamlStore(NIPaths(root).investigations).exists


def _economic_value(root: Path) -> tuple[Check, Callable[[str], bool]]:
    paths = EVPaths(root)
    cfg = ev_config(paths.config)
    problems, investigations = problems_store(paths, cfg), investigations_store(paths, cfg)
    return (lambda i, force: _refused(lambda: gate(problems, investigations, i, force)),
            YamlStore(paths.assessments).exists)


def _fit(root: Path) -> tuple[Check, Callable[[str], bool]]:
    problems = pf_problems_store(PFPaths(root), pf_config(PFPaths(root).config))
    return lambda i, force: pf_refusal(problems, i), YamlStore(PFPaths(root).fits).exists


def _generate(root: Path) -> tuple[Check, Callable[[str], bool]]:
    stores = OGStores.open(OGPaths(root), og_config(OGPaths(root).config))
    existing = {r["problem_id"] for r in stores.opportunities.all()} if stores.opportunities.dir.is_dir() else set()
    return (lambda i, force: _refused(lambda: (load_inputs(stores, i), opp_id_for(stores.opportunities, i))),
            existing.__contains__)


def _challenges(root: Path, headroom: bool) -> tuple[Check, Callable[[str], bool]]:
    paths = CIPaths(root)
    store, challenges = scout_store(paths, ci_config(paths.config)), YamlStore(paths.challenges)
    if headroom:  # `challenges headroom <ids>`: only the finished-challenge check applies
        return lambda i, force: refusal(store, challenges, i, True), challenges.exists
    return (lambda i, force: refusal(store, challenges, i, force),
            lambda i: challenges.exists(i) and bool(challenges.load(i).get("investigation")))


def _agent_cap(load_config, paths_cls, attr: str = "agent") -> Callable[[Path], tuple[float, str]]:
    def cap(root: Path) -> tuple[float, str]:
        return getattr(load_config(paths_cls(root).config), attr).max_budget_usd, ""
    return cap


def _pe_cap(root: Path) -> tuple[None, str]:
    budget = pe_config(PEPaths(root).config).extraction.token_budget
    return None, f"no per-item $ cap (runs on the subscription, ~$0.01-0.02 per candidate measured); " \
                 f"token budget {budget} output tokens per candidate"


def _ci_cap(attr: str, note: str) -> Callable[[Path], tuple[float, str]]:
    def cap(root: Path) -> tuple[float, str]:
        return getattr(ci_config(CIPaths(root).config), attr).max_budget_usd, note
    return cap


@dataclass(frozen=True)
class Action:
    key: str
    label: str                  # button text: "Run <label>"
    page: str                   # the page whose selection it takes: candidates | problems | challenges
    stage: str                  # roots key of the stage whose CLI runs
    script: str                 # console script in this venv
    command: str                # subcommand; the ids follow (each after `id_flag` when the CLI takes them so)
    force_option: str | None    # what --force does, where the CLI has it
    cap: Callable[[Path], tuple[float | None, str]]
    checks: Callable[[Path], tuple[Check, Callable[[str], bool]]]  # (refusal check, "already has a record")
    id_flag: str | None = None

    def argv(self, bin_dir: Path, root: Path, ids: list[str], force: bool) -> list[str]:
        """The stage's own CLI command line for these ids."""
        # ids never become options: `--flag=<id>` binds the value, `--` ends the options before positional ids
        args = [f"{self.id_flag}={i}" for i in ids] if self.id_flag else ["--", *ids]
        return [str(bin_dir / self.script), "--root", str(root), self.command,
                *(["--force"] if force and self.force_option else []), *args]


ACTIONS = {a.key: a for a in [
    Action("extract", "extraction", "candidates", "problemextractor", "problemextractor", "run",
           None, _pe_cap, _extract, id_flag="--candidate"),
    Action("novelty", "novelty", "problems", "noveltyinvestigator", "noveltyinvestigator", "investigate", None,
           _agent_cap(ni_config, NIPaths), _novelty),
    Action("economic_value", "economic value", "problems", "economicvalue", "economicvalue", "assess",
           "assess problems NoveltyInvestigator marked solved", _agent_cap(ev_config, EVPaths), _economic_value),
    Action("fit", "fit", "problems", "personalfit", "fit", "assess", None, _agent_cap(pf_config, PFPaths), _fit),
    Action("generate", "generate opportunity", "problems", "opportunitygenerator", "opportunities", "generate",
           None, _agent_cap(og_config, OGPaths), _generate),
    Action("headroom", "headroom", "challenges", "challengeinvestigator", "challenges", "headroom", None,
           _ci_cap("baseline_agent", "spent only when a missing baseline must be looked up; the leaderboard is scraped"),
           lambda root: _challenges(root, headroom=True)),
    Action("investigate", "investigate", "challenges", "challengeinvestigator", "challenges", "investigate",
           "investigate challenges the headroom check found solved",
           _ci_cap("investigate_agent", "an unchecked challenge gets its headroom check first (baseline lookup cap extra)"),
           lambda root: _challenges(root, headroom=False)),
]}


def for_page(page: str) -> list[Action]:
    return [a for a in ACTIONS.values() if a.page == page]


def confirm(roots: dict[str, Path], action: str, ids: list[str], force: bool) -> dict:
    """What a run would do before any spend: count, per-item cap and worst case, the items the stage refuses (its
    own message and fix), the items that already have a record (re-running replaces it), and the force option."""
    if action not in ACTIONS:
        raise RqdError(f"unknown action {action!r}", fix=f"Use one of: {', '.join(ACTIONS)}")
    if not ids:
        raise RqdError("no items selected", fix="Select at least one row, then press Run")
    a = ACTIONS[action]
    root = roots[a.stage]
    check, has_record = a.checks(root)
    refused, runnable = [], []
    for i in dict.fromkeys(ids):  # unique, in selection order
        err = check(i, force)
        if err is None:
            runnable.append(i)
        else:
            refused.append({"id": i, "message": str(err), "fix": err.fix})
    cap, note = a.cap(root)
    return {"action": a, "ids": list(dict.fromkeys(ids)), "count": len(runnable), "runnable": runnable,
            "refused": refused, "existing": [i for i in runnable if has_record(i)], "cap_usd": cap, "cap_note": note,
            "worst_case_usd": None if cap is None else round(cap * len(runnable), 2),
            "force_option": a.force_option, "force": force}
