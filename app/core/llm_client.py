import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import TypeVar

from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam, ChatCompletionToolParam
from pydantic import BaseModel

DEFAULT_BASE_URL = "https://geekspace.cloud/v1"
DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "gpt-4o-mini"

ParsedModel = TypeVar("ParsedModel", bound=BaseModel)

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)


class _MockCompletions:
    async def parse(
        self,
        messages: list[ChatCompletionMessageParam],
        response_format: type[ParsedModel],
        **_: object,
    ) -> SimpleNamespace:
        task = _last_user_content(messages)
        parsed = response_format.model_validate(_mock_structured_payload(task, response_format))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))])


class _MockClient:
    def __init__(self) -> None:
        completions = _MockCompletions()
        self.chat = SimpleNamespace(completions=completions)
        self.beta = SimpleNamespace(chat=SimpleNamespace(completions=completions))


class AsyncLLMClient:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        driver: str | None = None,
        mock_mode: bool | None = None,
    ) -> None:
        self.driver = (driver or os.getenv("LLM_DRIVER", "openai")).lower()
        self.mock_mode = _env_bool("MOCK_MODE") if mock_mode is None else mock_mode
        if self.mock_mode:
            self.driver = "mock"
            self.model = model or os.getenv("MODEL", "mock-local")
            self.client: AsyncOpenAI | _MockClient = _MockClient()
            return

        if self.driver in {"ark", "doubao"}:
            self.model = model or os.environ["ENDPOINT_ID"]
            self.client = AsyncOpenAI(
                base_url=base_url or os.getenv("ARK_BASE_URL", DEFAULT_ARK_BASE_URL),
                api_key=api_key or os.environ["ARK_API_KEY"],
            )
            return

        self.model = model or os.getenv("MODEL", DEFAULT_MODEL)
        self.client = AsyncOpenAI(
            base_url=_openai_base_url(base_url or os.getenv("BASE_URL", DEFAULT_BASE_URL)),
            api_key=api_key or os.environ["API_KEY"],
        )

    async def agenerate(
        self,
        messages: list[ChatCompletionMessageParam],
        tools: list[ChatCompletionToolParam] | None = None,
        **kwargs: object,
    ) -> ChatCompletion:
        if self.mock_mode:
            return _mock_completion(messages, tools)

        request: dict[str, object] = {
            "model": kwargs.pop("model", self.model),
            "messages": messages,
        }
        if tools is not None:
            request["tools"] = tools
        request.update(kwargs)
        return await self.client.chat.completions.create(**request)


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _openai_base_url(value: str) -> str:
    url = value.rstrip("/")
    if url.endswith("/v1"):
        return url
    return f"{url}/v1"


def _mock_completion(
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam] | None,
) -> ChatCompletion:
    content = _last_user_content(messages)
    if tools:
        name = _mock_route(content, tools)
        args: dict[str, str] = {
            "thought": "Use the registered agent that best matches the request.",
            "task_description": content,
        }
        tool_call = SimpleNamespace(
            function=SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False))
        )
        message = SimpleNamespace(tool_calls=[tool_call], content=None)
    else:
        message = SimpleNamespace(tool_calls=None, content=f"Mock response: {content}")
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _mock_route(content: str, tools: list[ChatCompletionToolParam]) -> str:
    text = content.lower()
    search_keywords = (
        "\u67e5",
        "\u641c\u7d22",
        "\u4eca\u5929",
        "\u6700\u65b0",
        "\u80a1\u4ef7",
        "\u80a1\u7968",
        "\u65b0\u95fb",
        "\u82f1\u4f1f\u8fbe",
        "search",
        "price",
        "stock",
        "latest",
    )
    wants_search = any(keyword in text for keyword in search_keywords)
    preferred = ("search", "\u641c\u7d22") if wants_search else (
        "code",
        "debug",
        "implement",
        "\u4ee3\u7801",
    )
    for tool in tools:
        function = tool["function"]
        description = str(function.get("description", "")).lower()
        if any(token in description for token in preferred):
            return str(function["name"])
    return str(tools[0]["function"]["name"])


def _last_user_content(messages: list[ChatCompletionMessageParam]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            value = message.get("content", "")
            return value if isinstance(value, str) else str(value)
    return ""


def _mock_structured_payload(
    task: str,
    response_format: type[ParsedModel],
) -> dict[str, object]:
    fields = set(response_format.model_fields)
    if {"summary", "sources"}.issubset(fields):
        return {
            "summary": f"Mock search completed for: {task}",
            "sources": ["mock://dynamic-search-agent"],
        }
    if {"code", "explanation", "language"}.issubset(fields):
        language = "html" if _html_requested(task) else "python"
        return {
            "code": _mock_code(task),
            "explanation": "Local Mock Coder Agent generated a structured code artifact.",
            "language": language,
        }
    return {"content": f"Mock agent response: {task}"}


def _mock_code(task: str) -> str:
    text = task.lower()
    if _html_requested(task):
        return (
            "<!doctype html>\n"
            "<html lang=\"zh-CN\">\n"
            "<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>AgentHub Live Preview</title>\n"
            "<style>\n"
            "body{margin:0;font-family:Inter,Arial,sans-serif;background:#0f172a;color:#e5e7eb;}\n"
            "main{min-height:100vh;display:grid;place-items:center;padding:40px;}\n"
            "section{max-width:760px;border:1px solid #334155;background:#111827;padding:32px;}\n"
            "h1{font-size:42px;margin:0 0 16px;color:#38bdf8;}\n"
            "p{font-size:18px;line-height:1.7;color:#cbd5e1;}\n"
            "</style>\n"
            "</head>\n"
            "<body>\n"
            "<main><section><h1>AgentHub 实时预览</h1><p>HTML artifact has been written to the session workspace and rendered through the static workspace mount.</p></section></main>\n"
            "</body>\n"
            "</html>\n"
        )
    hitl_requested = any(
        token in text
        for token in (
            "hitl",
            "requires_human",
            "loop test",
            "dead loop",
            "semantic loop",
            "fail repeatedly",
            "repeated failure",
            "syntax failure",
            "\u6b7b\u5faa\u73af\u6d4b\u8bd5",
            "\u4eba\u5de5\u63a5\u7ba1",
        )
    )
    resumed = any(
        token in text
        for token in (
            "human feedback",
            "resume",
            "hitl resume",
        )
    )
    if hitl_requested and not resumed:
        return "def broken_loop(:\n    return 1\n"
    quicksort_requested = any(
        token in text
        for token in (
            "quick sort",
            "quicksort",
            "\u5feb\u6392",
            "\u5feb\u901f\u6392\u5e8f",
        )
    )
    if quicksort_requested:
        return (
            "def quick_sort(items):\n"
            "    if len(items) <= 1:\n"
            "        return items\n"
            "    pivot = items[len(items) // 2]\n"
            "    left = [item for item in items if item < pivot]\n"
            "    middle = [item for item in items if item == pivot]\n"
            "    right = [item for item in items if item > pivot]\n"
            "    return quick_sort(left) + middle + quick_sort(right)\n"
            "\n"
            "if __name__ == \"__main__\":\n"
            "    print(quick_sort([5, 3, 8, 4, 2, 7, 1, 10]))\n"
        )
    if hitl_requested and resumed:
        return "print('HITL resume completed')\n"
    return "print('Mock Coder Agent artifact')\n"


def _html_requested(task: str) -> bool:
    text = task.lower()
    return any(
        token in text
        for token in (
            "html",
            "web page",
            "webpage",
            "landing page",
            "\u7f51\u9875",
            "\u9875\u9762",
            "\u524d\u7aef\u9875",
        )
    )
