from app.ai_prompt import build_strategy_prompt
from app.models import AiStrategyPromptRequest, StrategyConfig


def test_ai_prompt_documents_current_v15_2_v16_contract():
    prompt = build_strategy_prompt(AiStrategyPromptRequest(strategy=StrategyConfig()))
    # The product release advances, but imported strategy JSON remains v15.
    assert 'BTC Strategy Lab V15.2 / V16 research mode' in prompt
    assert '"schema_version":15' in prompt

    # Previously supported strategy and data-quality contracts remain documented.
    assert 'CALL and PUT have separate exit rule groups' in prompt
    assert 'NO TRADE' in prompt
    assert 'CROSSES_ABOVE' in prompt
    assert 'historical IV' in prompt
    assert 'fixed UTC clock-close boundaries' in prompt
    assert 'enforce_trade_budget_strict' in prompt
    assert 'LOW_FIDELITY_SYNTHETIC_BBO' in prompt

    # Newly documented capabilities and limitations.
    assert 'V15.2 ACCURACY & TRUST' in prompt
    assert 'warmup_candles' in prompt
    assert 'warmup_policy' in prompt
    assert 'end_of_data_quote_max_age_seconds' in prompt
    assert 'mark-to-market drawdown' in prompt
    assert 'V16 PHASE 1 EXECUTION-COST SENSITIVITY' in prompt
    assert 'analysis-only' in prompt


def test_ai_prompt_distinguishes_strategy_schema_and_backtest_controls():
    strategy = StrategyConfig()
    prompt = build_strategy_prompt(AiStrategyPromptRequest(strategy=strategy))

    assert 'BacktestRequest fields only' in prompt
    assert 'keep schema_version=15' in prompt
    assert 'execution_stress is NOT part of StrategyConfig' not in prompt
    assert 'Execution stress is NOT part of StrategyConfig' in prompt

    # Warm-up is a backtest request, not a new importable strategy field.
    assert 'warmup_candles' not in StrategyConfig.model_fields
    assert 'warmup_policy' not in StrategyConfig.model_fields
    assert strategy.execution.end_of_data_quote_max_age_seconds == 300



def test_prompt_documents_daily_levels_and_identity_rearming():
    prompt = build_strategy_prompt(AiStrategyPromptRequest(strategy=StrategyConfig()))
    for text in ('DAY_LEVELS', 'reset_operand', 'older_history_ready',
                 'first backward chronological matches', 'intrabar event order'):
        assert text in prompt
    assert 'reset_operand' in StrategyConfig.model_json_schema()['$defs']['AlertRule']['properties']


def test_futures_prompt_mentions_current_research_contract():
    strategy=StrategyConfig(market_type="FUTURES")
    prompt=build_strategy_prompt(AiStrategyPromptRequest(strategy=strategy))
    for phrase in ("schema_version=15","funding_rate_multiplier",
                   "September 8, 2025", "frozen holdout", "margin_tier_mode",
                   "NOT fields in strategy JSON", "NOT Delta-verified"):
        assert phrase in prompt


def test_importable_futures_example_matches_current_strategy_schema():
    import json
    from pathlib import Path
    example=Path(__file__).resolve().parents[2]/"examples"/"btcusd-futures-research.template.json"
    payload=json.loads(example.read_text(encoding="utf-8"))
    assert payload["schema_version"]==15
    assert payload["app"]=="BTC Strategy Lab"
    validated=StrategyConfig.model_validate(payload["strategy"])
    assert validated.market_type=="FUTURES"
    assert validated.futures.funding_mode=="EXCLUDE_WITH_WARNING"
    assert validated.position_policy=="EXCLUSIVE"


def test_futures_ai_prompt_documents_stateful_risk_mode_and_example():
    strategy = StrategyConfig(market_type="FUTURES")
    prompt = build_strategy_prompt(AiStrategyPromptRequest(strategy=strategy))
    for term in ("futures.pullback.enabled=true", "max_wait_bars",
                 "swing_lookback_bars", "stop_buffer_atr", "reward_r_multiple",
                 "equity_risk_percent", "risk budget", "NEXT 5m OPEN",
                 "btc-futures-stateful-1h-15m-5m.strategy.json"):
        assert term.lower() in prompt.lower()
    assert "BOTH legacy fields MUST be null" in prompt
    assert "Schema version remains 15" in prompt


def test_stateful_futures_example_can_be_validated():
    from pathlib import Path
    import json
    path = Path(__file__).resolve().parents[1] / "examples" / "btc-futures-stateful-1h-15m-5m.strategy.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    assert obj["schema_version"] == 15
    strategy = StrategyConfig.model_validate(obj["strategy"])
    assert strategy.futures.pullback.enabled
    assert strategy.futures.stop_loss_percent is None
    assert strategy.futures.take_profit_percent is None
    assert strategy.market_type == "FUTURES"


