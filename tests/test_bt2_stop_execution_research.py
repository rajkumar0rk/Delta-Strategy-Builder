from backtest.bt2_stop_execution_research import stop_execution_scenarios


def test_stop_execution_matrix_changes_only_bt2_stop_settings():
    scenarios = stop_execution_scenarios()

    assert len(scenarios) == 8
    assert {scenario.group for scenario in scenarios} == {2}
    assert {scenario.exit_mode for scenario in scenarios} == {"EMA_VWAP"}
    assert {scenario.hard_stop_percent_override for scenario in scenarios} == {
        -10.0,
        -12.5,
        -15.0,
        -17.5,
    }
    assert {scenario.hard_stop_fill_mode for scenario in scenarios} == {
        "SAME_QUOTE",
        "NEXT_QUOTE",
    }
    assert all(scenario.min_option_true_ranges == 0 for scenario in scenarios)
    assert all(scenario.fee_aware_multiplier == 0.0 for scenario in scenarios)
