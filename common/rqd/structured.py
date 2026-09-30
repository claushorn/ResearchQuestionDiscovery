from pydantic import BaseModel

_DROP = {"title", "default", "maxLength", "minLength", "maxItems", "minItems", "minimum", "maximum",
         "exclusiveMinimum", "exclusiveMaximum"}


def _sanitize(node):
    # structured outputs accept optional properties; pydantic already lists only fields without defaults in "required"
    if isinstance(node, list):
        return [_sanitize(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in _DROP:
            continue
        out[k] = {name: _sanitize(sub) for name, sub in v.items()} if k in ("properties", "$defs") else _sanitize(v)
    if out.get("type") == "object":
        out["additionalProperties"] = False
    return out


def api_schema(model: type[BaseModel]) -> dict:
    """JSON schema accepted by output_config.format (unsupported constraints removed; Pydantic enforces them)."""
    return _sanitize(model.model_json_schema())
