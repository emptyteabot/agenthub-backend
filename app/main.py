import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.core.llm_client import AsyncLLMClient
from app.core.orchestrator import DynamicOrchestrator, HumanFeedbackFrame, StepPayload
from app.core.runner import AsyncCodeRunner
from app.core.workspace import FileTreeNode, WorkspaceManager
from app.db.database import async_session_factory, init_db
from app.db.models import Agent, Message, Session
from app.db.repositories import AgentRepository, MessageRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
WORKSPACE_ROOT = PROJECT_ROOT / "workspaces"
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
FRONTEND_ROOT.mkdir(parents=True, exist_ok=True)
workspace_manager = WorkspaceManager()
code_runner = AsyncCodeRunner(workspace_manager)
SessionState = Literal["IDLE", "PROCESSING", "WAITING_HUMAN"]
SESSION_STATES: dict[int, SessionState] = {}


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    avatar: str = Field(default="bot", max_length=200)
    system_prompt: str = Field(min_length=1)
    tags: str = Field(default="", max_length=300)


class AgentRead(BaseModel):
    id: int
    name: str
    avatar: str
    system_prompt: str
    tags: str
    is_custom: bool


class SessionRead(BaseModel):
    id: int
    title: str
    created_at: str
    last_active_at: str


class MessageRead(BaseModel):
    id: int
    session_id: int
    type: str
    agent: str
    sender: str
    role: str
    content: str
    filename: str | None = None
    artifact_code: str | None = None
    created_at: str


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    FRONTEND_ROOT.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield


app = FastAPI(title="AgentHub API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/workspaces", StaticFiles(directory=str(WORKSPACE_ROOT)), name="workspaces")
app.mount("/frontend", StaticFiles(directory=str(FRONTEND_ROOT)), name="frontend")


@app.get("/")
async def index() -> RedirectResponse:
    return RedirectResponse(url="/frontend/code.html")


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {"status": "ok", "mock_mode": _mock_mode_enabled()}


@app.get("/api/agents")
async def list_agents() -> list[AgentRead]:
    async with async_session_factory() as db:
        agents = await AgentRepository(db).get_all_agents()
        return [_agent_read(agent) for agent in agents]


@app.post("/api/agents")
async def create_agent(agent_data: AgentCreate) -> AgentRead:
    async with async_session_factory() as db:
        repo = AgentRepository(db)
        agent = await repo.create_custom_agent(agent_data.model_dump())
        await db.commit()
        return _agent_read(agent)


@app.get("/api/sessions")
async def list_sessions() -> list[SessionRead]:
    async with async_session_factory() as db:
        sessions = await MessageRepository(db).get_all_sessions()
        return [_session_read(session) for session in sessions]


@app.get("/api/messages/{session_id}")
async def list_messages(session_id: int) -> list[MessageRead]:
    async with async_session_factory() as db:
        messages = await MessageRepository(db).get_messages(session_id)
        return [_message_read(message) for message in messages]


@app.get("/api/workspace/{session_id}/files")
async def list_workspace_files(session_id: int) -> list[FileTreeNode]:
    return workspace_manager.list_files_tree(session_id)


@app.get("/api/workspace/{session_id}/file")
async def read_workspace_file(session_id: int, path: str = Query(...)) -> dict[str, str]:
    return {"path": path, "content": workspace_manager.read_file(session_id, path)}


@app.websocket("/api/ws/chat")
async def chat_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    feedback_queues: dict[int, asyncio.Queue[HumanFeedbackFrame]] = {}
    active_tasks: dict[int, asyncio.Task[None]] = {}
    send_lock = asyncio.Lock()
    try:
        while True:
            data = _payload(await websocket.receive_json())
            action = str(data.get("action", ""))
            event_type = str(data.get("type", "message"))
            user_input = str(data.get("content") or data.get("message") or "")
            session_id = _session_id(data.get("session_id"))
            async with async_session_factory() as db:
                message_repo = MessageRepository(db)
                session = await message_repo.get_or_create_session(
                    session_id,
                    _session_title(user_input),
                )
                workspace_manager.init_workspace(session.id)
                SESSION_STATES.setdefault(session.id, "IDLE")
                feedback_queues.setdefault(session.id, asyncio.Queue())
                await db.commit()
            await _send_json(websocket, send_lock, {"type": "session", "session_id": session.id})

            if action == "run":
                await _run_workspace(websocket, send_lock, session.id)
                await _touch_session(session.id)
                await _send_json(websocket, send_lock, {"type": "done", "session_id": session.id})
                continue

            if event_type not in {"message", "human_feedback"}:
                continue

            state = SESSION_STATES[session.id]
            if state == "WAITING_HUMAN":
                await feedback_queues[session.id].put(
                    {
                        "type": "human_feedback",
                        "content": user_input,
                    }
                )
                SESSION_STATES[session.id] = "PROCESSING"
                continue

            if state != "IDLE":
                await _send_json(
                    websocket,
                    send_lock,
                    {
                        "type": "system.busy",
                        "agent": "System",
                        "content": "Current session is processing.",
                        "session_id": session.id,
                    },
                )
                continue

            SESSION_STATES[session.id] = "PROCESSING"
            task = asyncio.create_task(
                _run_orchestrator_stream(
                    websocket,
                    send_lock,
                    session.id,
                    user_input,
                    feedback_queues[session.id],
                )
            )
            active_tasks[session.id] = task
    except WebSocketDisconnect:
        for task in active_tasks.values():
            task.cancel()


