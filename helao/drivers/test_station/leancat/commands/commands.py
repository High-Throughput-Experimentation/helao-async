import queue
from psycopg2 import sql
from ..database import query
from ..logger import script_log


class LeancatSession:
    
    def __init__(self) -> None:
        pass

commands_queue = queue.Queue()


def create_session(arg_script_job_id, description="") -> int:
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


def terminate_session(session_id):
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

