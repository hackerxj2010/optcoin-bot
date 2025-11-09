from typing import Optional
from playwright.async_api import Browser, BrowserContext
from telethon import TelegramClient

from optcoin_bot.config import app_config, load_accounts_from_json, AccountCredentials, PROJECT_ROOT
from optcoin_bot.core.workflow import OptcoinWorkflow
from optcoin_bot.utils.logging import get_logger

logger = get_logger("Actions")


def get_accounts_to_process(accounts_file: str = "accounts.json") -> list[AccountCredentials]:
    """Charge les comptes à partir du fichier JSON ou utilise les informations d'identification de l'environnement."""
    accounts_config = load_accounts_from_json(accounts_file)
    if accounts_config.accounts:
        return accounts_config.accounts

    if app_config.optcoin_username and app_config.optcoin_password:
        return [
            AccountCredentials(
                account_name="default_account",
                username=app_config.optcoin_username,
                password=app_config.optcoin_password,
            )
        ]
    return []


async def run_login_for_account(account: AccountCredentials, browser: Browser, adapter, context: BrowserContext, **kwargs):
    logger.info(f"Tentative de connexion pour le compte : {account.account_name}")

    storage_state_path = None
    if app_config.storage_state_enabled:
        storage_dir = PROJECT_ROOT / app_config.storage_state_dir
        storage_dir.mkdir(exist_ok=True)
        storage_state_path = storage_dir / f"{account.account_name}.json"

    page = None
    try:
        page = await context.new_page()
        workflow = OptcoinWorkflow(
            username=account.username,
            password=account.password,
            browser_context=context,
            storage_state_path=storage_state_path,
            page=page,
        )
        return await workflow.execute_login(dry_run=kwargs.get("dry_run", True))
    finally:
        if page and not page.is_closed():
            await page.close()


async def run_submit_order_for_account(
    account: AccountCredentials, 
    browser: Browser, 
    adapter, 
    context: BrowserContext,
    telethon_client: Optional[TelegramClient] = None, 
    chat_id: Optional[int] = None, 
    **kwargs
):
    logger.info(f"Tentative de soumission d'ordre pour le compte : {account.account_name}")

    storage_state_path = None
    if app_config.storage_state_enabled:
        storage_dir = PROJECT_ROOT / app_config.storage_state_dir
        storage_dir.mkdir(exist_ok=True)
        storage_state_path = storage_dir / f"{account.account_name}.json"

    page = None
    try:
        page = await context.new_page()
        workflow = OptcoinWorkflow(
            username=account.username,
            password=account.password,
            browser_context=context,
            storage_state_path=storage_state_path,
            page=page,
        )
        report = await workflow.execute_submit_order(**kwargs)
        if not report.get("success"):
            error_message = report.get("error", "Erreur inconnue lors de l'exécution du workflow.")
            logger.warning(f"Le workflow a échoué pour {account.account_name}: {error_message}")
            if telethon_client and chat_id:
                await telethon_client.send_message(chat_id, f"🔴 ÉCHEC pour le compte {account.account_name}: {error_message}")
        return report
    except Exception as e:
        logger.error(f"Erreur critique dans le workflow pour le compte {account.account_name}: {e}", exc_info=True)
        if telethon_client and chat_id:
            await telethon_client.send_message(chat_id, f"🔴 ERREUR CRITIQUE pour le compte {account.account_name}: {e}")
        return {
            "account_name": account.account_name,
            "success": False,
            "error": str(e),
        }
    finally:
        if page and not page.is_closed():
            await page.close()
