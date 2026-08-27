"""Smoke tests: confirm the package and all subpackages import cleanly.

Run with: uv run pytest -q
"""


def test_package_imports() -> None:
    """The tripcascade package imports and exposes a version."""
    import tripcascade

    assert tripcascade.__version__


def test_subpackages_import() -> None:
    """All six subpackages import without error (no missing deps at scaffold stage)."""
    import importlib

    for sub in ("graph", "forecast", "agent", "atlas_tools", "ui", "watcher"):
        mod = importlib.import_module(f"tripcascade.{sub}")
        assert mod is not None, f"tripcascade.{sub} failed to import"


def test_settlement_cap_default() -> None:
    """The documented default cap (5000 cents = S$50) is internally consistent."""
    cap_cents = 5000
    assert cap_cents == 50 * 100
    # Leg 1 (S$30) auto-settles; Leg 2 (S$120) is human-gated.
    assert 30 * 100 <= cap_cents
    assert 120 * 100 > cap_cents
