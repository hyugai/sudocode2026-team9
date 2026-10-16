"""Transcribe a recording locally without starting the agent or calling an LLM."""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

from telesale_agent.adapters.asr import ZipformerASREngine
from telesale_agent.core.models import Channel, ConversationState, TurnContext, TurnInput


async def main(path: Path) -> None:
    engine = ZipformerASREngine()
    with path.open("rb") as source:
        audio = source.read(engine.config.max_upload_bytes + 1)
    context = TurnContext(
        input=TurnInput(conversation_id="local-asr-check", audio=audio, channel=Channel.VOICE),
        state=ConversationState(conversation_id="local-asr-check"),
    )
    print(await engine.transcribe(context))


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.file))
