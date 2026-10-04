from app.core.env import env_int


def test_env_int_uses_default_when_unset_or_invalid(monkeypatch):
    monkeypatch.delenv("F19_TEST_INTEGER", raising=False)
    assert env_int("F19_TEST_INTEGER", 10, 1) == 10
    monkeypatch.setenv("F19_TEST_INTEGER", "")
    assert env_int("F19_TEST_INTEGER", 10, 1) == 10
    monkeypatch.setenv("F19_TEST_INTEGER", "bad")
    assert env_int("F19_TEST_INTEGER", 10, 1) == 10
    monkeypatch.setenv("F19_TEST_INTEGER", "0")
    assert env_int("F19_TEST_INTEGER", 10, 1) == 10


def test_env_int_accepts_pool_values(monkeypatch):
    monkeypatch.setenv("F19_TEST_INTEGER", "25")
    assert env_int("F19_TEST_INTEGER", 10, 1) == 25
