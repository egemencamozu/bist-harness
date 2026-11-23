"""Exception hierarchy. Every error the harness can raise on purpose derives from BistHarnessError."""

from __future__ import annotations


class BistHarnessError(Exception):
    """Base class for all intentional errors."""


class ConfigError(BistHarnessError):
    """Invalid or inconsistent configuration (universe.yaml / settings.yaml)."""


class AsOfRequiredError(BistHarnessError):
    """A data access was attempted without a valid as_of_date."""


class LookAheadError(BistHarnessError):
    """Data with a knowledge date after as_of_date reached a caller. Always a hard block."""


class DataNotFoundError(BistHarnessError):
    """Requested ticker/series/period is not present in the store."""


class SnapshotIntegrityError(BistHarnessError):
    """A frozen raw snapshot does not match its manifest (file changed or missing)."""
