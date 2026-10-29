from __future__ import annotations

import json
from app import main
from app.models import StrategyConfig


def test_saved_strategy_load_uses_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "project_root", lambda: tmp_path)
    folder=tmp_path/"strategy-lab"/"strategies"
    folder.mkdir(parents=True)
    payload={"schema_version":15,"app":"BTC Strategy Lab",
             "strategy":StrategyConfig(market_type="FUTURES").model_dump()}
    (folder/"futures-example.strategy.json").write_text(json.dumps(payload),encoding="utf-8")
    loaded=main.load_strategy("futures-example")
    assert loaded["strategy"]["market_type"]=="FUTURES"
    assert loaded["payload"]["schema_version"]==15
