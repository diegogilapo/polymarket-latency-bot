import time
import json
import httpx
from eth_account import Account
from src.config import config
from src.utils.dns_resolver import setup_smart_dns

setup_smart_dns()

RPC_URL = "https://polygon.drpc.org"
USDC_CONTRACT = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # Native USDC on Polygon
USDC_E_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # Bridged USDC.e

# Contratos de Polymarket que necesitan permiso de gasto (Allowance)
SPENDERS = [
    ("Polymarket Exchange V2", "0xE111180000d2663C0091e4f400237545B87B996B"),
    ("Polymarket Neg Risk V2", "0xe2222d279d744050d28e00520010520000310F59"),
    ("Polymarket Neg Risk Adapter", "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"),
    ("Polymarket CTF Exchange V1", "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"),
]

# Firma ABI de approve(address spender, uint256 amount) -> 0x095ea7b3
MAX_UINT256 = "f" * 64

def check_and_approve():
    private_key = config.polymarket_private_key.strip()
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    account = Account.from_key(private_key)
    wallet_address = account.address

    print("=" * 70)
    print(f"🔑 Verificando Billetera: {wallet_address}")
    print("=" * 70)

    client = httpx.Client(timeout=8.0)

    # 1. Verificar balance de POL (Gas)
    payload_pol = {"jsonrpc": "2.0", "method": "eth_getBalance", "params": [wallet_address, "latest"], "id": 1}
    resp = client.post(RPC_URL, json=payload_pol)
    wei_bal = int(resp.json().get("result", "0x0"), 16)
    pol_bal = wei_bal / 1e18
    print(f"⛽ Balance de Gas (POL): {pol_bal:.6f} POL")

    if pol_bal < 0.005:
        print("\n❌ POL INSUFICIENTE PARA EL GAS.")
        print(f"👉 Envía al menos $0.10 USD en POL a tu billetera ({wallet_address}) en la red Polygon.")
        print("En cuanto lo envíes, vuelve a ejecutar este comando.")
        return

    # 2. Obtener Nonce y Gas Price
    payload_nonce = {"jsonrpc": "2.0", "method": "eth_getTransactionCount", "params": [wallet_address, "latest"], "id": 2}
    nonce = int(client.post(RPC_URL, json=payload_nonce).json().get("result", "0x0"), 16)

    payload_gas = {"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 3}
    gas_price = int(client.post(RPC_URL, json=payload_gas).json().get("result", "0x0"), 16)
    gas_price = max(gas_price, int(35e9))  # Mínimo 35 Gwei en Polygon

    # 3. Aprobar cada contrato para Native USDC y USDC.e
    for token_name, token_addr in [("Native USDC", USDC_CONTRACT), ("USDC.e", USDC_E_CONTRACT)]:
        print(f"\n📝 Verificando aprobaciones para {token_name} ({token_addr})...")
        for spender_name, spender_addr in SPENDERS:
            clean_spender = spender_addr.lower().replace("0x", "").zfill(64)
            clean_wallet = wallet_address.lower().replace("0x", "").zfill(64)

            # Consultar allowance actual
            call_data = "0xdd62ed3e" + clean_wallet + clean_spender
            payload_allowance = {"jsonrpc": "2.0", "method": "eth_call", "params": [{"to": token_addr, "data": call_data}, "latest"], "id": 4}
            allowance_hex = client.post(RPC_URL, json=payload_allowance).json().get("result", "0x0")
            allowance_val = int(allowance_hex, 16)

            if allowance_val > 10**12:
                print(f"  ✅ {spender_name}: YA APROBADO (Ilimitado)")
                continue

            print(f"  ⏳ Aprobando {spender_name} en la blockchain...")
            approve_data = "0x095ea7b3" + clean_spender + MAX_UINT256
            tx = {
                "to": token_addr,
                "value": 0,
                "gas": 65000,
                "gasPrice": int(gas_price * 1.2),
                "nonce": nonce,
                "chainId": 137,
                "data": approve_data
            }
            signed_tx = account.sign_transaction(tx)
            raw_tx_hex = "0x" + signed_tx.raw_transaction.hex() if hasattr(signed_tx, "raw_transaction") else "0x" + signed_tx.rawTransaction.hex()

            payload_send = {"jsonrpc": "2.0", "method": "eth_sendRawTransaction", "params": [raw_tx_hex], "id": 5}
            send_resp = client.post(RPC_URL, json=payload_send).json()
            
            if "error" in send_resp:
                print(f"    ❌ Error al aprobar: {send_resp['error']}")
            else:
                tx_hash = send_resp.get("result")
                print(f"    🚀 Transacción enviada con éxito! TxHash: {tx_hash}")
                nonce += 1
                time.sleep(2)

    print("\n" + "=" * 70)
    print("🎉 ¡TODOS LOS CONTRATOS DE POLYMARKET QUEDARON APROBADOS!")
    print("=" * 70)

if __name__ == "__main__":
    check_and_approve()
