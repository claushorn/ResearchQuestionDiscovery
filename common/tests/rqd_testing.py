"""Test helpers shared by all capability test suites (unique module name: no conftest collisions)."""
import json

import httpx

from rqd.config import HttpCfg
from rqd.http import Fetcher


def make_fetcher(routes: dict, robots: str | None = None, sleeps: list | None = None) -> Fetcher:
    """routes: {"GET https://x/y": str | dict | list | httpx.Response | Exception}"""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=robots) if robots is not None else httpx.Response(404)
        value = routes.get(f"{request.method} {url}")
        if value is None:
            return httpx.Response(404)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, httpx.Response):
            return value
        if isinstance(value, (dict, list)):
            return httpx.Response(200, json=value)
        return httpx.Response(200, text=value)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    record = sleeps if sleeps is not None else []
    return Fetcher(HttpCfg(user_agent="test-agent", timeout_s=5, min_interval_s_per_host=0.0),
                   client=client, sleep=record.append)


# stream-json events as emitted by `claude -p --output-format stream-json` (recorded from claude 2.1.285)
def tool_use(name, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def agent_result(**kw):
    base = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 5, "duration_ms": 26044,
            "total_cost_usd": 0.1257, "terminal_reason": "completed", "structured_output": {"a": "x"},
            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 900, "cache_read_input_tokens": 10036,
                      "output_tokens": 1608}, "api_error_status": None, "result": None}
    return base | kw


def stream(*events):
    return "\n".join(json.dumps(e) for e in [{"type": "system", "subtype": "init"}, *events]) + "\n"


def pdf_bytes(text: str) -> bytes:
    """A minimal one-page PDF whose page shows `text` (Helvetica), enough for pypdf text extraction."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
