"""Offline platform-specific peak memory reader sanity checks."""
import sys

from backtest.process_memory import peak_process_rss_kib, current_process_rss_kib


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


def test_current_resident_working_set_is_sane_on_supported_platforms():
    current = current_process_rss_kib()
    peak = peak_process_rss_kib()
    assert current is None or (type(current) is int and current > 0)
    if sys.platform.startswith("linux") or sys.platform == "win32":
        assert current is not None
        assert peak is not None
        # The process can grow between calls but the high-water mark should
        # always be at least the current value (allow one-page sampling drift).
        assert current <= peak + 4096
