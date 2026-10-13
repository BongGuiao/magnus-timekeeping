class AuthRuleError(ValueError):
    """Base class for authentication business-rule failures; transport layers translate subclasses."""


class AccountNotFoundError(AuthRuleError):
    pass


class InvalidCredentialsError(AuthRuleError):
    pass


class PasswordPolicyError(AuthRuleError):
    pass


class AccountUnavailableError(AuthRuleError):
    """The account is inactive, pending, or administratively locked."""


class AccountLockedError(AuthRuleError):
    """Temporarily locked after too many failed attempts."""
