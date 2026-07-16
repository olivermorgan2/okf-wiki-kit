"""Shared pytest configuration for the okf-wiki-kit test suite."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: opt-in tests against a real built vault (gated by the "
        "OKF_TEST_VAULT env var; see tests/test_integration.py).",
    )
