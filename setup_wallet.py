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

console = Console(force_terminal=True, legacy_windows=False)

def generate_polymarket_credentials():
    console.print(Panel(
        "[bold cyan]🔑 ASISTENTE AUTOMÁTICO DE CREDENCIALES DE POLYMARKET CLOB[/bold cyan]\n"
        "[dim]Este asistente genera de forma 100% segura y privada tus 3 claves de API para operar en modo real.[/dim]",
        border_style="cyan"
    ))

    # 1. Obtener clave privada (por argumento de consola, archivo .env o entrada directa)
    raw_key = None
    if len(sys.argv) > 1 and len(sys.argv[1].strip()) >= 30:
        raw_key = sys.argv[1].strip()
        console.print("[green]✔ Clave privada detectada por argumento de consola.[/green]")
    else:
        # Verificar si está en variables de entorno o archivo .env
        env_key = os.getenv("POLYMARKET_PRIVATE_KEY", "").strip()
        if len(env_key) >= 30:
            console.print(f"[green]✔ Clave privada detectada en variable de entorno: {env_key[:6]}...{env_key[-4:]}[/green]")
            raw_key = env_key

    if not raw_key:
        console.print("\n[bold yellow]👉 Pega tu Clave Privada de MetaMask (Clic derecho o Ctrl+V para pegar):[/bold yellow]")
        try:
            # Usar input estándar para evitar bloqueos de teclado en Windows PowerShell
            raw_key = input("Clave Privada: ").strip()
        except KeyboardInterrupt:
            console.print("\n[red]Operación cancelada por el usuario.[/red]")
            return

    clean_key = raw_key.strip()
    if clean_key.startswith("'") or clean_key.startswith('"'):
        clean_key = clean_key[1:-1]
    if not clean_key.startswith("0x"):
        clean_key = "0x" + clean_key

    if len(clean_key) < 64:
        console.print(f"\n[bold red]❌ Error:[/] La clave privada ingresada es muy corta ({len(clean_key)} caracteres). Debe tener 64 caracteres.")
        return

    try:
        # 2. Derivar dirección pública
        account = Account.from_key(clean_key)
        funder_address = account.address
        console.print(f"\n[green]✅ Billetera Polygon Detectada:[/] [bold cyan]{funder_address}[/bold cyan]")

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

        # 5. Guardar automáticamente en .env local
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
        console.print("[bold green]💾 ¡Archivo .env actualizado localmente con tus credenciales![/bold green]\n")

    except Exception as e:
        console.print(f"\n[bold red]❌ Error al derivar credenciales con Polymarket:[/] {e}")
        console.print("[dim]Verifica que la clave privada sea correcta y que la computadora tenga conexión a internet.[/dim]")

if __name__ == "__main__":
    generate_polymarket_credentials()
