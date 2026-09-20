"""Domain-specific exceptions with actionable failure messages."""


class PolymerLabError(Exception):
    """Base exception for the platform."""


class DependencyUnavailable(PolymerLabError):
    """A requested production adapter is not installed."""


class ValidationError(PolymerLabError):
    """A candidate or result failed validation."""


class BudgetExceeded(PolymerLabError):
    """A campaign action would exceed a configured budget."""


class ApprovalRequired(PolymerLabError):
    """An expensive operation has no valid approval."""


class InvalidStateTransition(PolymerLabError):
    """A persisted job or campaign transition is invalid."""


class ScientificResultError(PolymerLabError):
    """A physics result is incomplete, malformed, or unconverged."""
