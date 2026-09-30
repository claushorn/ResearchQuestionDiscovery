import re

from rqd.errors import RqdError
from rqd.records import YamlStore


def opp_id_for(store: YamlStore, problem_id: str) -> str:
    """The problem's existing OPP id, else the next free one (OPP-0001, OPP-0002, ...)."""
    paths = sorted(store.dir.glob("*.yaml")) if store.dir.is_dir() else []
    records = []
    for path in paths:
        r = store.load(path.stem)
        if not isinstance(r, dict) or not re.fullmatch(r"OPP-\d+", str(r.get("id"))) or "problem_id" not in r \
                or r["id"] != path.stem:
            raise RqdError(f"{path} is not an opportunity record (id / problem_id missing or not matching its name)",
                           fix=f"Move {path.name} out of {store.dir}")
        records.append(r)
    for r in records:
        if r["problem_id"] == problem_id:
            return r["id"]
    return f"OPP-{max((int(r['id'][4:]) for r in records), default=0) + 1:04d}"
