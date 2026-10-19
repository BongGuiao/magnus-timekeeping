class ScheduleUploadError(ValueError):
    """Base class for schedule upload rule failures; transport layers translate subclasses."""


class ScheduleUploadNotFoundError(ScheduleUploadError):
    pass


class ScheduleUploadPermissionError(ScheduleUploadError):
    pass


class ScheduleUploadStateError(ScheduleUploadError):
    pass


class ScheduleUploadRejectedFileError(ScheduleUploadError):
    """The uploaded file failed validation, so no batch was created."""

    def __init__(self, error_count: int):
        self.error_count = error_count
        super().__init__(
            f"The file has {error_count} validation error(s). "
            "Preview the file to see the affected rows, correct them, and upload again."
        )


class ScheduleUploadNoLongerApplicableError(ScheduleUploadError):
    """A pending batch failed re-validation at approval time."""

    def __init__(self, messages: list[str]):
        self.messages = messages
        shown = "; ".join(messages[:5])
        more = f" (and {len(messages) - 5} more)" if len(messages) > 5 else ""
        super().__init__(
            f"This batch can no longer be applied: {shown}{more}. "
            "Reject it and ask the supervisor to upload a corrected file."
        )
