"""Next-stage actions per page: each runs the stage's own CLI on the selected ids (an Agent Task)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    key: str
    label: str      # button text: "Run <label>"
    page: str       # the page whose selection it takes: candidates | problems | challenges


ACTIONS = {a.key: a for a in [
    Action("extract", "extraction", "candidates"),
    Action("novelty", "novelty", "problems"),
    Action("economic_value", "economic value", "problems"),
    Action("fit", "fit", "problems"),
    Action("generate", "generate opportunity", "problems"),
    Action("headroom", "headroom", "challenges"),
    Action("investigate", "investigate", "challenges"),
]}


def for_page(page: str) -> list[Action]:
    return [a for a in ACTIONS.values() if a.page == page]
