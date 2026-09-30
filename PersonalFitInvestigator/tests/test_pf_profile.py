import pytest

from pf_testing import make_profile
from personalfit.profile import load_profile
from rqd.errors import ConfigError


def test_loads_all_supported_files_sorted_with_pdf_text(tmp_path):
    p = load_profile(make_profile(tmp_path / "pp"), 10_000)
    assert [f.path for f in p.files] == ["capabilities.yaml", "cv.md", "cv_long.pdf", "interests.yml"]
    assert "data leakage problem" in p.files[2].text and len(p.digest) == 64


def test_digest_changes_when_a_file_changes(tmp_path):
    d = make_profile(tmp_path / "pp")
    before = load_profile(d, 10_000).digest
    (d / "notes.txt").write_text("Taught himself to program at the age of 10.", encoding="utf-8")
    assert load_profile(d, 10_000).digest != before


@pytest.mark.parametrize("setup, match", [
    (lambda d: None, "not found"),
    (lambda d: d.mkdir(), "no profile files"),
    (lambda d: (d.mkdir(), (d / "photo.png").write_bytes(b"x")), "unsupported"),
    (lambda d: (d.mkdir(), (d / "big.md").write_text("x" * 200)), "too large"),
])
def test_profile_problems_are_clean_config_errors(tmp_path, setup, match):
    d = tmp_path / "pp"
    setup(d)
    with pytest.raises(ConfigError, match=match) as e:
        load_profile(d, 100)
    assert e.value.fix
