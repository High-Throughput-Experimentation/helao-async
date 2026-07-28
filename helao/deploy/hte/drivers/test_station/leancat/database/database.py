"""PostgreSQL connection helpers used by the LEANCAT driver.

Provides a :class:`Db` wrapper around ``psycopg2`` with autocommit and
``tenacity``-driven retries plus a :func:`reconnect` decorator that
reopens the connection when a query raises.
"""

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
    """Decorator that reconnects a :class:`Db` instance before calling ``f``.

    On :class:`psycopg2.Error` the connection is closed and the exception
    is re-raised so the caller's retry policy can take over.

    Args:
        f: Method whose first argument is a :class:`Db` instance.

    Returns:
        Wrapped method enforcing the reconnect-on-error policy.
    """

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
    """Thin ``psycopg2`` wrapper with autocommit and retry-friendly helpers.

    Holds the connection parameters dict and lazily opens an autocommit
    connection. Provides :meth:`query`, :meth:`listen_channels` and
    :meth:`check_notifications` for LEANCAT's notification-driven flow.
    """

    def __init__(self, params):
        """Store connection parameters; defer opening the connection.

        Args:
            params: Mapping passed straight to ``psycopg2.connect``.
        """
        self._connection_params = params
        self._connection = None

    def connected(self) -> bool:
        """Return ``True`` if a live (unclosed) connection is held."""
        return self._connection and self._connection.closed == 0

    def connect(self):
        """Close any existing connection and open a fresh autocommit one."""
        self.close()
        self._connection = connect(**self._connection_params)
        self._connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

    def close(self):
        """Close the underlying connection if open, swallowing errors."""
        if self.connected():
            # noinspection PyBroadException
            try:
                self._connection.close()
            except Exception:
                pass

        self._connection = None

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    @reconnect
    def query(self, sql, *args):
        """Execute ``sql`` with optional positional ``args`` and return rows.

        :class:`OperationalError` is re-raised to trigger ``tenacity`` retry;
        :class:`ProgrammingError` and other exceptions are returned as
        ``"Error: ..."`` strings so the retry loop is not disturbed.

        Args:
            sql: SQL string or ``psycopg2.sql.Composable``.
            *args: Positional parameters bound to the SQL.

        Returns:
            ``cur.fetchall()`` results, the original exception object when
            "No results to fetch" applies, or an ``"Error: ..."`` string.
        """
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

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    @reconnect
    def check_notifications(self):
        """Drain pending PostgreSQL ``NOTIFY`` messages.

        Returns:
            A list of ``{"channel": str, "payload": str}`` dicts, one per
            queued notification.
        """
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
        """Issue a ``LISTEN`` query for each channel name in ``channels``.

        Args:
            channels: Iterable of channel identifiers to subscribe to.
        """
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
