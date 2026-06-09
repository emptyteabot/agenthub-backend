import json
from abc import ABC, abstractmethod

from openai.types.chat import ChatCompletionMessageParam

from app.agents.schemas import CoderOutput, SearchOutput
from app.core.llm_client import AsyncLLMClient


class BaseAgentAdapter(ABC):
    @abstractmethod
    async def execute_task(self, prompt: str, system_prompt: str) -> str:
        raise NotImplementedError


class CodexAdapter(BaseAgentAdapter):
    def __init__(self, client: AsyncLLMClient) -> None:
        self.client = client

    async def execute_task(self, prompt: str, system_prompt: str) -> str:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        if _wants_code(prompt):
            response = await self.client.client.beta.chat.completions.parse(
                model=self.client.model,
                messages=messages,
                response_format=CoderOutput,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError("Codex adapter failed to produce CoderOutput")
            return parsed.model_dump_json()
        if _wants_search(prompt):
            response = await self.client.client.beta.chat.completions.parse(
                model=self.client.model,
                messages=messages,
                response_format=SearchOutput,
            )
            parsed = response.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError("Codex adapter failed to produce SearchOutput")
            return parsed.model_dump_json()
        response = await self.client.agenerate(messages=messages)
        return response.choices[0].message.content or ""


class ClaudeCodeAdapter(BaseAgentAdapter):
    async def execute_task(self, prompt: str, system_prompt: str) -> str:
        if _wants_code(prompt):
            return json.dumps(
                {
                    "code": "print('Claude Code adapter completed the delegated task')\n",
                    "explanation": "Claude Code adapter produced an isolated executable artifact.",
                    "language": "python",
                },
                ensure_ascii=False,
            )
        if _wants_search(prompt):
            return json.dumps(
                {
                    "summary": "Claude Code adapter completed the requested external lookup simulation.",
                    "sources": ["mock://claude-code-adapter"],
                },
                ensure_ascii=False,
            )
        return f"Claude Code adapter response: {system_prompt[:80]} | {prompt[:160]}"


class OpenCodeAdapter(BaseAgentAdapter):
    async def execute_task(self, prompt: str, system_prompt: str) -> str:
        if _wants_code(prompt):
            return json.dumps(
                {
                    "code": "print('OpenCode adapter completed the delegated task')\n",
                    "explanation": "OpenCode adapter produced a deterministic platform artifact.",
                    "language": "python",
                },
                ensure_ascii=False,
            )
        if _wants_search(prompt):
            return json.dumps(
                {
                    "summary": "OpenCode adapter completed the requested platform lookup simulation.",
                    "sources": ["mock://opencode-adapter"],
                },
                ensure_ascii=False,
            )
        return f"OpenCode adapter response: {system_prompt[:80]} | {prompt[:160]}"


def build_agent_adapter(driver: str, client: AsyncLLMClient) -> BaseAgentAdapter:
    normalized = driver.strip().lower()
    if normalized in {"claude", "claude-code", "claudecode"}:
        return ClaudeCodeAdapter()
    if normalized in {"opencode", "open-code", "open_code"}:
        return OpenCodeAdapter()
    return CodexAdapter(client)


def _wants_code(prompt: str) -> bool:
    lowered = prompt.lower()
    return all(token in lowered for token in ("code", "explanation", "language"))


def _wants_search(prompt: str) -> bool:
    lowered = prompt.lower()
    return all(token in lowered for token in ("summary", "sources"))
