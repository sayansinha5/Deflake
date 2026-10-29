from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.llm.factory import Llm


@dataclass
class GraphContext:
    settings: Settings
    sessionmaker: async_sessionmaker
    llm: Llm
    search: object
    runner: object | None = None


current_context: ContextVar[GraphContext] = ContextVar("deflake_graph_context")
