from sourcescout.adapters.base import IsKnown, RawItem
from sourcescout.adapters.jobboards import _json, _shape_error
from rqd.http import Fetcher, html_to_text
from sourcescout.registry import Source

DETAIL_URL = "https://api.grants.gov/v1/api/fetchOpportunity"


def fetch(source: Source, http: Fetcher, is_known: IsKnown,
          item_errors: list[str] | None = None) -> list[RawItem]:
    payload = {"keyword": source.params["keyword"],
               "oppStatuses": source.params.get("opp_statuses", "forecasted|posted"),
               "rows": int(source.params.get("rows", 50))}
    data = _json(http.post_json(source.url, payload), source.url)
    try:
        hits = data["data"]["oppHits"]
        items = []
        for h in hits:
            url = f"https://www.grants.gov/search-results-detail/{h['id']}"
            if is_known(url):
                continue
            detail = _json(http.post_json(DETAIL_URL, {"opportunityId": int(h["id"])}), DETAIL_URL)["data"]
            syn = detail.get("synopsis") or {}
            desc, links = html_to_text(syn.get("synopsisDesc") or "", url)
            text = "\n".join([
                f"Title: {h['title']}",
                f"Agency: {h.get('agency', '')}",
                f"Opportunity number: {h.get('number', '')}",
                f"Status: {h.get('oppStatus', '')}",
                f"Close date: {h.get('closeDate') or ''}",
                f"Award ceiling: {syn.get('awardCeilingFormatted') or ''}",
                f"Estimated total funding: {syn.get('estimatedFundingFormatted') or ''}",
                "",
                desc,
            ])
            items.append(RawItem(source.id, url, h["title"] or "", h.get("openDate"), text, tuple(links)))
        return items
    except (KeyError, TypeError, ValueError) as e:
        raise _shape_error(source.url, e) from e
