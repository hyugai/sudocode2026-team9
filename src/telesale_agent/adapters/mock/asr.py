from telesale_agent.core.interfaces import ASREngine
from telesale_agent.core.models import TurnContext

class MockASREngine(ASREngine):
    """
    Mock ASR that simply extracts text from audio metadata if available,
    or falls back to user-provided text if it's already a text input.
    """
    async def transcribe(self, context: TurnContext) -> str | None:
        if context.input.audio:
            # In a real implementation, this would call Whisper or similar API
            # For mock, we pretend the audio translates to a specific hardcoded string
            # or extract it from metadata if passed for testing
            return context.input.metadata.get("mock_transcription", "[Mock Audio Transcript]")
            
        return context.input.text
