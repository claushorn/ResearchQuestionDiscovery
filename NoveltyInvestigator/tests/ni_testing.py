"""Helpers for NoveltyInvestigator tests (unique module name: no conftest collisions across capabilities)."""


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


def ni_output(**over) -> dict:
    base = {"novelty_status": "partially_solved",
            "already_solved": "partially", "already_solved_reasoning": "AlphaFold solves most of it", "already_solved_evidence": [1],
            "same_problem_paper": "yes", "same_problem_paper_reasoning": "Jumper et al.", "same_problem_paper_evidence": [1],
            "merely_implementation_issue": "no", "merely_implementation_issue_reasoning": "needs new methods",
            "merely_implementation_issue_evidence": [],
            "obvious_baseline": "yes", "obvious_baseline_description": "run AlphaFold2", "obvious_baseline_reasoning": "public",
            "obvious_baseline_evidence": [1],
            "obvious_approaches_tried": "yes", "obvious_approaches_tried_reasoning": "many groups", "obvious_approaches_tried_evidence": [2],
            "closest_work": [{"title": "AlphaFold2", "url": "https://paper.example/af2", "year": 2021, "kind": "paper",
                              "quote": "predicts protein structures with atomic accuracy", "how_close": "solves it for monomers"},
                             {"title": "RoseTTAFold", "url": "https://paper.example/rf.pdf", "year": 2021, "kind": "paper",
                              "quote": "three-track network", "how_close": "similar"}],
            "difference_from_closest_work": "complexes remain harder",
            "strongest_counterargument": "the core problem is solved",
            "confidence": 0.8}
    return base | over


def problem_record(pid: str = "prob-abc-r1-0") -> dict:
    return {"problem_id": pid, "revision": 1,
            "problem": {"precise_statement": "Predict 3D protein structure from sequence at near-experimental accuracy."},
            "current_state": {"known_solution": "not stated"}, "failure": {"what_current_methods_cannot_do": "not stated"},
            "desired_capability": "atomic-accuracy structures", "why_it_matters": "drug design",
            "unsolvedness": {"explicit": False, "explicit_evidence": "", "inferred": True, "evidence_verified": None},
            "sources": [{"candidate_id": "cand-abc-r1-0", "source_id": "grants-gov-protein", "tier": "A",
                         "url": "https://g.example/1", "title": "Call 1",
                         "payment_signal": {"type": "grant", "stated": "$1M", "deadline": None}}],
            "merge_log": [], "extracted_with": {"model": "m", "run_id": "R", "output_tokens": 500, "at": "t"}}
