"""PostgreSQL access with explicit, short-lived transaction boundaries."""

from contextlib import contextmanager
from typing import Iterator

import psycopg

from clavel.core.settings import Settings


class Database:
    """Own configuration, not an open connection; safe to construct at startup."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.database_url

    @contextmanager
    def session(self) -> Iterator[psycopg.Connection]:
        """One connection/transaction: commit on success, rollback on error.

        Always close on exit, including when commit fails. Callers must let
        failures escape the block to roll back the unit of work. Never share
        a session between requests or commit midway through a unit of work.
        """
        connection = psycopg.connect(
            self._url.get_secret_value(),
            connect_timeout=3,
            options="-c statement_timeout=3000",
            autocommit=False,
        )
        try:
            with connection:
                yield connection
        finally:
            # psycopg's context manager can leave a connection open if COMMIT
            # itself fails (for example, a deferred constraint violation).
            connection.close()

    def is_ready(self) -> bool:
        """Probe PostgreSQL now; failures convey no private driver details."""
        try:
            with self.session() as connection:
                return connection.execute("SELECT 1").fetchone() == (1,)
        except psycopg.Error:
            return False
