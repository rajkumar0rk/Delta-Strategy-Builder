"""Offline platform-specific peak memory reader sanity checks."""
import sys

from backtest.process_memory import peak_process_rss_kib


def test_peak_process_memory_reader_is_nonnegative_or_unavailable():
    result = peak_process_rss_kib()
    assert result is None or (type(result) is int and result > 0)
    if sys.platform.startswith("linux") or sys.platform == "win32":
        assert result is not None


def test_benchmark_cli_exposes_diagnostic_retention_option():
    from backtest import benchmark_legacy_run
    import inspect
    signature = inspect.signature(benchmark_legacy_run.benchmark)
    assert "retain_decision_events" in signature.parameters
    assert signature.parameters["retain_decision_events"].default is True
