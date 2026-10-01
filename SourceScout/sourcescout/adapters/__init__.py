from sourcescout.adapters import grants_gov, jobboards, rss, talks, webpage
from sourcescout.adapters.base import IsKnown, Kind, RawItem

KINDS: dict[str, Kind] = {
    "rss": Kind(rss.fetch),
    "greenhouse": Kind(jobboards.fetch_greenhouse),
    "lever": Kind(jobboards.fetch_lever),
    "ashby": Kind(jobboards.fetch_ashby),
    "grants_gov": Kind(grants_gov.fetch, ("keyword",)),
    "html_list": Kind(webpage.fetch_list, ("link_selector",)),
    "page": Kind(webpage.fetch_page),
    "json_sessions": Kind(talks.fetch_json_sessions, ("items_path", "title_field", "text_fields")),
    "html_sections": Kind(talks.fetch_html_sections, ("section_selector",)),
}
REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {k: v.required_params for k, v in KINDS.items()}

__all__ = ["KINDS", "REQUIRED_PARAMS", "IsKnown", "Kind", "RawItem"]
