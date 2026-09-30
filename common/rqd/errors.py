class RqdError(Exception):
    """Deterministic, operator-fixable failure. The CLI prints message + fix and exits 1."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.fix = fix


class ConfigError(RqdError):
    pass


class ExtractionConfigError(RqdError):
    pass


class ItemExtractionError(Exception):
    """External failure extracting one item; the item is marked failed and the run continues."""


class SourceFetchError(Exception):
    """External failure while fetching one source; recorded and reported, the run continues."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status  # the HTTP status for an HTTP error response


class AgentError(ItemExtractionError):
    """An agent session (claude -p with tools) ended without a usable result; the transcript is kept for audit."""

    def __init__(self, message: str, transcript: str = ""):
        super().__init__(message)
        self.transcript = transcript
