from types import SimpleNamespace

from test_extract import add_item, cand, ctx, message  # noqa: F401  (fixture re-export)
from sourcescout.extract import run_extraction
from sourcescout.store import item_id_for


class FakeBatches:
    def __init__(self, results_by_batch=None):
        self.created = []
        self.results_by_batch = results_by_batch or {}
        self.polls = 0

    def create(self, requests):
        bid = f"b{len(self.created) + 1}"
        self.created.append(requests)
        self.results_by_batch.setdefault(bid, [
            SimpleNamespace(custom_id=r["custom_id"],
                            result=SimpleNamespace(type="succeeded", message=message({"candidates": [cand()]})))
            for r in requests])
        return SimpleNamespace(id=bid, processing_status="in_progress")

    def retrieve(self, batch_id):
        self.polls += 1
        return SimpleNamespace(id=batch_id, processing_status="ended" if self.polls > 1 else "in_progress")

    def results(self, batch_id):
        return iter(self.results_by_batch[batch_id])


def client_with(batches):
    return SimpleNamespace(messages=SimpleNamespace(batches=batches))


def test_batch_submit_and_collect(ctx):
    add_item(ctx, "https://g.example/1")
    add_item(ctx, "https://g.example/2")
    batches = FakeBatches()
    sleeps = []
    run_extraction(ctx, client_with(batches), batch=True, sleep=sleeps.append)
    [requests] = batches.created
    assert {r["custom_id"] for r in requests} == {item_id_for("https://g.example/1"), item_id_for("https://g.example/2")}
    assert requests[0]["params"]["output_config"]["format"]["type"] == "json_schema"
    assert sleeps == [ctx.cfg.batch_poll_seconds]
    assert ctx.report.extract["g"].candidates == 2 and ctx.store.pending() == []


def test_resume_collects_previously_submitted_batch(ctx):
    add_item(ctx, "https://g.example/1")
    [item] = ctx.store.pending()
    ctx.store.mark_submitted([item.item_id], "old")
    old = [SimpleNamespace(custom_id=item.item_id,
                           result=SimpleNamespace(type="succeeded", message=message({"candidates": [cand()]})))]
    batches = FakeBatches({"old": old})
    run_extraction(ctx, client_with(batches), batch=True, sleep=lambda s: None)
    assert batches.created == []  # nothing resubmitted
    assert ctx.report.extract["g"].candidates == 1 and ctx.store.submitted_batch_ids() == []


def test_expired_goes_back_to_pending_and_errored_fails(ctx):
    add_item(ctx, "https://g.example/1")
    add_item(ctx, "https://g.example/2")
    a, b = [i.item_id for i in ctx.store.pending()]
    ctx.store.mark_submitted([a, b], "old")
    results = [SimpleNamespace(custom_id=a, result=SimpleNamespace(type="expired")),
               SimpleNamespace(custom_id=b, result=SimpleNamespace(type="errored", error="invalid_request"))]
    batches = FakeBatches({"old": results})
    # expired item is resubmitted in the same run and succeeds there
    run_extraction(ctx, client_with(batches), batch=True, sleep=lambda s: None)
    assert len(batches.created) == 1 and [r["custom_id"] for r in batches.created[0]] == [a]
    assert ctx.store.get(b).extract_status == "failed"
    assert ctx.store.get(a).extract_status == "done"
