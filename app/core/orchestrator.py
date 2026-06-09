import ast
import asyncio
import hashlib
import json
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import TypedDict

from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
from pydantic import BaseModel, ConfigDict, Field

from app.agents.schemas import CoderOutput, SearchOutput
from app.core.adapters import build_agent_adapter
from app.core.llm_client import AsyncLLMClient
from app.core.runner import AsyncCodeRunner
from app.core.sandbox import PythonSandbox
from app.core.workspace import WorkspaceManager
from app.db.models import Agent
from app.db.repositories import AgentRepository

MAX_RETRIES = 3


class ReviewResult(TypedDict):
    passed: bool
    summary: str
    error_feedback: str


class ExecutionSnapshot(TypedDict):
    tool_args_json: str
    ast_hash: str
    raw_text: str


class HumanFeedbackFrame(TypedDict):
    type: str
    content: str


@dataclass(frozen=True)
class Checkpoint:
    id: str
    context_messages: list[dict[str, str]]
    main_code: str | None


class MessageStep(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    agent: str
    content: str | None = None
    filename: str | None = None
    stages: list[dict[str, str]] | None = None
    loop_count: int | None = None
    passed: bool | None = None
    error_feedback: str | None = None
    artifact_code: str | None = None
    checkpoint_id: str | None = None


class DynamicAgentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thought: str = Field(description="Brief internal planning summary")
    task_description: str = Field(description="The concrete delegated task for this agent")


class GenericAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str


AgentOutput = CoderOutput | SearchOutput | GenericAgentOutput
StepPayload = dict[str, object]
HumanFeedbackReceiver = Callable[[], Awaitable[HumanFeedbackFrame]]


class DynamicOrchestrator:
    def __init__(
        self,
        client: AsyncLLMClient,
        session_id: int,
        agent_repository: AgentRepository,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        self.client = client
        self.session_id = session_id
        self.agent_repository = agent_repository
        self.workspace_manager = workspace_manager or WorkspaceManager()
        self.sandbox = PythonSandbox()
        self.runner = AsyncCodeRunner(self.workspace_manager)

    async def route_intent_stream(
        self,
        user_input: str,
        context_messages: Sequence[Mapping[str, str]] | None = None,
        human_feedback_receiver: HumanFeedbackReceiver | None = None,
    ) -> AsyncGenerator[StepPayload, None]:
        agents = await self.agent_repository.get_all_agents()
        tool_matrix = _build_tools(agents)
        durable_notes: list[str] = []
        execution_history: list[ExecutionSnapshot] = []
        active_context = _context_copy(context_messages or ())
        auto_retry_count = 0
        stagnation_count = 0

        while True:
            auto_retry_count += 1
            repair_note = durable_notes[-1] if durable_notes else None
            selected_agent, parsed_args = await self._plan(
                user_input,
                active_context,
                durable_notes,
                repair_note,
                tool_matrix,
            )
            checkpoint = self._create_checkpoint(active_context, auto_retry_count)
            yield _dump_step(
                MessageStep(
                    type="thought",
                    agent="\u7f16\u6392\u5668",
                    content=parsed_args.thought.strip(),
                    loop_count=auto_retry_count,
                    checkpoint_id=checkpoint.id,
                )
            )
            yield _dump_step(_flow_step(selected_agent.name, auto_retry_count, checkpoint.id))

            output = await self._act(selected_agent, parsed_args, repair_note)
            if isinstance(output, CoderOutput):
                self.workspace_manager.write_file(
                    self.session_id,
                    _artifact_path(output.language),
                    output.code,
                )
            async for step in _artifact_steps(selected_agent, output, auto_retry_count, checkpoint.id):
                yield _dump_step(step)

            review = await self._verify_artifact(user_input, selected_agent, output)
            yield _dump_step(
                MessageStep(
                    type="review",
                    agent="\u7f16\u6392\u5668",
                    content=review["summary"],
                    loop_count=auto_retry_count,
                    passed=review["passed"],
                    error_feedback=review["error_feedback"],
                    checkpoint_id=checkpoint.id,
                )
            )

            print(f"[Router] Selected Agent: {selected_agent.name}")
            if review["passed"]:
                return

            self._restore_checkpoint(checkpoint)
            active_context = checkpoint.context_messages
            durable_notes.append(review["error_feedback"])
            execution_history.append(_execution_snapshot(parsed_args, output))
            loop_score = self._calculate_loop_score(execution_history)
            stagnation_count = stagnation_count + 1 if loop_score >= 2 else 0
            requires_human = stagnation_count >= 2 or auto_retry_count >= MAX_RETRIES
            if not requires_human:
                continue

            yield _human_required_step(checkpoint.id)
            if human_feedback_receiver is None:
                return

            feedback_frame = await human_feedback_receiver()
            feedback = feedback_frame["content"].strip()
            if feedback:
                durable_notes.append(f"[Human Feedback] {feedback}")
            self._restore_checkpoint(checkpoint)
            active_context = checkpoint.context_messages
            auto_retry_count = 0
            stagnation_count = 0

    def _calculate_loop_score(self, history: list[ExecutionSnapshot]) -> int:
        recent = history[-3:]
        score = 0
        for index in range(1, len(recent)):
            previous = recent[index - 1]
            current = recent[index]
            if _sha256(previous["tool_args_json"]) == _sha256(current["tool_args_json"]):
                score += 1
            if previous["ast_hash"] and previous["ast_hash"] == current["ast_hash"]:
                score += 1
        return score

    async def _plan(
        self,
        user_input: str,
        context_messages: Sequence[Mapping[str, str]],
        durable_notes: Sequence[str],
        repair_note: str | None,
        tool_matrix: Mapping[str, Agent],
    ) -> tuple[Agent, DynamicAgentArgs]:
        response = await self.client.agenerate(
            messages=self._build_messages(user_input, context_messages, durable_notes, repair_note),
            tools=list(_tool_spec(agent) for agent in tool_matrix.values()),
            tool_choice="auto",
            parallel_tool_calls=False,
        )
        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            raise RuntimeError("LLM failed to select a routing tool")

        tool_call = tool_calls[0]
        selected_agent = tool_matrix[tool_call.function.name]
        parsed_args = DynamicAgentArgs.model_validate(json.loads(tool_call.function.arguments))
        if not parsed_args.thought.strip():
            raise RuntimeError("LLM failed to provide a planning thought")
        return selected_agent, parsed_args

    async def _act(
        self,
        agent: Agent,
        parsed_args: DynamicAgentArgs,
        repair_note: str | None,
    ) -> AgentOutput:
        task = parsed_args.task_description
        if repair_note:
            task = (
                f"{task}\n\n"
                "\u4fee\u590d\u7ea6\u675f\uff1a\n"
                f"{repair_note}\n\n"
                "\u8bf7\u907f\u514d\u91cd\u590d\u8be5\u5931\u8d25\u6a21\u5f0f\u3002"
            )
        if _agent_has_tag(agent, ("code", "debug", "implement", "python", "frontend", "backend")):
            return CoderOutput.model_validate_json(
                await _run_adapter_agent(self.client, agent, task, _schema_prompt(CoderOutput))
            )
        if _agent_has_tag(agent, ("search", "docs", "news", "current", "facts")):
            return SearchOutput.model_validate_json(
                await _run_adapter_agent(self.client, agent, task, _schema_prompt(SearchOutput))
            )
        return GenericAgentOutput(
            content=await _run_adapter_agent(self.client, agent, task, "Return concise text.")
        )

    def _build_messages(
        self,
        user_input: str,
        context_messages: Sequence[Mapping[str, str]],
        durable_notes: Sequence[str],
        repair_note: str | None,
    ) -> list[ChatCompletionMessageParam]:
        content = (
            "You are the central Orchestrator for AgentHub. You must NOT answer directly. "
            "Select exactly one registered agent tool. Tool arguments must contain thought "
            "and task_description. If durable failure notes exist, avoid those patterns."
        )
        messages: list[ChatCompletionMessageParam] = [{"role": "system", "content": content}]
        if context_messages:
            messages.append({"role": "system", "content": _format_context(context_messages)})
        if durable_notes:
            messages.append({"role": "system", "content": _format_durable_notes(durable_notes)})
        if repair_note:
            messages.append({"role": "system", "content": f"Current repair lemma: {repair_note}"})
        messages.append({"role": "user", "content": user_input})
        return messages

    async def _verify_artifact(
        self,
        user_input: str,
        agent: Agent,
        output: AgentOutput,
    ) -> ReviewResult:
        if isinstance(output, CoderOutput):
            return await _verify_code(user_input, output, self.sandbox, self.runner, self.session_id)
        if isinstance(output, SearchOutput):
            return _verify_search(output)
        if output.content.strip():
            return _review(True, "Agent artifact produced successfully.")
        return _review(False, _failure_lemma("\u7ed3\u6784", f"{agent.name}EmptyOutput", 0))

    def _create_checkpoint(
        self,
        context_messages: Sequence[Mapping[str, str]],
        loop_count: int,
    ) -> Checkpoint:
        main_code = _read_workspace_main(self.workspace_manager, self.session_id)
        seed = f"{self.session_id}:{loop_count}:{len(context_messages)}:{main_code or ''}"
        return Checkpoint(
            id=f"ckpt_{self.session_id}_{_sha256(seed)[:12]}",
            context_messages=_context_copy(context_messages),
            main_code=main_code,
        )

    def _restore_checkpoint(self, checkpoint: Checkpoint) -> None:
        if checkpoint.main_code is not None:
            self.workspace_manager.write_file(self.session_id, "src/main.py", checkpoint.main_code)
            return
        _remove_workspace_main(self.workspace_manager, self.session_id)


async def _run_adapter_agent(
    client: AsyncLLMClient,
    agent: Agent,
    task: str,
    contract: str,
) -> str:
    adapter = build_agent_adapter(_agent_driver(agent), client)
    prompt = f"{task}\n\nOutput contract:\n{contract}"
    return await adapter.execute_task(prompt, agent.system_prompt)


async def _artifact_steps(
    agent: Agent,
    output: AgentOutput,
    loop_count: int,
    checkpoint_id: str,
) -> AsyncGenerator[MessageStep, None]:
    if isinstance(output, CoderOutput):
        language = output.language.lower()
        yield MessageStep(
            type="code_diff",
            agent=agent.name,
            filename=_artifact_path(language),
            content=escape(output.code),
            artifact_code=output.code,
            loop_count=loop_count,
            checkpoint_id=checkpoint_id,
        )
        yield MessageStep(
            type="text",
            agent=agent.name,
            content=escape(output.explanation),
            loop_count=loop_count,
            checkpoint_id=checkpoint_id,
        )
        return

    if isinstance(output, SearchOutput):
        content = output.summary
        if output.sources:
            content = f"{content}\n\nSources:\n" + "\n".join(output.sources)
        yield MessageStep(
            type="text",
            agent=agent.name,
            content=escape(content),
            loop_count=loop_count,
            checkpoint_id=checkpoint_id,
        )
        return

    yield MessageStep(
        type="text",
        agent=agent.name,
        content=escape(output.content),
        loop_count=loop_count,
        checkpoint_id=checkpoint_id,
    )


def _execution_snapshot(parsed_args: DynamicAgentArgs, output: AgentOutput) -> ExecutionSnapshot:
    raw_text = _raw_output_text(output)
    return {
        "tool_args_json": parsed_args.model_dump_json(exclude_none=True),
        "ast_hash": _ast_hash(raw_text),
        "raw_text": raw_text,
    }


def _build_tools(agents: Sequence[Agent]) -> dict[str, Agent]:
    return {_tool_name(agent): agent for agent in agents}


def _tool_spec(agent: Agent) -> ChatCompletionToolParam:
    return {
        "type": "function",
        "function": {
            "name": _tool_name(agent),
            "description": f"{agent.name}: {agent.tags}",
            "parameters": DynamicAgentArgs.model_json_schema(),
        },
    }


def _tool_name(agent: Agent) -> str:
    return f"agent_{agent.id}"


def _agent_has_tag(agent: Agent, tags: Sequence[str]) -> bool:
    values = {item.strip().lower() for item in agent.tags.split(",") if item.strip()}
    name = agent.name.lower()
    return any(tag in values or tag in name for tag in tags)


def _agent_driver(agent: Agent) -> str:
    values = [item.strip().lower() for item in agent.tags.split(",") if item.strip()]
    for value in values:
        if value.startswith("driver:"):
            return value.split(":", 1)[1]
        if value in {"codex", "claude", "claude-code", "opencode", "open-code"}:
            return value
    return "codex"


def _schema_prompt(output_schema: type[CoderOutput] | type[SearchOutput]) -> str:
    return json.dumps(output_schema.model_json_schema(), ensure_ascii=False)


def _flow_step(agent_name: str, loop_count: int, checkpoint_id: str) -> MessageStep:
    return MessageStep(
        type="flow",
        agent="\u7f16\u6392\u5668",
        loop_count=loop_count,
        checkpoint_id=checkpoint_id,
        stages=[
            {
                "title": "Plan",
                "description": "Context loaded and execution path selected",
                "status": "completed",
            },
            {
                "title": "Action",
                "description": agent_name,
                "status": "active",
            },
            {
                "title": "Review",
                "description": "Sandbox and semantic checks pending",
                "status": "pending",
            },
        ],
    )


def _human_required_step(checkpoint_id: str) -> StepPayload:
    return {
        "type": "run.requires_human",
        "agent": "\u7f16\u6392\u5668",
        "content": (
            "\u68c0\u6d4b\u5230\u667a\u80fd\u4f53\u9677\u5165\u8bed\u4e49\u6b7b\u5faa\u73af\uff0c"
            "\u5df2\u4e3a\u60a8\u9501\u5b9a\u5b89\u5168\u68c0\u67e5\u70b9\uff0c"
            "\u7b49\u5f85\u4eba\u5de5\u53cd\u9988\u4ecb\u5165\u3002"
        ),
        "checkpoint_id": checkpoint_id,
    }


def _format_context(context_messages: Sequence[Mapping[str, str]]) -> str:
    lines = [
        ":".join(
            (
                item.get("role", ""),
                item.get("sender", ""),
                item.get("type", ""),
                item.get("content", ""),
            )
        )
        for item in context_messages
    ]
    return "Recent persisted context:\n" + "\n".join(lines)


def _format_durable_notes(durable_notes: Sequence[str]) -> str:
    return "Durable notes:\n" + "\n".join(durable_notes)


def _context_copy(context_messages: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "role": item.get("role", ""),
            "sender": item.get("sender", ""),
            "type": item.get("type", ""),
            "content": item.get("content", ""),
        }
        for item in context_messages
    ]


async def _verify_code(
    user_input: str,
    output: CoderOutput,
    sandbox: PythonSandbox,
    runner: AsyncCodeRunner,
    session_id: int,
) -> ReviewResult:
    code = output.code.strip()
    language = output.language.strip()
    explanation = output.explanation.strip()
    if not code or not language or not explanation:
        return _review(False, _failure_lemma("\u7ed3\u6784", "MissingArtifactField", 0))

    if language.lower() == "python":
        ok, reason = sandbox.verify_code(code)
        if not ok:
            return _review(False, _compressed_failure("\u8bed\u6cd5", reason))
        ok, reason = await runner.run_code(session_id)
        if not ok:
            return _review(False, _compressed_failure("\u6267\u884c", reason))

    lowered_request = user_input.lower()
    lowered_code = code.lower()
    sort_requested = any(
        token in lowered_request
        for token in ("quick", "sort", "\u5feb\u6392", "\u5feb\u901f\u6392\u5e8f")
    )
    if sort_requested and not any(token in lowered_code for token in ("quick", "sort", "pivot")):
        return _review(False, _failure_lemma("\u8bed\u4e49", "QuicksortPatternMissing", 0))

    return _review(True, "Code compiled and executed successfully.")


def _verify_search(output: SearchOutput) -> ReviewResult:
    if not output.summary.strip():
        return _review(False, _failure_lemma("\u7ed3\u6784", "MissingSearchSummary", 0))
    if not output.sources:
        return _review(False, _failure_lemma("\u7ed3\u6784", "MissingSearchSource", 0))
    return _review(True, "Search artifact includes summary and sources.")


def _review(passed: bool, summary: str) -> ReviewResult:
    return {
        "passed": passed,
        "summary": summary,
        "error_feedback": "" if passed else summary,
    }


def _compressed_failure(phase: str, reason: str) -> str:
    return _failure_lemma(phase, _extract_error_type(reason), _extract_line_no(reason))


def _failure_lemma(phase: str, err_type: str, line_no: int) -> str:
    return f"[Failure Lemma] {phase}\u7531\u4e8e {err_type} \u5728 {line_no} \u884c\u5931\u8d25\u3002\u4e0d\u53ef\u91cd\u590d\u6b64\u9519\u8bef\u6a21\u5f0f\u3002"


def _extract_error_type(reason: str) -> str:
    matches = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b", reason)
    if matches:
        return matches[-1]
    if "Syntax Error" in reason:
        return "SyntaxError"
    return "RuntimeError"


def _extract_line_no(reason: str) -> int:
    matches = re.findall(r"line\s+(\d+)", reason, flags=re.IGNORECASE)
    if matches:
        return int(matches[-1])
    return 0


def _ast_hash(code: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return f"invalid:{_sha256(code)}"
    return _sha256(ast.dump(tree, include_attributes=False))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _raw_output_text(output: AgentOutput) -> str:
    if isinstance(output, CoderOutput):
        return output.code
    if isinstance(output, SearchOutput):
        return output.summary
    return output.content


def _read_workspace_main(
    workspace_manager: WorkspaceManager,
    session_id: int,
) -> str | None:
    workspace = Path(workspace_manager.init_workspace(session_id))
    path = workspace / "src" / "main.py"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _remove_workspace_main(
    workspace_manager: WorkspaceManager,
    session_id: int,
) -> None:
    workspace = Path(workspace_manager.init_workspace(session_id))
    path = (workspace / "src" / "main.py").resolve()
    if workspace == path or workspace in path.parents:
        path.unlink(missing_ok=True)


def _extension(language: str) -> str:
    return {
        "python": "py",
        "html": "html",
        "javascript": "js",
        "typescript": "ts",
        "java": "java",
        "go": "go",
        "rust": "rs",
    }.get(language, "txt")


def _artifact_path(language: str) -> str:
    extension = _extension(language.strip().lower())
    if extension == "py":
        return "src/main.py"
    if extension == "html":
        return "src/index.html"
    return f"src/main.{extension}"


def _dump_step(step: MessageStep) -> StepPayload:
    return {str(key): value for key, value in step.model_dump(exclude_none=True).items()}


async def _main() -> None:
    from app.db.database import async_session_factory, init_db

    await init_db()
    async with async_session_factory() as session:
        orchestrator = DynamicOrchestrator(
            AsyncLLMClient(),
            session_id=0,
            agent_repository=AgentRepository(session),
        )
        async for step in orchestrator.route_intent_stream("\u5e2e\u6211\u5199\u4e2a\u5feb\u6392"):
            print(json.dumps(step, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_main())
