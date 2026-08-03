from datetime import date

import pytest

from app.data.providers import normalize_massive_chain, normalize_massive_contract


def test_normalize_massive_contract_call(massive_chain_sample):
    raw = massive_chain_sample["results"][0]
    contract = normalize_massive_contract(
        raw,
        as_of=date(2026, 7, 2),
        include_raw_payload=True,
    )

    assert contract.symbol == "O:SPY260821C00150000"
    assert contract.underlying_symbol == "SPY"
    assert contract.contract_type == "call"
    assert contract.strike == 150.0
    assert contract.dte == 50
    assert contract.bid == 2.10
    assert contract.ask == 2.20
    assert contract.mid == 2.15
    assert contract.spread_abs == pytest.approx(0.10)
    assert contract.open_interest == 1543
    assert contract.delta == 0.52
    assert contract.provider == "massive"
    assert contract.has_live_quote is True
    assert contract.raw_provider_payload is not None


def test_normalize_massive_chain(massive_chain_sample):
    contracts, underlying_price, warnings = normalize_massive_chain(
        massive_chain_sample,
        as_of=date(2026, 7, 2),
        underlying_price_override=547.25,
    )

    assert len(contracts) == 2
    assert underlying_price == 547.25
    assert warnings == []
    assert {c.contract_type for c in contracts} == {"call", "put"}
