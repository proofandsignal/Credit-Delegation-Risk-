from credit_delegation_risk.live_aave import (
    AAVE_V3_ETHEREUM_POOL,
    AccountState,
    _decode_words,
    _encode_address,
    _topic_address,
    get_account_state,
)


class FakeRpc:
    def keccak_text(self, text: str) -> str:
        return "0x12345678" + "00" * 28

    def eth_call(self, *, to: str, data: str, block_number: int) -> str:
        assert to == AAVE_V3_ETHEREUM_POOL
        assert data.startswith("0x12345678")
        assert block_number == 123
        words = [2500 * 10**8, 1000 * 10**8, 500 * 10**8, 8000, 7000, int(1.25 * 10**18)]
        return "0x" + "".join(f"{word:064x}" for word in words)


def test_encode_address_is_abi_word():
    value = _encode_address("0x00000000000000000000000000000000000000ab")
    assert len(value) == 64
    assert value.endswith("00ab")


def test_topic_address_extracts_indexed_address():
    topic = "0x" + "00" * 12 + "11" * 20
    assert _topic_address(topic) == "0x" + "11" * 20


def test_decode_words():
    raw = "0x" + f"{1:064x}{2:064x}{3:064x}"
    assert _decode_words(raw, 3) == [1, 2, 3]


def test_get_account_state_decodes_aave_pool_response():
    state = get_account_state(
        FakeRpc(),
        "0x00000000000000000000000000000000000000ab",
        123,
    )
    assert state == AccountState(
        total_collateral_base=2500 * 10**8,
        total_debt_base=1000 * 10**8,
        available_borrows_base=500 * 10**8,
        current_liquidation_threshold_bps=8000,
        ltv_bps=7000,
        health_factor_raw=int(1.25 * 10**18),
    )
