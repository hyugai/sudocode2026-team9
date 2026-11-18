"""Lazy model creation; usage belongs to learning reports, never TurnResult."""
import json
import re
from self_agent.guardrails import UNTRUSTED_DATA_POLICY


def parse_json_content(content, *, root_array_key=None):
    """LangChain providers return either a string or typed content blocks."""
    if isinstance(content, list):
        content = "".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in content
            if isinstance(block, str) or (isinstance(block, dict)
                and block.get("type") in {"text", "output_text"}
                and isinstance(block.get("text"), str)))
    if not isinstance(content, str):
        raise ValueError("Learning model response has no text content")
    content = content.strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.S | re.I)
    if fence:
        content = fence.group(1).strip()
    value = json.loads(content)
    if root_array_key and isinstance(value,list) and all(isinstance(item,dict) for item in value):
        value={root_array_key:value}
    if not isinstance(value, dict):
        raise ValueError("Learning model must return a JSON object")
    return value


class LearningModel:
    def __init__(self):
        self.model = None
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    async def candidates(self,instruction,payload):
        # The detector contract permits an array of candidates. Normalize a
        # bare array at this boundary only; all verdict/lesson APIs stay strict.
        return await self.json(instruction,payload,root_array_key='gaps')

    async def json(self, instruction, payload, *, root_array_key=None):
        if self.model is None:
            from telesale_agent.adapters.llm.model_factory import create_chat_model
            self.model = create_chat_model(temperature=0, max_output_tokens=4096, thinking_level="minimal")
        for attempt in range(2):
            try:
                response = await self.model.ainvoke([
                    ("system", instruction + " Return only a compact JSON object, no prose or markdown. " +
                     UNTRUSTED_DATA_POLICY +
                     (' The previous response was not a valid JSON object; correct the format.' if attempt else '')),
                    ("human", json.dumps(payload, ensure_ascii=False))])
            except Exception as exc:
                exc.learning_diagnostics = {'stage':'provider_request','error':type(exc).__name__}
                raise
            usage = getattr(response, "usage_metadata", None) or {}
            for key in self.usage:
                self.usage[key] += usage.get(key) or 0
            try:
                return parse_json_content(response.content,root_array_key=root_array_key)
            except (ValueError, TypeError) as exc:
                if attempt:
                    metadata=getattr(response,'response_metadata',{}) or {}
                    reason=str(metadata.get('finish_reason','unknown'))
                    exc.learning_diagnostics = {'stage':'parse_json','error':type(exc).__name__,
                        'content_type':type(response.content).__name__,
                        'content_chars':len(str(response.content)),
                        'finish_reason':reason if reason in {'STOP','MAX_TOKENS','SAFETY','RECITATION','OTHER','unknown','stop','length'} else 'other',
                        'attempts':attempt+1}
                    raise
