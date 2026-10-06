"""Tests for app/core/db_retry.py.

Verifies the exponential-backoff retry decorator for transient DB failures.
"""
from __future__ import annotations

import unittest
from functools import partial
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from app.core.db_retry import DEFAULT_BACKOFF_BASE, DEFAULT_MAX_RETRIES, with_db_retry
from app.core.exceptions import DatabaseConnectionError


def _op_error(message: str = "server gone") -> OperationalError:
    """Build a real OperationalError instance."""
    return OperationalError("SELECT 1", {}, Exception(message))


def _dbapi_error(message: str = "connection refused") -> DBAPIError:
    # DBAPIError requires (statement, params, orig)
    return DBAPIError("SELECT 1", {}, Exception(message))


def _retry(*, max_retries=3, backoff_base=0.001):
    """Helper: returns a configured decorator instance.

    Usage: @_retry(max_retries=3)
           def func(): ...
    """
    return with_db_retry(max_retries=max_retries, backoff_base=backoff_base)


# ---------------------------------------------------------------------------
# Happy path / pass-through
# ---------------------------------------------------------------------------

class TestRetryNoFailure(unittest.TestCase):
    def test_passes_through_when_no_exception(self):
        @with_db_retry
        def func():
            return "ok"

        self.assertEqual(func(), "ok")

    def test_returns_value_unchanged(self):
        @with_db_retry
        def func(x, y):
            return x + y

        self.assertEqual(func(2, 3), 5)

    def test_propagates_kwargs(self):
        captured = {}

        @with_db_retry
        def func(user_id, project_id):
            captured["user_id"] = user_id
            captured["project_id"] = project_id
            return "done"

        func(user_id=1, project_id=42)
        self.assertEqual(captured, {"user_id": 1, "project_id": 42})


# ---------------------------------------------------------------------------
# Non-transient errors are NOT retried
# ---------------------------------------------------------------------------

class TestNonTransientErrors(unittest.TestCase):
    def test_value_error_propagates_immediately(self):
        """A generic exception (ValueError, etc.) is NOT caught by the decorator."""
        retry = partial(with_db_retry, max_retries=3, backoff_base=0.001)

        @retry
        def func():
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            func()

    def test_integrity_error_is_currently_retried_known_limitation(self):
        """KNOWN LIMITATION: IntegrityError IS retried because it inherits
        from DBAPIError in SQLAlchemy 2.x. Future PR should exclude it
        explicitly with `except (OperationalError, DBAPIError) but not IntegrityError`.
        """
        attempts = [0]
        retry = partial(with_db_retry, max_retries=3, backoff_base=0.001)

        @retry
        def func():
            attempts[0] += 1
            raise IntegrityError("INSERT", {}, Exception("dup key"))

        with patch("app.core.db_retry.time.sleep"):
            # Currently retries 3 times, then wraps as DatabaseConnectionError
            with self.assertRaises(DatabaseConnectionError):
                func()

        self.assertEqual(attempts[0], 3)


# ---------------------------------------------------------------------------
# Retry on transient errors
# ---------------------------------------------------------------------------

class TestRetryBehavior(unittest.TestCase):
    def test_succeeds_after_one_failure(self):
        """First call fails (OperationalError), second call succeeds."""
        attempts = [0]
        retry = partial(with_db_retry, max_retries=3, backoff_base=0.001)

        @retry
        def func():
            attempts[0] += 1
            if attempts[0] < 2:
                raise _op_error("transient")
            return "ok"

        with patch("app.core.db_retry.time.sleep"):
            self.assertEqual(func(), "ok")
        self.assertEqual(attempts[0], 2)

    def test_succeeds_after_two_failures(self):
        """Two failures, third succeeds."""
        attempts = [0]
        retry = partial(with_db_retry, max_retries=3, backoff_base=0.001)

        @retry
        def func():
            attempts[0] += 1
            if attempts[0] < 3:
                raise _op_error("transient")
            return "ok"

        with patch("app.core.db_retry.time.sleep"):
            self.assertEqual(func(), "ok")
        self.assertEqual(attempts[0], 3)

    def test_exhausts_retries_and_raises_database_connection_error(self):
        """All attempts fail → wrapped as DatabaseConnectionError after max_retries."""
        retry = partial(with_db_retry, max_retries=3, backoff_base=0.001)

        @retry
        def func():
            raise _op_error("server gone")

        with patch("app.core.db_retry.time.sleep"):
            with self.assertRaises(DatabaseConnectionError) as ctx:
                func()

        self.assertIn("DB operation failed after 3 attempts", str(ctx.exception))
        self.assertIn("server gone", str(ctx.exception))
        # Original exception is preserved as __cause__
        self.assertIsInstance(ctx.exception.__cause__, OperationalError)

    def test_also_retries_on_dbapi_error(self):
        """DBAPIError (e.g. connection refused) is also retried."""
        attempts = [0]
        retry = partial(with_db_retry, max_retries=2, backoff_base=0.001)

        @retry
        def func():
            attempts[0] += 1
            if attempts[0] < 2:
                raise _dbapi_error()
            return "ok"

        with patch("app.core.db_retry.time.sleep"):
            self.assertEqual(func(), "ok")
        self.assertEqual(attempts[0], 2)

    def test_attempts_count_equals_max_retries_when_all_fail(self):
        attempts = [0]
        retry = partial(with_db_retry, max_retries=4, backoff_base=0.001)

        @retry
        def func():
            attempts[0] += 1
            raise _op_error()

        with patch("app.core.db_retry.time.sleep"):
            with self.assertRaises(DatabaseConnectionError):
                func()

        self.assertEqual(attempts[0], 4)

    def test_does_not_sleep_after_final_failure(self):
        """The final (exhausted) attempt must NOT sleep — only intermediate ones do."""
        retry = partial(with_db_retry, max_retries=3, backoff_base=0.001)

        @retry
        def func():
            raise _op_error()

        with patch("app.core.db_retry.time.sleep") as mock_sleep:
            with self.assertRaises(DatabaseConnectionError):
                func()

        # 3 attempts -> 2 sleeps between them (attempt 1 -> 2, attempt 2 -> 3)
        self.assertEqual(mock_sleep.call_count, 2)


