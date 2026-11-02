"""Contract lookup parity including expiry activation and strike ties."""
from dataclasses import replace
import random
import pytest
from backtest.data import OptionSpec
from backtest.option_expiry_index import OptionExpiryIndex
from backtest.ema_vwap_research import _select_option


def sample_specs():
    options=[]
    base=1_800_000_000_000_000_000
    day=86_400_000_000_000
    for i in range(90):
        expiry=base+(1+i%10)*day
        options.append(OptionSpec(
            symbol=f"BTC-{i}",source_symbol=f"BTC-{i}",expiry="EX",
            strike=float(100000+(i%7-3)*500),
            option_type="CE" if i%2 else "PE",
            activation_ns=base-(i%4)*day+((i%3)*day),
            expiration_ns=expiry,price_precision=1,size_precision=0,
            price_increment=0.5,size_increment=1,lot_size=1,
            min_quantity=1,contract_value=.001,
        ))
    return options,base,day


@pytest.mark.parametrize("inclusive", [True,False])
def test_index_matches_original_selection_across_signals(inclusive):
    specs,base,day=sample_specs()
    index=OptionExpiryIndex(specs)
    rng=random.Random(1234)
    for _ in range(800):
        signal=base+rng.randrange(-1,8)*day+rng.randrange(0,24)*3_600_000_000_000
        direction=rng.choice(["CALL","PUT"])
        underlying=100000+rng.randrange(-8,8)*250
        low=rng.choice([0,0.5,1,2])
        high=rng.choice([3,4,9])
        opts=dict(min_days_to_expiry=low,
                  min_days_to_expiry_inclusive=inclusive,
                  max_days_to_expiry=high)
        assert index.select(signal,direction,underlying,**opts)==_select_option(
            specs,signal,direction,underlying,**opts)


def test_index_validates_invalid_dte():
    index=OptionExpiryIndex([])
    with pytest.raises(ValueError,match="invalid option expiry range"):
        index.select(10,"CALL",100,min_days_to_expiry=-1)
