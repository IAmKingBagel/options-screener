from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.option import OptionChainResponse, OptionContractSnapshot


def test_option_contract_snapshot_valid():
    contract = OptionContractSnapshot(
        symbol="O:SPY260821C00150000",
        underlying_symbol="SPY",
        underlying_price=547.25,
        contract_type="call",
        expiration_date=date(2026, 8, 21),
        strike=150.0,
        dte=50,
        bid=2.10,
        ask=2.20,
        mid=2.15,
        spread_abs=0.10,
        spread_pct=0.0465,
    )
    assert contract.contract_type == "call"
    assert contract.dte == 50


def test_option_contract_snapshot_rejects_invalid_type():
    with pytest.raises(ValidationError):
        OptionContractSnapshot(
            symbol="X",
            underlying_symbol="SPY",
            contract_type="straddle",  # type: ignore[arg-type]
            expiration_date=date(2026, 8, 21),
            strike=150.0,
            dte=50,
        )


def test_option_chain_response_round_trip():
    now = datetime.now(timezone.utc)
    response = OptionChainResponse(
        underlying_symbol="SPY",
        underlying_price=547.25,
        fetched_at=now,
        contract_count=1,
        contracts=[
            OptionContractSnapshot(
                symbol="O:SPY260821C00150000",
                underlying_symbol="SPY",
                contract_type="call",
                expiration_date=date(2026, 8, 21),
                strike=150.0,
                dte=50,
            )
        ],
    )
    payload = response.model_dump(mode="json")
    assert payload["underlying_symbol"] == "SPY"
    assert payload["contract_count"] == 1