# ---------------------------------------------------------------------------
# Backoff timing
# ---------------------------------------------------------------------------

class TestBackoffTiming(unittest.TestCase):
    def test_exponential_backoff_values(self):
        """waits are 0.2, 0.4 for 3 attempts (no sleep after final)."""
        attempts = [0]
        retry = partial(with_db_retry, max_retries=3, backoff_base=0.2)

        @retry
        def func():
            attempts[0] += 1
            if attempts[0] < 3:
                raise _op_error()
            return "ok"

        with patch("app.core.db_retry.time.sleep") as mock_sleep:
            func()

        # 2 sleeps with values 0.2 and 0.4 (exponential: 0.2 * 2^0 = 0.2, 0.2 * 2^1 = 0.4)
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertEqual(mock_sleep.call_args_list[0].args[0], 0.2)
        self.assertEqual(mock_sleep.call_args_list[1].args[0], 0.4)

    def test_custom_backoff_base(self):
        attempts = [0]
        retry = partial(with_db_retry, max_retries=2, backoff_base=0.5)

        @retry
        def func():
            attempts[0] += 1
            if attempts[0] < 2:
                raise _op_error()
            return "ok"

        with patch("app.core.db_retry.time.sleep") as mock_sleep:
            func()

        self.assertEqual(mock_sleep.call_args_list[0].args[0], 0.5)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TestLogging(unittest.TestCase):
    def test_warns_on_each_retry(self):
        attempts = [0]
        retry = partial(with_db_retry, max_retries=3, backoff_base=0.001)

        @retry
        def func():
            attempts[0] += 1
            if attempts[0] < 3:
                raise _op_error("boom")
            return "ok"

        with patch("app.core.db_retry.time.sleep"), \
             patch("app.core.db_retry.logger") as mock_logger:
            func()

        # 2 warnings (between attempts 1-2 and 2-3)
        self.assertEqual(mock_logger.warning.call_count, 2)

    def test_errors_when_retries_exhausted(self):
        retry = partial(with_db_retry, max_retries=2, backoff_base=0.001)

        @retry
        def func():
            raise _op_error("server gone")

        with patch("app.core.db_retry.time.sleep"), \
             patch("app.core.db_retry.logger") as mock_logger:
            with self.assertRaises(DatabaseConnectionError):
                func()

        self.assertEqual(mock_logger.error.call_count, 1)


# ---------------------------------------------------------------------------
# Decorator metadata preserved
# ---------------------------------------------------------------------------

class TestDecoratorMetadata(unittest.TestCase):
    def test_preserves_function_name(self):
        @with_db_retry
        def my_special_function():
            return 1

        self.assertEqual(my_special_function.__name__, "my_special_function")

    def test_preserves_docstring(self):
        @with_db_retry
        def func():
            """My docstring."""
            return 1

        self.assertEqual(func.__doc__, "My docstring.")


# ---------------------------------------------------------------------------
# Default constants
# ---------------------------------------------------------------------------

class TestDefaults(unittest.TestCase):
    def test_default_max_retries_is_three(self):
        self.assertEqual(DEFAULT_MAX_RETRIES, 3)

    def test_default_backoff_base_is_point_two(self):
        self.assertEqual(DEFAULT_BACKOFF_BASE, 0.2)