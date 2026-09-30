"""The user's profile: every file in personal_profile/ (git-ignored), read as evidence."""
import hashlib
from dataclasses import dataclass
from pathlib import Path

from rqd.errors import ConfigError, SourceFetchError
from rqd.http import pdf_to_text

TEXT = (".md", ".txt", ".yaml", ".yml")
SUPPORTED = TEXT + (".pdf",)


@dataclass(frozen=True)
class ProfileFile:
    path: str   # relative to the profile directory
    text: str


@dataclass(frozen=True)
class Profile:
    files: list[ProfileFile]
    digest: str  # changes whenever any file changes: fits made with another digest are stale

    def file(self, path: str) -> ProfileFile | None:
        return next((f for f in self.files if f.path == path), None)


def load_profile(directory: Path, max_chars: int) -> Profile:
    if not directory.is_dir():
        raise ConfigError(f"profile directory not found: {directory}",
                          fix="Create it and add your CV / notes (see PersonalFitInvestigator/README.md), or set profile_dir")
    paths = sorted(p for p in directory.rglob("*") if p.is_file() and not p.name.startswith("."))
    if not paths:
        raise ConfigError(f"no profile files in {directory}", fix="Add your CV / notes (see PersonalFitInvestigator/README.md)")
    bad = [p.name for p in paths if p.suffix.lower() not in SUPPORTED]
    if bad:
        raise ConfigError(f"unsupported profile file(s): {', '.join(bad)}",
                          fix=f"Convert to one of {', '.join(SUPPORTED)} or move them out of {directory}")
    files = []
    for p in paths:
        try:
            text = pdf_to_text(p.read_bytes()) if p.suffix.lower() == ".pdf" else p.read_text(encoding="utf-8")
        except (SourceFetchError, UnicodeDecodeError) as e:
            raise ConfigError(f"cannot read profile file {p}: {e}", fix="Replace it with a readable text or PDF file") from e
        files.append(ProfileFile(p.relative_to(directory).as_posix(), text))
    total = sum(len(f.text) for f in files)
    if total > max_chars:
        raise ConfigError(f"profile is too large: {total:,} characters > profile_max_chars {max_chars:,}",
                          fix="Remove or shorten files in the profile directory, or raise profile_max_chars")
    h = hashlib.sha256()
    for f in files:
        h.update(f.path.encode() + b"\0" + f.text.encode() + b"\0")
    return Profile(files, h.hexdigest())


def render(profile: Profile) -> str:
    return "\n".join(f'<file path="{f.path}">\n{f.text}\n</file>' for f in profile.files)
