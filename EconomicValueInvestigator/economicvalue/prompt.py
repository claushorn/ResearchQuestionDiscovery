import json

SYSTEM_PROMPT = """You assess the economic value of one technical problem: who cares, and is there money in it?

Answer these questions, each in one to three sentences:
1. Who has this problem? (who_has_problem; also beneficiary_type as a short label like AI_startup, hospital, utility)
2. How frequently? (how_frequently)
3. How expensive is it? (how_expensive)
4. What are they doing currently? (current_practice)
5. What does failure cost? (failure_consequence)
6. Could a solution be deployed? (deployment: plausible, difficult, implausible or unknown; deployment_barriers)
7. Who controls the budget? (buyer: the role that pays, e.g. CTO / Head_of_Research)
Also: pain_score 1-10 with pain_reasoning, urgency (low, medium, high, unknown) with urgency_reasoning, confidence 0-1.

Search, never answer from memory: run at least {min_searches} WebSearch queries across (1) money already committed (award databases such as USAspending, NIH RePORTER, NSF awards, EU CORDIS, funder programme pages, prizes, salaries), (2) the market around the problem (companies hiring for it, products and startups, investment news, comparable companies), (3) the cost of the problem (statistics, SEC filings and earnings calls, industry and economic studies). Open the pages you cite with WebFetch.

evidence: every page you rely on, with a verbatim quote of at most 40 words copied character for character from that page (never from a search snippet, no ellipses), its kind, and company when the page is about a specific company.

Numbers and money go only in estimates, never in the text answers unless they are quoted in evidence. Each estimate row: quantity (affected_units, frequency_per_year, cost_per_occurrence, addressable_share, current_cost, failure_cost), low, high, unit (a currency code like USD for money, e.g. USD/year for yearly costs; addressable_share as a fraction 0-1), and its basis:
- source: the number of the evidence entry whose quote contains the supporting figure;
- analogous_company: the number of an evidence entry about a comparable company (company filled in);
- explicit_assumption: evidence 0 and the assumption written out.
If you have no basis for a number, leave it out: unknown is better than a guess. Several rows per quantity are allowed.
potential_value is computed from affected_units x frequency_per_year x cost_per_occurrence x addressable_share by the caller; do not state it.

willingness_to_pay: money already committed to this problem (awards, prizes, budgets, salaries), each with the number of the evidence entry that shows it."""


def system_prompt(min_searches: int) -> str:
    return SYSTEM_PROMPT.format(min_searches=min_searches)


def render_input(problem: dict, score: dict, investigation: dict | None) -> str:
    sources = "\n".join(f"- {s['title']} ({s['url']}) payment: {json.dumps(s['payment_signal'])}" for s in problem["sources"])
    if investigation is None:
        novelty = "not investigated"
    else:
        works = "\n".join(f"  - {w['title']} ({w['url']})" for w in investigation.get("closest_work", []))
        novelty = (f"status: {investigation['novelty']['status']}\n"
                   f"strongest counterargument: {investigation.get('strongest_counterargument', '')}\n"
                   f"closest work:\n{works}")
    return (f"<problem id=\"{problem['problem_id']}\">\n"
            f"<statement>{problem['problem']['precise_statement']}</statement>\n"
            f"<desired_capability>{problem['desired_capability']}</desired_capability>\n"
            f"<why_it_matters>{problem['why_it_matters']}</why_it_matters>\n"
            f"<known_solution>{problem['current_state']['known_solution']}</known_solution>\n"
            f"<stated_in>\n{sources}\n</stated_in>\n</problem>\n"
            f"<money_already_found>{json.dumps(score)}</money_already_found>\n"
            f"<novelty_investigation>\n{novelty}\n</novelty_investigation>")
