"""Custom exception hierarchy for yt2bili."""


class YT2BILIError(Exception):
    """Base exception for all yt2bili errors."""


class DownloadError(YT2BILIError):
    """Raised when video or subtitle download fails."""


class SubtitleError(YT2BILIError):
    """Raised when subtitle processing fails."""


class UploadError(YT2BILIError):
    """Raised when Bilibili upload fails."""


class AuthenticationError(YT2BILIError):
    """Raised when Bilibili credential authentication fails."""


class MonitorError(YT2BILIError):
    """Raised when RSS feed monitoring fails."""


class ConfigError(YT2BILIError):
    """Raised when configuration loading or validation fails."""


class TaskQueueError(YT2BILIError):
    """Raised when task queue operations fail."""
