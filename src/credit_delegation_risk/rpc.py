from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class JsonRpcError(RuntimeError):
    pass


class JsonRpcClient:
    def __init__(self, url: str, timeout: float = 30.0) -> None:
        if not url:
            raise ValueError("RPC URL is required")
        self.url = url
        self.timeout = timeout
        self._request_id = 0

    def call(self, method: str, params: list[Any]) -> Any:
        self._request_id += 1
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = ""
            suffix = f": {error_body}" if error_body else ""
            raise JsonRpcError(
                f"RPC request failed for {method}: HTTP {exc.code}{suffix}"
            ) from exc
        except Exception as exc:
            raise JsonRpcError(f"RPC request failed for {method}: {exc}") from exc

        if "error" in body:
            raise JsonRpcError(f"RPC error for {method}: {body['error']}")
        if "result" not in body:
            raise JsonRpcError(f"RPC response missing result for {method}")
        return body["result"]

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def block(self, number: int) -> dict[str, Any]:
        result = self.call("eth_getBlockByNumber", [hex(number), False])
        if result is None:
            raise JsonRpcError(f"block not found: {number}")
        return result

    def logs(
        self,
        *,
        address: str,
        from_block: int,
        to_block: int,
        topics: list[str | None],
    ) -> list[dict[str, Any]]:
        return self.call(
            "eth_getLogs",
            [
                {
                    "address": address,
                    "fromBlock": hex(from_block),
                    "toBlock": hex(to_block),
                    "topics": topics,
                }
            ],
        )

    def eth_call(self, *, to: str, data: str, block_number: int) -> str:
        return self.call(
            "eth_call",
            [{"to": to, "data": data}, hex(block_number)],
        )

    def transaction_receipt(self, tx_hash: str) -> dict[str, Any]:
        result = self.call("eth_getTransactionReceipt", [tx_hash])
        if result is None:
            raise JsonRpcError(f"transaction receipt not found: {tx_hash}")
        return result

    def asset_transfers(self, params: dict[str, Any]) -> dict[str, Any]:
        result = self.call("alchemy_getAssetTransfers", [params])
        if not isinstance(result, dict):
            raise JsonRpcError("alchemy_getAssetTransfers returned non-object result")
        return result

    def keccak_text(self, text: str) -> str:
        encoded = "0x" + text.encode("utf-8").hex()
        return self.call("web3_sha3", [encoded])
