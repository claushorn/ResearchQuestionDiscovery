from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, NamedTuple

if TYPE_CHECKING:
    from sourcescout.http import Fetcher
    from sourcescout.registry import Source


@dataclass(frozen=True)
class RawItem:
    source_id: str
    url: str
    title: str
    published: str | None
    text: str
    links: tuple[str, ...] = ()


IsKnown = Callable[[str], bool]
FetchFn = Callable[["Source", "Fetcher", IsKnown], list[RawItem]]


class Kind(NamedTuple):
    fetch: FetchFn
    required_params: tuple[str, ...] = ()
