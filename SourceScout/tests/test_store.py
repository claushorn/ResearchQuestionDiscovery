from sourcescout.adapters.base import RawItem
from sourcescout.store import Store, canonical_url, item_id_for

T0, T1 = "2026-09-30T10:00:00+00:00", "2026-10-01T10:00:00+00:00"


def item(text="body", url="https://a.example/x", links=()):
    return RawItem("s1", url, "Title", None, text, tuple(links))


def test_canonical_url():
    assert canonical_url("HTTPS://A.example/x/?utm_source=z&id=3#frag") == "https://a.example/x?id=3"
    assert item_id_for("https://a.example/x/") == item_id_for("https://a.example/x?utm_medium=m")


def test_new_unchanged_changed(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    assert st.upsert(item(), T0, 1000) == ("new", False)
    assert st.is_known("https://a.example/x")
    assert st.upsert(item(), T1, 1000) == ("unchanged", False)
    st.mark_done(item_id_for("https://a.example/x"))
    assert st.pending() == []
    assert st.upsert(item("new body"), T1, 1000) == ("changed", False)
    [p] = st.pending()
    assert p.revision == 2 and p.text == "new body" and p.extract_status == "pending"


def test_truncation_is_reported_and_hash_stable(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    assert st.upsert(item("x" * 50), T0, 10) == ("new", True)
    assert st.pending()[0].text == "x" * 10
    assert st.upsert(item("x" * 50), T1, 10) == ("unchanged", True)


def test_batch_bookkeeping(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    st.upsert(item(url="https://a.example/1"), T0, 100)
    st.upsert(item(url="https://a.example/2"), T0, 100)
    ids = [i.item_id for i in st.pending()]
    st.mark_submitted(ids, "batch-1")
    assert st.pending() == [] and st.submitted_batch_ids() == ["batch-1"]
    assert set(st.items_in_batch("batch-1")) == set(ids)
    st.mark_failed(ids[0], "boom")
    st.reset_pending(ids[1])
    assert [i.item_id for i in st.pending()] == [ids[1]]
    assert st.get(ids[0]).extract_status == "failed"


def test_links_first_seen_since(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    st.upsert(item(url="https://a.example/1", links=["https://jobs.lever.co/acme"]), T0, 100)
    st.upsert(item(url="https://a.example/2", links=["https://b.example"]), T1, 100)
    assert [l for l, _ in st.links_first_seen_since(T1)] == ["https://b.example"]


def test_status_counts_and_retry_failed(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    st.upsert(item(url="https://a.example/1"), T0, 100)
    st.upsert(item(url="https://a.example/2"), T0, 100)
    a, b = [i.item_id for i in st.pending()]
    st.mark_failed(a, "boom")
    assert st.status_counts() == {"failed": 1, "pending": 1}
    assert st.reset_failed() == 1 and st.status_counts() == {"pending": 2}
