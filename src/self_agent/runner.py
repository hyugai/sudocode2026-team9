"""Standalone session runner. Never imported by the existing benchmark."""
import argparse
import asyncio
from .config import LearningConfig


async def run(args):
    from dotenv import load_dotenv
    load_dotenv()
    config = LearningConfig.from_env()
    # Keep the configured DB/Pinecone retrieval untouched. Learning reuses the
    # base harness's read-only search_policy tool; it does not select a new DB.
    from telesale_agent.bootstrap import build_deepagent_harness
    from telesale_agent.core.models import ConversationState, TurnInput
    from .harness import SelfAgentHarness
    import uuid
    sid = "self-agent-" + uuid.uuid4().hex
    state = ConversationState(sid)
    async with SelfAgentHarness(build_deepagent_harness(), config=config) as agent:
        turn_results = []
        for question in args.questions:
            result = await agent.run_turn(TurnInput(sid, text=question), state)
            state = result.state
            turn_results.append(result)
            print(result.response_text)
        job = await agent.end_session(state, turn_results=turn_results)
        print(job)
        if job.job_id:
            print(await agent.wait_learning(job.job_id))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("questions", nargs="+")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
