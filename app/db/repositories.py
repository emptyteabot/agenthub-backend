from collections.abc import Mapping

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Agent, Artifact, Message, Session


class MessageRepository:
    def __init__(self, db: SQLAlchemyAsyncSession) -> None:
        self.db = db

    async def create_session(self, title: str) -> Session:
        session = Session(title=title)
        self.db.add(session)
        await self.db.flush()
        return session

    async def get_session(self, session_id: int) -> Session | None:
        return await self.db.get(Session, session_id)

    async def get_all_sessions(self) -> list[Session]:
        result = await self.db.execute(
            select(Session).order_by(desc(Session.last_active_at), desc(Session.id))
        )
        return list(result.scalars().all())

    async def get_or_create_session(self, session_id: int | None, title: str) -> Session:
        if session_id is not None:
            existing = await self.get_session(session_id)
            if existing is not None:
                return existing
        return await self.create_session(title)

    async def touch_session(self, session: Session) -> None:
        session.last_active_at = func.now()
        await self.db.flush()

    async def add_message(
        self,
        session_id: int,
        sender: str,
        role: str,
        content: str,
        type_: str = "text",
    ) -> Message:
        message = Message(
            session_id=session_id,
            sender=sender,
            role=role,
            content=content,
            type=type_,
        )
        self.db.add(message)
        await self.db.flush()
        return message

    async def get_recent_messages(self, session_id: int, limit: int) -> list[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(desc(Message.created_at), desc(Message.id))
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def get_messages(self, session_id: int) -> list[Message]:
        result = await self.db.execute(
            select(Message)
            .options(selectinload(Message.artifacts))
            .where(Message.session_id == session_id)
            .order_by(Message.created_at, Message.id)
        )
        return list(result.scalars().all())

    async def next_artifact_version(self, session_id: int) -> int:
        result = await self.db.execute(
            select(func.max(Artifact.version))
            .join(Message)
            .where(Message.session_id == session_id)
        )
        current = result.scalar_one_or_none()
        return int(current or 0) + 1

    async def add_artifact(
        self,
        message_id: int,
        version: int,
        code_content: str,
        diff_info: str | None = None,
    ) -> Artifact:
        artifact = Artifact(
            message_id=message_id,
            version=version,
            code_content=code_content,
            diff_info=diff_info,
        )
        self.db.add(artifact)
        await self.db.flush()
        return artifact


class AgentRepository:
    def __init__(self, db: SQLAlchemyAsyncSession) -> None:
        self.db = db

    async def get_all_agents(self) -> list[Agent]:
        await self.ensure_default_agents()
        result = await self.db.execute(select(Agent).order_by(Agent.id))
        return list(result.scalars().all())

    async def get_agent_by_name(self, name: str) -> Agent | None:
        await self.ensure_default_agents()
        result = await self.db.execute(select(Agent).where(Agent.name == name))
        return result.scalar_one_or_none()

    async def get_agent_by_id(self, agent_id: int) -> Agent | None:
        await self.ensure_default_agents()
        return await self.db.get(Agent, agent_id)

    async def create_custom_agent(self, agent_data: Mapping[str, object]) -> Agent:
        agent = Agent(
            name=str(agent_data["name"]),
            avatar=str(agent_data.get("avatar", "bot")),
            system_prompt=str(agent_data["system_prompt"]),
            tags=str(agent_data.get("tags", "")),
            is_custom=bool(agent_data.get("is_custom", True)),
        )
        self.db.add(agent)
        await self.db.flush()
        return agent

    async def ensure_default_agents(self) -> None:
        result = await self.db.execute(select(func.count(Agent.id)))
        if int(result.scalar_one()) > 0:
            return
        self.db.add_all(
            [
                Agent(
                    name="\u7f16\u6392\u5668",
                    avatar="route",
                    system_prompt=(
                        "You are the central Orchestrator for AgentHub. Plan, route, "
                        "and coordinate specialized agents without answering directly."
                    ),
                    tags="route,plan,orchestrate",
                    is_custom=False,
                ),
                Agent(
                    name="\u4ee3\u7801\u4e13\u5bb6",
                    avatar="code",
                    system_prompt=(
                        "You are a senior full-stack engineer. Produce structured code "
                        "artifacts that satisfy the requested implementation task."
                    ),
                    tags="code,debug,implement,python,frontend,backend",
                    is_custom=False,
                ),
                Agent(
                    name="\u641c\u7d22\u8005",
                    avatar="search",
                    system_prompt=(
                        "You are a search specialist. Return concise findings with reliable "
                        "source links when lookup or current facts are required."
                    ),
                    tags="search,docs,news,current,facts",
                    is_custom=False,
                ),
            ]
        )
        await self.db.flush()
