from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, NamedTuple

if TYPE_CHECKING:
    from rqd.http import Fetcher
    from sourcescout.registry import Source


@dataclass(frozen=True)
class RawItem:
    source_id: str
    url: str
    title: str
    published: str | None
    text: str
    links: tuple[str, ...] = ()
    finished: bool = False     # the listing marks it finished (ended challenge): stored, never extracted
    status_only: bool = False  # already-known item whose only news is the finished flag (page not refetched)


IsKnown = Callable[[str], bool]
# fetch(source, http, is_known, item_errors=None): per-item fetch failures are appended to item_errors
# when a list is given (the source still succeeds); with None they raise SourceFetchError.
FetchFn = Callable[..., list[RawItem]]


def item_failed(item_errors: list[str] | None, url: str, e: Exception) -> None:
    if item_errors is None:
        raise e
    item_errors.append(f"{url}: {e}")


class Kind(NamedTuple):
    fetch: FetchFn
    required_params: tuple[str, ...] = ()
