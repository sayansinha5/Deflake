from contextlib import asynccontextmanager

from app.config import Settings


def _repair_aiomysql_blob_escape() -> None:
    """PyMySQL 1.2 replaced escape_bytes_prefixed with a string sentinel.

    aiomysql 0.3.2 still calls it when a checkpoint blob (bytes) is written.
    Point the name at pymysql.converters.escape_bytes, which emits a MySQL hex literal.
    """
    import aiomysql.connection as connection
    from pymysql.converters import escape_bytes

    if not callable(connection.escape_bytes_prefixed):
        connection.escape_bytes_prefixed = escape_bytes


@asynccontextmanager
async def mysql_checkpointer(settings: Settings):
    """LangGraph MySQL saver. Tables are created by the migration, not at runtime.

    langgraph-checkpoint-mysql 3.0.0 hardcodes table names, so CHECKPOINT_TABLE_PREFIX
    is kept in config and not applied.
    """
    _repair_aiomysql_blob_escape()
    from langgraph.checkpoint.mysql.aio import AIOMySQLSaver

    url = settings.database_url.replace("mysql+aiomysql://", "mysql://", 1)
    async with AIOMySQLSaver.from_conn_string(url) as saver:
        yield saver
