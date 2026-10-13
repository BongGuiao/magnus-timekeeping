class AttendanceRuleError(ValueError):
    """Base class for business-rule failures; transport layers translate subclasses."""


class RecordNotFoundError(AttendanceRuleError):
    pass


class ConflictError(AttendanceRuleError):
    pass


class RuleViolationError(AttendanceRuleError):
    pass


class PermissionDeniedError(AttendanceRuleError):
    pass


class SnapshotUnavailableError(AttendanceRuleError):
    pass
