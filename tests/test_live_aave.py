from credit_delegation_risk.live_aave import (
    AAVE_V3_ETHEREUM_POOL,
    AccountState,
    BorrowHistory,
    _decode_address_array,
    _decode_words,
    _encode_address,
    _topic_address,
    get_account_state,
    verify_borrow_history,
)


class FakeRpc:
    def keccak_text(self, text: str) -> str:
        if text.startswith("Borrow("):
            return "0x" + "aa" * 32
        return "0x12345678" + "00" * 28

    def eth_call(self, *, to: str, data: str, block_number: int) -> str:
        assert to == AAVE_V3_ETHEREUM_POOL
        assert data.startswith("0x12345678")
        assert block_number == 123
        words = [2500 * 10**8, 1000 * 10**8, 500 * 10**8, 8000, 7000, int(1.25 * 10**18)]
        return "0x" + "".join(f"{word:064x}" for word in words)

    def transaction_receipt(self, tx_hash: str) -> dict:
        wallet = "0x" + "11" * 20
        return {
            "logs": [
                {
                    "address": AAVE_V3_ETHEREUM_POOL,
                    "blockNumber": hex(100),
                    "topics": [
                        "0x" + "aa" * 32,
                        "0x" + "00" * 12 + "22" * 20,
                        "0x" + "00" * 12 + wallet[2:],
                    ],
                }
            ]
        }


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


def test_decode_dynamic_address_array():
    addresses = ["11" * 20, "22" * 20]
    raw = (
        "0x"
        + f"{32:064x}"
        + f"{2:064x}"
        + ("0" * 24 + addresses[0]).rjust(64, "0")
        + ("0" * 24 + addresses[1]).rjust(64, "0")
    )
    assert _decode_address_array(raw) == [
        "0x" + addresses[0],
        "0x" + addresses[1],
    ]


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


def test_borrow_history_is_verified_against_pool_receipt():
    history = BorrowHistory(
        wallet_address="0x" + "11" * 20,
        earliest_borrow_block=100,
        earliest_borrow_tx="0x" + "33" * 32,
        variable_debt_token="0x" + "44" * 20,
    )
    assert verify_borrow_history(FakeRpc(), history) is True
