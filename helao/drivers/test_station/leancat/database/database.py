import json
from psycopg2 import connect, sql
from psycopg2 import OperationalError, ProgrammingError, Error
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from tenacity import retry, wait_exponential, stop_after_attempt
from typing import Callable
from ..logger import main_log


# arg_app_config_path = sys.argv[1]

# with open(arg_app_config_path, "r") as f:
#     app_config = json.loads(f.read())
#     db_config = app_config["app"]["db"]
#     # Delete property reconnectionInterval that is not recognized by psycopg2
#     del db_config["reconnectionInterval"]


def reconnect(f: Callable):
    def wrapper(db, *args, **kwargs):
        if not db.connected():
            main_log.error("Database not connected")
            db.connect()

        try:
            return f(db, *args, **kwargs)
        except Error:
            main_log.error("Connection error")
            db.close()
            raise

    return wrapper


class Db:
    def __init__(self, params):
        self._connection_params = params
        self._connection = None

    def connected(self) -> bool:
        return self._connection and self._connection.closed == 0

    def connect(self):
        self.close()
        self._connection = connect(**self._connection_params)
        self._connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

    def close(self):
        if self.connected():
            # noinspection PyBroadException
            try:
                self._connection.close()
            except Exception:
                pass

        self._connection = None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    @reconnect
    def query(self, sql, *args):
        try:
            # Do not use main_log! This would lead to a cycle, because logged messages are written to the log file where the read_lines() function
            # picks them up and feeds them to the db -> this leads to another query and the cycle start over.
            # print(f'Executing query: "{sql}"') # Use this line for debugging only! Execution of this line when python process is launched from Node.js causes OSError: [Errno 22] Invalid argument
            cur = self._connection.cursor()
            cur.execute(sql, args)
            return cur.fetchall()
        except OperationalError as e:
            raise
        # The errors below does not raise exceptions, otherwise retry function won't work
        except ProgrammingError as e:
            if e == "No results to fetch":
                return e
            else:
                return "Error: " + str(e)
        except Exception as e:
            return "Error: " + str(e)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    @reconnect
    def check_notifications(self):
        msgArray = []
        self._connection.poll()
        while self._connection.notifies:
            notify = self._connection.notifies.pop(0)
            main_log.debug(
                f'Received notification, PID: {str(notify.pid)}, channel: "{notify.channel}", payload: {notify.payload}'
            )
            msgArray.append({"channel": notify.channel, "payload": notify.payload})
        return msgArray

    def listen_channels(self, channels):
        for item in channels:
            self.query(sql.SQL("LISTEN {channel}").format(channel=sql.Identifier(item)))
            main_log.debug(f'Channel listener started: "{item}"')


# db = Db(db_config)
# try:
#     db.connect()
#     query = db.query
#     listen_channels = db.listen_channels
#     check_notifications = db.check_notifications
#     # Test db connection
#     query("SELECT NOW()")
#     main_log.info("Database connected")
#     listen_channels(["scripts-jobs-commands:new-row"])
# except Exception as e:
#     main_log.error(e)
