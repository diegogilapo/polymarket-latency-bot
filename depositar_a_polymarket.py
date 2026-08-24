import time
import json
import httpx
from eth_account import Account
from src.config import config
from src.utils.dns_resolver import setup_smart_dns

setup_smart_dns()

RPC_URL = "https://polygon.drpc.org"
NATIVE_USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
DEPOSIT_WALLET = "0xbb9C2007dADB32d6c9c33d7CD630A929DcC5eaaf"

def transfer_to_polymarket():
    private_key = config.polymarket_private_key.strip()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    account = Account.from_key(private_key)
    wallet_address = account.address

    print("=" * 70)
    print(f"🏦 Transfiriendo USDC a tu Cuenta de Depósito de Polymarket")
    print(f"  • Desde MetaMask: {wallet_address}")
    print(f"  • Hacia Polymarket: {DEPOSIT_WALLET}")
    print("=" * 70)

    client = httpx.Client(timeout=8.0)

    # 1. Consultar balance exacto de Native USDC
    clean_wallet = wallet_address.lower().replace("0x", "").zfill(64)
    call_data = "0x70a08231" + clean_wallet
    payload_bal = {"jsonrpc": "2.0", "method": "eth_call", "params": [{"to": NATIVE_USDC, "data": call_data}, "latest"], "id": 1}
    bal_hex = client.post(RPC_URL, json=payload_bal).json().get("result", "0x0")
    raw_bal = int(bal_hex, 16)
    usdc_bal = raw_bal / 1e6

    print(f"\n💵 Saldo en MetaMask: ${usdc_bal:.2f} USDC")

    if raw_bal == 0:
        print("❌ No hay saldo de USDC en la billetera.")
        return

    # 2. Consultar Nonce y Gas Price
    payload_nonce = {"jsonrpc": "2.0", "method": "eth_getTransactionCount", "params": [wallet_address, "latest"], "id": 2}
    nonce = int(client.post(RPC_URL, json=payload_nonce).json().get("result", "0x0"), 16)

    payload_gas = {"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 3}
    gas_price = int(client.post(RPC_URL, json=payload_gas).json().get("result", "0x0"), 16)
    gas_price = max(gas_price, int(35e9))

    # 3. Construir transfer(address recipient, uint256 amount) -> 0xa9059cbb
    clean_deposit = DEPOSIT_WALLET.lower().replace("0x", "").zfill(64)
    clean_amount = hex(raw_bal)[2:].zfill(64)
    transfer_data = "0xa9059cbb" + clean_deposit + clean_amount

    tx = {
        "to": NATIVE_USDC,
        "value": 0,
        "gas": 90000,
        "gasPrice": int(gas_price * 1.3),
        "nonce": nonce,
        "chainId": 137,
        "data": transfer_data
    }

    print(f"⏳ Enviando ${usdc_bal:.2f} USDC al contrato de Polymarket...")
    signed_tx = account.sign_transaction(tx)
    raw_tx_hex = "0x" + signed_tx.raw_transaction.hex() if hasattr(signed_tx, "raw_transaction") else "0x" + signed_tx.rawTransaction.hex()

    payload_send = {"jsonrpc": "2.0", "method": "eth_sendRawTransaction", "params": [raw_tx_hex], "id": 4}
    send_resp = client.post(RPC_URL, json=payload_send).json()

    if "error" in send_resp:
        print(f"❌ Error al transferir: {send_resp['error']}")
    else:
        tx_hash = send_resp.get("result")
        print(f"🚀 ¡Depósito enviado con éxito a Polymarket!")
        print(f"  TxHash: {tx_hash}")
        print("\n🎉 Los fondos llegarán a tu cuenta de trading en ~10 segundos.")

if __name__ == "__main__":
    transfer_to_polymarket()
