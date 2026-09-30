"""The one-page research brief, rendered by code from the opportunity record and the earlier stages' records."""
import textwrap

RULE = "=" * 58
WIDTH = 78


def _para(text: str) -> str:
    return "\n".join(textwrap.fill(p, WIDTH) for p in str(text).split("\n") if p.strip()) or "—"


def _conf(x) -> str:
    return "—" if x is None else f"{x:.2f}"


def _score(name: str, x) -> str:
    return f"{name} unknown" if x is None else f"{name} {x}/10"


def _beneficiary(ev: dict | None) -> str:
    if ev is None:
        return "not assessed: run economicvalue"
    e = ev["economic_value"]
    who = e["beneficiary"]["description"] or e["beneficiary"]["type"]
    pv = e["potential_value"]
    value = ("potential value unknown" if pv == "unknown"
             else f"potential value {pv['low']:,.0f}–{pv['high']:,.0f} {pv['unit']} ({pv['status']})")
    return f"{who}\nBuyer: {e['buyer']}\n{value}"


def render(record: dict, problem: dict, fit: dict, novelty: dict | None, ev: dict | None, profile_name: str) -> str:
    s, p, c = record["brief_sections"], record["opportunity_profile"], record["confidence"]
    status = f"(novelty check: {novelty['novelty']['status']})" if novelty else "(novelty not checked: run noveltyinvestigator)"
    counter = novelty["strongest_counterargument"] if novelty else "not checked: run noveltyinvestigator"
    why_me = "\n".join(f"- {a['claim']} ({a['file']})" for a in fit["advantages"]) or "- no advantage backed by the profile"
    engagement = ", ".join(f"{k}: {v}" for k, v in p["likely_engagement"].items())
    box = {r: "x" if record["recommendation"] == r else " " for r in ("ignore", "investigate", "contact")}
    sections = [
        ("PROBLEM", _para(problem["problem"]["precise_statement"])),
        ("WHY THIS MAY BE UNSOLVED", _para(f"{s['why_unsolved']} {status}")),
        ("CURRENT BEST APPROACH", _para(s["current_best_approach"])),
        ("STRONGEST COUNTEREVIDENCE", _para(counter)),
        ("ECONOMIC BENEFICIARY", _para(_beneficiary(ev))),
        (f"WHY {profile_name.upper()}?", why_me),
        ("WHAT WE COULD TEST", _para(s["what_we_could_test"])),
        ("ESTIMATED FIRST EXPERIMENT", _para(s["first_experiment"]) + f"\n~{s['first_experiment_hours']:g} hours\n"
         f"~${s['first_experiment_compute_usd']:g} compute\n(both are assumptions)"),
        ("IF SUCCESSFUL", _para(s["if_successful"])),
        ("IF FAILED", _para(s["if_failed"])),
        ("CONFIDENCE", f"Novelty       {_conf(c['novelty'])}\nValue         {_conf(c['value'])}\n"
                       f"Tractability  {_conf(c['tractability'])}\nFit           {_conf(c['fit'])}"),
        ("OPPORTUNITY PROFILE", ", ".join([_score("novelty", p["novelty"]), _score("economic value", p["economic_value"]),
                                           _score("tractability", p["tractability"]),
                                           _score("personal advantage", p["personal_advantage"])])
         + f"\nasymmetric upside: {p['asymmetric_upside']}\nlikely engagement: {engagement}"),
        ("THESIS", _para(record["thesis"])),
        ("RECOMMENDATION", f"[{box['ignore']}] Ignore\n[{box['investigate']}] Investigate\n[{box['contact']}] Contact someone\n"
                           + _para(record["recommendation_reason"])),
    ]
    body = "\n\n".join(f"{name}\n{text}" for name, text in sections)
    return f"{RULE}\n{record['id']}\n\n{record['title'].upper()}\n{RULE}\n\n{body}\n{RULE}\n"
