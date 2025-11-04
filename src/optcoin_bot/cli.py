import asyncio
import time

import click
import uvicorn

from optcoin_bot.actions import (
    get_accounts_to_process,
    run_submit_order_for_account,
    run_login_for_account,
)
from optcoin_bot.config import app_config
from optcoin_bot.orchestrator import orchestrate_accounts
from optcoin_bot.playwright_adapter import PlaywrightAdapter
from optcoin_bot.server.main import app as fastapi_app
from optcoin_bot.telegram_bot import run_bot as run_telegram_bot


from optcoin_bot.utils.logging import get_logger

logger = get_logger("CLI")

def sanitize_for_console(text) -> str:
    return str(text).encode("cp1252", "replace").decode("cp1252")


@click.group()
def cli():
    """Bot de Copy Trading OPTCOIN"""
    pass


@cli.command()
@click.option("--mode", type=click.Choice(["visible", "invisible"]), default="invisible")
@click.option("--accounts-file", default="optcoin-bot/accounts.json")
@click.option("--performant/--no-performant", default=True)
def login(mode: str, accounts_file: str, performant: bool):
    """Automatise la connexion pour tous les comptes configurés."""
    headless = mode == "invisible"
    accounts_to_process = get_accounts_to_process(accounts_file)
    if not accounts_to_process:
        click.echo(click.style("Aucun compte trouvé. Veuillez configurer accounts.json ou votre fichier .env.", fg="red"))
        return

    click.echo(f"Tentative de connexion pour {len(accounts_to_process)} comptes en mode {mode} (performant={performant}) ...")

    start_wall = time.perf_counter()

    async def main():
        async with PlaywrightAdapter() as adapter:
            browser = await adapter.launch_browser(headless=headless)
            try:
                results = await orchestrate_accounts(
                    accounts=accounts_to_process,
                    run_for_account=run_login_for_account,
                    max_concurrency=app_config.max_concurrent_accounts,
                    browser=browser,
                    adapter=adapter,
                    dry_run=False,
                    performant=performant,
                )
                return results
            finally:
                pass

    try:
        results = asyncio.run(main())
    except Exception as e:
        err = sanitize_for_console(str(e))
        click.echo(click.style(f"Erreur fatale lors de l'exécution de la connexion : {err}", fg="red"))
        results = []
    
    for result in results:
        if isinstance(result, dict):
            account_name = result.get("account_name", "Unknown Account")
            if result.get("success"):
                click.echo(f"{account_name}: {click.style('Connexion RÉUSSIE', fg='green')}")
            else:
                error_msg = sanitize_for_console(result.get("error", "Unknown error"))
                click.echo(f"{account_name}: {click.style('Connexion ÉCHOUÉE', fg='red')} - {error_msg}")
        else:
            err = sanitize_for_console(str(result))
            click.echo(f"{click.style('Connexion ÉCHOUÉE', fg='red')} - Unexpected error: {err}")

    if app_config.enforce_min_run_per_execution:
        elapsed = time.perf_counter() - start_wall
        remaining = float(app_config.min_run_seconds) - float(elapsed)
        if remaining > 0:
            time.sleep(remaining)

    click.echo("Toutes les tentatives de connexion sont terminées.")


@cli.command()
@click.argument("order_number")
@click.option("--dry-run", is_flag=True, default=False)
@click.option("-y", "--yes", is_flag=True)
@click.option("--mode", type=click.Choice(["visible", "invisible"]), default="invisible")
@click.option("--accounts-file", default="optcoin-bot/accounts.json")
@click.option("--performant/--no-performant", default=True)
@click.option("--skip-history-verification", is_flag=True, default=False)
@click.option("--max-retries", type=int, default=1)
def submit_order(
    order_number: str,
    dry_run: bool,
    yes: bool,
    mode: str,
    accounts_file: str,
    performant: bool,
    skip_history_verification: bool,
    max_retries: int,
):
    """Exécute le processus de soumission d'ordre pour tous les comptes configurés."""
    if not dry_run and not yes:
        click.confirm(
            "ATTENTION : Vous êtes sur le point d'exécuter des ordres RÉELS. Voulez-vous continuer ?",
            abort=True,
        )

    headless = mode == "invisible"
    initial_accounts = get_accounts_to_process(accounts_file)
    if not initial_accounts:
        click.echo(
            click.style(
                "Aucun compte trouvé. Veuillez configurer accounts.json ou votre fichier .env.",
                fg="red",
            )
        )
        return

    start_wall = time.perf_counter()

    async def main():
        async with PlaywrightAdapter() as adapter:
            browser = await adapter.launch_browser(headless=headless)
            try:
                results = await orchestrate_accounts(
                    accounts=initial_accounts,
                    run_for_account=run_submit_order_for_account,
                    max_concurrency=app_config.max_concurrent_accounts,
                    browser=browser,
                    adapter=adapter,
                    order_number=order_number,
                    dry_run=dry_run,
                    headless=headless,
                    performant=performant,
                    skip_history_verification=skip_history_verification,
                )
                logger.info(f"Results from orchestrate_accounts: {results}")
                return results
            finally:
                pass

    try:
        final_reports = asyncio.run(main())
    except Exception as e:
        err = sanitize_for_console(str(e))
        click.echo(click.style(f"Erreur fatale lors de l'exécution de la soumission d'ordre : {err}", fg="red"))
        final_reports = []

    click.echo("\n--- Résumé final de l'exécution ---")
    success_count = sum(1 for r in final_reports if isinstance(r, dict) and r.get("success"))
    for report in final_reports:
        if isinstance(report, dict):
            account_name = report.get("account_name", "Unknown Account")
            if report.get("success"):
                click.echo(f"{account_name}: {click.style('SUCCÈS', fg='green')}")
            else:
                error_msg = sanitize_for_console(report.get("error", "Unknown error"))
                click.echo(
                    f"{account_name}: {click.style('ÉCHEC', fg='red')} - {error_msg}"
                )
        else:
            err = sanitize_for_console(str(report))
            click.echo(f"{click.style('ÉCHEC', fg='red')} - Unexpected error: {err}")

    if app_config.enforce_min_run_per_execution:
        elapsed = time.perf_counter() - start_wall
        remaining = float(app_config.min_run_seconds) - float(elapsed)
        if remaining > 0:
            time.sleep(remaining)

    click.echo(
        f"\n=========================\nTous les processus sont terminés. {success_count}/{len(initial_accounts)} succès.\n========================="
    )



@cli.command()
def serve():
    """Démarre le serveur webhook FastAPI."""
    uvicorn.run(
        fastapi_app,
        host=app_config.webhook_host,
        port=app_config.webhook_port,
        log_level=app_config.log_level.lower(),
    )


@cli.command()
def run_telegram():
    """Démarre le bot Telegram."""
    run_telegram_bot()


if __name__ == "__main__":
    cli()
