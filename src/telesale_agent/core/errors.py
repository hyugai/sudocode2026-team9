class PipelineStageError(RuntimeError):
    """Error raised when one named pipeline stage fails."""

    def __init__(self, stage: str, conversation_id: str, cause: Exception) -> None:
        self.stage = stage
        self.conversation_id = conversation_id
        self.cause = cause
        super().__init__(
            f"stage '{stage}' failed for conversation '{conversation_id}': {cause}"
        )


class AgentLoopLimitError(RuntimeError):
    """Error raised when the agent does not finish within the configured limit."""


class AudioInputError(ValueError):
    """The uploaded recording cannot be used as a conversation turn."""


class AudioTooLargeError(AudioInputError):
    """The recording exceeds the configured upload size."""


class ASRUnavailableError(RuntimeError):
    """Local speech recognition dependencies or model files are unavailable."""