def test_generation_prompt_rejects_unrecognized_strategy_fields_and_locates_request_settings():
    from pathlib import Path

    guide = (Path(__file__).resolve().parents[2] / "codex" /
             "STRATEGY_JSON_GENERATION_PROMPT.md").read_text(encoding="utf-8")
    assert "schema_version" in guide and "StrategyConfig.model_validate" in guide
    assert "unknown keys" in guide.lower()
    for text in ("dataset_mode", "warmup_candles", "storage_mode",
                 "EXCLUDE_WITH_WARNING", "PULLBACK_SETUP", "RESEARCH_ONLY"):
        assert text in guide


def test_futures_ai_prompt_explicitly_documents_planner_and_schema_guards():
    prompt = build_strategy_prompt(
        AiStrategyPromptRequest(strategy=StrategyConfig(market_type="FUTURES"))
    )
    for fragment in ("unknown strategy keys", "max_wait_bars * 5",
                     "PULLBACK_SETUP", "ordinary EntryBehavior lifecycle",
                     "funding CSV exists", "BacktestRequest"):
        # The request/settings contract is represented by a list of fields,
        # not necessarily the class name in the futures-specific prompt.
        if fragment == "BacktestRequest":
            assert "warmup_candles" in prompt and "storage_mode" in prompt
        else:
            assert fragment in prompt


def test_options_ai_prompt_documents_strict_generation_contract():
    prompt = build_strategy_prompt(AiStrategyPromptRequest(strategy=StrategyConfig()))
    assert "STRATEGY_JSON_GENERATION_PROMPT.md" in prompt
    assert "Reject unknown keys" in prompt

def test_intraday_stop_market_futures_example_and_generation_contract():
    import json
    from pathlib import Path
    path = (Path(__file__).resolve().parents[1] / "examples" /
            "btc-futures-intraday-1h-15m-stop-market.strategy.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload['schema_version'] == 15
    strategy = StrategyConfig.model_validate(payload['strategy'])
    pullback = strategy.futures.pullback
    assert strategy.market_type == 'FUTURES'
    assert pullback.enabled and pullback.execution_mode == 'STOP_MARKET_INTRABAR'
    assert pullback.stop_anchor == 'SIGNAL_CANDLE'
    assert pullback.breakout_buffer_ticks == 1 and pullback.max_wait_bars == 6
    assert pullback.trend_crossover_block_bars == 3
    assert strategy.futures.force_exit_time == '23:45'
    assert strategy.risk.max_daily_loss_percent == 1
    assert strategy.risk.max_hold_minutes is None
    assert strategy.session.timezone == 'Asia/Kolkata'
    assert strategy.session.windows[0].end == '21:59'
    prompt = build_strategy_prompt(AiStrategyPromptRequest(strategy=strategy))
    for term in ('STOP_MARKET_INTRABAR', 'SIGNAL_CANDLE', 'breakout_buffer_ticks',
                 'trend_crossover_block_bars', 'force_exit_time',
                 'extra_half_spread_bps', 'btc-futures-intraday-1h-15m-stop-market.strategy.json'):
        assert term in prompt

def test_importable_options_shared_pullback_and_ai_prompt_contract():
    from pathlib import Path
    import json
    path=(Path(__file__).resolve().parents[1]/'examples'/
          'btc-options-intraday-pullback.strategy.json')
    payload=json.loads(path.read_text(encoding='utf-8'))
    assert payload['schema_version']==15 and payload['app']=='BTC Strategy Lab'
    strategy=StrategyConfig.model_validate(payload['strategy'])
    assert strategy.market_type=='OPTIONS'
    assert strategy.options_pullback.enabled
    assert strategy.options_pullback.execution_mode=='STOP_MARKET_INTRABAR'
    assert strategy.options_pullback.stop_anchor=='SIGNAL_CANDLE'
    assert strategy.options_pullback.trend_crossover_block_bars==3
    assert strategy.options_force_exit_time=='23:45'
    assert strategy.risk.stop_loss.mode=='NONE'
    p=build_strategy_prompt(AiStrategyPromptRequest(strategy=strategy))
    for key in ('options_pullback.enabled', 'options_force_exit_time',
                'BUY CALL/BUY PUT', 'option premium', 'underlying_tick_size',
                'OPTIONS_PULLBACK_BACKTEST.md'):
        assert key.lower() in p.lower()


def test_options_signal_stop_and_futures_schema_remain_documented():
    from app.ai_prompt import build_strategy_prompt
    from app.models import AiStrategyPromptRequest, StrategyConfig
    prompt=build_strategy_prompt(AiStrategyPromptRequest(strategy=StrategyConfig()))
    assert 'UNDERLYING_SIGNAL_CANDLE' in prompt
    assert 'signal_candle_execution_timeframe' in prompt
    assert 'FUTURES' in prompt
    assert 'BUY CALL' in prompt
