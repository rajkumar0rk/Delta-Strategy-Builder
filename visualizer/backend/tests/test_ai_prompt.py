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
