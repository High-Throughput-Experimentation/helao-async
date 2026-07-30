"""LEANCAT command primitives backed by PostgreSQL functions.

Provides the shared ``commands_queue`` plus thin wrappers around the
PostgreSQL stored procedures used to start/terminate LEANCAT sessions and
to record timestamp annotations.
"""

import queue

from psycopg2 import sql

from ..database import query
from ..logger import script_log


class LeancatSession:
    """Placeholder session object reserved for future LEANCAT state."""

    def __init__(self) -> None:
        """No-op initialiser."""
        pass


commands_queue = queue.Queue()


def create_session(arg_script_job_id, description="") -> int:
    """Create a new LEANCAT logging session via the SQL ``create_session``.

    Args:
        arg_script_job_id: Identifier of the script job that owns the session.
        description: Free-text description stored with the session.

    Returns:
        The new session id returned by the SQL function.

    Raises:
        Exception: If the SQL call returns an error string.
    """
    str_sql = sql.SQL("SELECT create_session({script_job_id}, {description})").format(
        script_job_id=sql.Literal(arg_script_job_id),
        description=sql.Literal(description),
    )
    res = query(str_sql)
    if isinstance(res, str) and "Error" in res:
        raise Exception(
            f'Error creating session with script job id {arg_script_job_id}, description: "{description}", error message: {res}'
        )
    resp_session_id = res[0][0]
    script_log.debug(f"Created new session with id: {resp_session_id}")
    return resp_session_id


def terminate_session(session_id) -> int:
    """Terminate an existing LEANCAT session via SQL ``terminate_session``.

    Args:
        session_id: Identifier of the session to terminate.

    Returns:
        The session id returned by the SQL function.

    Raises:
        Exception: If the SQL call returns an error string.
    """
    str_sql = sql.SQL("SELECT terminate_session({session_id})").format(
        session_id=sql.Literal(session_id)
    )
    res = query(str_sql)
    if isinstance(res, str) and "Error" in res:
        raise Exception(
            f"Error terminating session with session id {session_id}, error message: {res}"
        )
    resp_session_id = res[0][0]
    script_log.debug(f"Terminated session with id: {resp_session_id}")
    return resp_session_id


def create_timestamp_annotation(description="") -> int:
    """Insert a row into ``timestampAnnotations`` with ``NOW()`` as the time.

    Args:
        description: Free-text annotation description.

    Returns:
        The id of the newly inserted annotation row.

    Raises:
        Exception: If the SQL call returns an error string.
    """
    str_sql = sql.SQL(
        'INSERT INTO "timestampAnnotations"(description, "time") VALUES ({description},NOW()) RETURNING id;'
    ).format(
        description=sql.Literal(description),
    )
    res = query(str_sql)
    if isinstance(res, str) and "Error" in res:
        raise Exception(f"Error creating timestamp annotation, error message: {res}")
    resp_session_id = res[0][0]
    script_log.debug(f"Created new timestamp annotation with id: {resp_session_id}")
    return resp_session_id
