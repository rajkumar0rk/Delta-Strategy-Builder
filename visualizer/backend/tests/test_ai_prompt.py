from app.ai_prompt import build_strategy_prompt
from app.models import AiStrategyPromptRequest, StrategyConfig


def test_ai_prompt_documents_current_v15_1_contract():
    text = build_strategy_prompt(AiStrategyPromptRequest(strategy=StrategyConfig()))
    assert 'BTC Strategy Lab V15.1' in text
    assert 'CALL and PUT have separate exit rule groups' in text
    assert 'NO TRADE' in text
    assert '"schema_version":15' in text
    assert 'CROSSES_ABOVE' in text
    assert 'historical IV' in text
    assert 'fixed UTC clock-close boundaries' in text
    assert 'enforce_trade_budget_strict' in text
    assert 'LOW_FIDELITY_SYNTHETIC_BBO' in text
