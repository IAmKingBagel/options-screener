from datetime import date
from unittest.mock import patch

from app.services.chain_service import ChainService


def test_chain_endpoint_with_mocked_massive(client, massive_chain_sample):
    with patch.object(ChainService, "get_chain") as mock_get_chain:
        from datetime import datetime, timezone

        from app.schemas.option import OptionChainResponse, OptionContractSnapshot

        mock_get_chain.return_value = OptionChainResponse(
            underlying_symbol="SPY",
            underlying_price=547.25,
            fetched_at=datetime.now(timezone.utc),
            contract_count=1,
            warnings=["Data may be delayed."],
            contracts=[
                OptionContractSnapshot(
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
                )
            ],
        )

        response = client.get("/api/chain/SPY?min_dte=14&max_dte=60")
        assert response.status_code == 200
        payload = response.json()
        assert payload["underlying_symbol"] == "SPY"
        assert payload["contract_count"] == 1
        assert payload["contracts"][0]["mid"] == 2.15
        assert any("delayed" in warning.lower() for warning in payload["warnings"])


def test_chain_service_stores_snapshot(db_session, massive_chain_sample):
    class FakeClient:
        def get_option_chain_snapshot(self, symbol, params=None, *, max_pages=4):
            assert symbol == "SPY"
            return massive_chain_sample

        def get_underlying_price(self, symbol):
            return 547.25

    service = ChainService(client=FakeClient())
    chain = service.get_chain(
        db_session,
        "SPY",
        min_dte=14,
        max_dte=60,
        force_refresh=True,
    )

    assert chain.underlying_symbol == "SPY"
    assert chain.contract_count == 2
    assert chain.snapshot_id is not None
    assert chain.contracts[0].spread_pct is not None
