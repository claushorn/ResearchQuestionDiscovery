class ScoutError(Exception):
    """Deterministic, operator-fixable failure. The CLI prints message + fix and exits 1."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.fix = fix


class ConfigError(ScoutError):
    pass


class RegistryError(ScoutError):
    pass


class ExtractionConfigError(ScoutError):
    pass


class SourceFetchError(Exception):
    """External failure while fetching one source; recorded and reported, the run continues."""
