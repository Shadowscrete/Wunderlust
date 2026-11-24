"""Database cache that creates its own table if it's missing.

On Vercel the cache lives in the database (see settings.CACHES). The table is normally created by the
accounts/0008 migration, but if a deployment runs before that migration has been applied, every cache
call would fail with "relation does not exist" and signed-in pages would return a 500. This backend
creates the table on the first such error and retries once, so the site heals itself.
"""
import logging
import threading

from django.core.cache.backends.db import DatabaseCache
from django.core.management import call_command
from django.db import OperationalError, ProgrammingError, connections, router

logger = logging.getLogger(__name__)
_create_lock = threading.Lock()


class SelfHealingDatabaseCache(DatabaseCache):
    def _ensure_table(self):
        with _create_lock:
            db = router.db_for_write(self.cache_model_class)
            connection = connections[db]
            if self._table in connection.introspection.table_names():
                return
            logger.warning('Cache table %s was missing; creating it.', self._table)
            call_command('createcachetable', self._table, database=db, verbosity=0)

    def _retry(self, method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        # PostgreSQL reports a missing table as ProgrammingError, SQLite as OperationalError.
        except (ProgrammingError, OperationalError) as exc:
            if self._table not in str(exc):
                raise
            self._ensure_table()
            return method(*args, **kwargs)

    def get_many(self, keys, version=None):
        return self._retry(super().get_many, keys, version=version)

    def _base_set(self, mode, key, value, timeout=None):
        return self._retry(super()._base_set, mode, key, value, timeout)

    def _base_delete_many(self, keys):
        return self._retry(super()._base_delete_many, keys)

    def has_key(self, key, version=None):
        return self._retry(super().has_key, key, version=version)

    def clear(self):
        return self._retry(super().clear)
