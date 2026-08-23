import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from eth_account import Account
from py_clob_client.client import ClobClient
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console(force_terminal=True, legacy_windows=False)

def generate_polymarket_credentials():
    console.print(Panel(
        "[bold cyan]🔑 ASISTENTE AUTOMÁTICO DE CREDENCIALES DE POLYMARKET CLOB[/bold cyan]\n"
        "[dim]Este asistente genera de forma 100% segura y privada tus 3 claves de API para operar en modo real.[/dim]",
        border_style="cyan"
    ))

    # 1. Solicitar clave privada de forma segura
    console.print("\n[bold yellow]👉 Ingresa tu Clave Privada de MetaMask (Polygon):[/bold yellow]")
    console.print("[dim](No te preocupes, se procesa únicamente en tu computadora de forma local)[/dim]")
    
    raw_key = Prompt.ask("[bold white]Clave Privada[/bold white]", password=True)
    clean_key = raw_key.strip()
    
    if not clean_key.startswith("0x"):
        clean_key = "0x" + clean_key

    try:
        # 2. Derivar dirección pública
        account = Account.from_key(clean_key)
        funder_address = account.address
        console.print(f"\n[green]✅ Billetera Detectada:[/] [bold cyan]{funder_address}[/bold cyan]")

        # 3. Conectar al CLOB de Polymarket en Polygon (Chain ID 137)
        console.print("[yellow]⏳ Conectando con Polymarket y firmando mensaje criptográfico EIP-712...[/yellow]")
        
        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=clean_key
        )

        creds = client.create_or_derive_api_creds()
        
        # 4. Mostrar Credenciales Listas
        cred_text = (
            f"[bold green]🎉 ¡Tus credenciales oficiales han sido generadas con éxito![/bold green]\n\n"
            f"[bold white]1. POLYMARKET_FUNDER_ADDRESS:[/bold white]\n"
            f"[cyan]{funder_address}[/cyan]\n\n"
            f"[bold white]2. POLYMARKET_PRIVATE_KEY:[/bold white]\n"
            f"[cyan]{clean_key}[/cyan]\n\n"
            f"[bold white]3. POLYMARKET_API_KEY:[/bold white]\n"
            f"[yellow]{creds.api_key}[/yellow]\n\n"
            f"[bold white]4. POLYMARKET_API_SECRET:[/bold white]\n"
            f"[yellow]{creds.api_secret}[/yellow]\n\n"
            f"[bold white]5. POLYMARKET_PASSPHRASE:[/bold white]\n"
            f"[yellow]{creds.api_passphrase}[/yellow]\n\n"
            f"[dim]------------------------------------------------------------\n"
            f"📌 Copia estos 5 valores en la pestaña Environment de tu panel de Render.com[/dim]"
        )

        console.print(Panel(cred_text, title="📋 TUS VARIABLES PARA RENDER.COM", border_style="green"))

        # 5. Opción de guardar en .env local
        save_env = Prompt.ask("\n¿Deseas guardar automáticamente estas variables en tu archivo .env local?", choices=["s", "n"], default="s")
        if save_env.lower() == "s":
            env_content = f"""# Configuración de Producción - Polymarket Bot
SIMULATION_MODE=False
ORDER_SIZE_USDC=25.0
POLYMARKET_FUNDER_ADDRESS={funder_address}
POLYMARKET_PRIVATE_KEY={clean_key}
POLYMARKET_API_KEY={creds.api_key}
POLYMARKET_API_SECRET={creds.api_secret}
POLYMARKET_PASSPHRASE={creds.api_passphrase}
"""
            with open(".env", "w", encoding="utf-8") as f:
                f.write(env_content)
            console.print("[bold green]💾 ¡Archivo .env guardado localmente con éxito![/bold green]\n")

    except Exception as e:
        console.print(f"\n[bold red]❌ Error al derivar credenciales:[/] {e}")
        console.print("[dim]Verifica que la clave privada sea válida (64 caracteres hexadecimales).[/dim]")

if __name__ == "__main__":
    generate_polymarket_credentials()
