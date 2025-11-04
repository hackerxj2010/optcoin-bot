import asyncio
from typing import List, Dict, Callable, Coroutine, Any

from playwright.async_api import Browser

from optcoin_bot.config import app_config, AccountCredentials, PROJECT_ROOT
from optcoin_bot.playwright_adapter import PlaywrightAdapter
from optcoin_bot.utils.logging import get_logger

logger = get_logger("Orchestrator")


async def orchestrate_accounts(
    accounts: List[AccountCredentials],
    run_for_account: Callable[..., Coroutine[Any, Any, Dict]],
    max_concurrency: int,
    browser: Browser,
    adapter: PlaywrightAdapter,
    **kwargs
) -> List[Dict]:
    limit = max(1, min(int(max_concurrency or 1), 10))
    logger.info(f"Démarrage de l'orchestration pour {len(accounts)} comptes avec une limite de concurrence de {limit}.")

    semaphore = asyncio.Semaphore(limit)
    tasks = []

    async def worker(account: AccountCredentials):
        async with semaphore:
            logger.debug(f"Traitement du compte : {account.account_name}")
            context = None
            try:
                storage_state_path = None
                if app_config.storage_state_enabled:
                    storage_dir = PROJECT_ROOT / app_config.storage_state_dir
                    storage_dir.mkdir(exist_ok=True)
                    storage_state_path = storage_dir / f"{account.account_name}.json"

                context = await adapter.new_context(
                    browser,
                    device=None,
                    performant=kwargs.get("performant", False),
                    storage_state_path=storage_state_path,
                )
                result = await run_for_account(account, browser, adapter, context, **kwargs)
                logger.debug(f"Fin du traitement du compte : {account.account_name}")
                return result
            finally:
                if context:
                    await context.close()

    for account in accounts:
        task = asyncio.create_task(worker(account))
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(f"Orchestration terminée pour {len(accounts)} comptes.")
    return results
