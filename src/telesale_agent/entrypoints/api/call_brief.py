from fastapi import Request

from telesale_agent.adapters.llm.call_brief_summary import GeminiCallBriefSummarizer


def get_call_brief_summarizer(request: Request) -> GeminiCallBriefSummarizer | None:
    return getattr(request.app.state, "call_brief_summarizer", None)


async def summarize_saved_brief(detail: dict, summarizer: GeminiCallBriefSummarizer | None) -> dict:
    messages = detail.pop("_brief_messages", None)
    brief = detail["call_brief"]
    if summarizer is not None and brief is not None and messages is not None:
        summary = await summarizer.summarize(brief, messages)
        if summary:
            detail["call_brief"] = {**brief, "summary": summary}
    return detail