async def _run_workspace(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session_id: int,
) -> None:
    async with async_session_factory() as db:
        repo = MessageRepository(db)
        start_step: StepPayload = {
            "type": "run",
            "agent": "Runner",
            "content": "python src/main.py",
            "session_id": session_id,
        }
        await _send_json(websocket, send_lock, start_step)
        await _persist_step(repo, session_id, start_step)
        ok, output = await code_runner.run_code(session_id)
        step: StepPayload = {
            "type": "stdout" if ok else "stderr",
            "agent": "Runner",
            "content": output,
            "passed": ok,
            "session_id": session_id,
        }
        await _send_json(websocket, send_lock, step)
        await _persist_step(repo, session_id, step)
        await db.commit()


async def _run_orchestrator_stream(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session_id: int,
    user_input: str,
    feedback_queue: asyncio.Queue[HumanFeedbackFrame],
) -> None:
    async with async_session_factory() as db:
        message_repo = MessageRepository(db)
        agent_repo = AgentRepository(db)
        history = await message_repo.get_recent_messages(session_id, 12)
        await message_repo.add_message(
            session_id=session_id,
            sender="User",
            role="user",
            content=user_input,
            type_="text",
        )
        await db.commit()
        context = _context_payload(history)
        orchestrator = DynamicOrchestrator(
            AsyncLLMClient(mock_mode=_mock_mode_enabled()),
            session_id=session_id,
            agent_repository=agent_repo,
            workspace_manager=workspace_manager,
        )
        async for step in orchestrator.route_intent_stream(
            user_input,
            context,
            human_feedback_receiver=feedback_queue.get,
        ):
            step["session_id"] = session_id
            if step.get("type") == "run.requires_human":
                SESSION_STATES[session_id] = "WAITING_HUMAN"
            await _send_json(websocket, send_lock, step)
            await _persist_step(message_repo, session_id, step)
            await db.commit()
        SESSION_STATES[session_id] = "IDLE"
        session = await message_repo.get_session(session_id)
        if session is not None:
            await message_repo.touch_session(session)
        await db.commit()
        await _send_json(websocket, send_lock, {"type": "done", "session_id": session_id})


def _payload(raw_payload: object) -> dict[str, object]:
    if not isinstance(raw_payload, dict):
        raise ValueError("WebSocket payload must be a JSON object")
    return {str(key): value for key, value in raw_payload.items()}


def _session_id(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


async def _send_json(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    payload: StepPayload,
) -> None:
    async with send_lock:
        await websocket.send_json(payload)


async def _touch_session(session_id: int) -> None:
    async with async_session_factory() as db:
        repo = MessageRepository(db)
        session = await repo.get_session(session_id)
        if session is not None:
            await repo.touch_session(session)
        await db.commit()


def _mock_mode_enabled() -> bool:
    value = os.getenv("MOCK_MODE") or dotenv_values(ENV_FILE).get("MOCK_MODE", "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _session_title(message: str) -> str:
    value = message.strip().replace("\n", " ")
    return value[:60] or "New Session"


def _context_payload(history: list[Message]) -> list[dict[str, str]]:
    return [
        {
            "role": item.role,
            "sender": item.sender,
            "type": item.type,
            "content": item.content,
        }
        for item in history
    ]


async def _persist_step(
    repo: MessageRepository,
    session_id: int,
    step: StepPayload,
) -> None:
    type_ = str(step.get("type", "text"))
    if type_ == "session":
        return

    sender = str(step.get("agent") or step.get("sender") or "Agent")
    message = await repo.add_message(
        session_id=session_id,
        sender=sender,
        role=_role_for_sender(sender),
        content=_step_content(step),
        type_=type_,
    )
    if type_ == "code_diff":
        version = await repo.next_artifact_version(session_id)
        await repo.add_artifact(
            message_id=message.id,
            version=version,
            code_content=str(step.get("artifact_code") or step.get("content", "")),
            diff_info=json.dumps(
                {"filename": step.get("filename"), "agent": sender},
                ensure_ascii=False,
            ),
        )


def _agent_read(agent: Agent) -> AgentRead:
    return AgentRead(
        id=agent.id,
        name=agent.name,
        avatar=agent.avatar,
        system_prompt=agent.system_prompt,
        tags=agent.tags,
        is_custom=agent.is_custom,
    )


def _session_read(session: Session) -> SessionRead:
    return SessionRead(
        id=session.id,
        title=session.title,
        created_at=session.created_at.isoformat(),
        last_active_at=session.last_active_at.isoformat(),
    )


def _message_read(message: Message) -> MessageRead:
    filename: str | None = None
    artifact_code: str | None = None
    if message.artifacts:
        artifact = message.artifacts[-1]
        artifact_code = artifact.code_content
        diff_info = json.loads(artifact.diff_info or "{}")
        raw_filename = diff_info.get("filename")
        if isinstance(raw_filename, str):
            filename = raw_filename
    return MessageRead(
        id=message.id,
        session_id=message.session_id,
        type=message.type,
        agent=message.sender,
        sender=message.sender,
        role=message.role,
        content=message.content,
        filename=filename,
        artifact_code=artifact_code,
        created_at=message.created_at.isoformat(),
    )


def _role_for_sender(sender: str) -> str:
    return "system" if sender == "System" else "assistant"


def _step_content(step: StepPayload) -> str:
    if step.get("type") == "flow":
        return json.dumps(step.get("stages", []), ensure_ascii=False)
    if step.get("type") == "review":
        return json.dumps(
            {
                "summary": step.get("content", ""),
                "passed": step.get("passed"),
                "loop_count": step.get("loop_count"),
                "error_feedback": step.get("error_feedback"),
            },
            ensure_ascii=False,
        )
    return str(step.get("content", ""))
