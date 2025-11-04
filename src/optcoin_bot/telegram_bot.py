import asyncio
import re

from telethon import TelegramClient, events

from optcoin_bot.actions import get_accounts_to_process, run_submit_order_for_account
from optcoin_bot.config import app_config
from optcoin_bot.orchestrator import orchestrate_accounts
from optcoin_bot.playwright_adapter import PlaywrightAdapter
from optcoin_bot.utils.logging import get_logger

logger = get_logger("TelethonBot")


def format_error_message(error: str) -> str:
    """Provides a more descriptive error message for common issues."""
    if "Invalid parameter" in error:
        return "Le site a rejeté l'ordre (paramètre invalide). L'identifiant de l'ordre est probablement expiré ou incorrect."
    if "Timeout" in error:
        return "Le site n'a pas répondu à temps. Cela peut être dû à une lenteur du réseau ou du site."
    if "Redirected to login page" in error:
        return "La session a expiré de manière inattendue. Le bot tentera de se reconnecter au prochain cycle."
    return error


async def run_trade_task(order_number: str, event: events.NewMessage.Event):
    """
    The actual long-running task that is executed in the background.
    Sends a message back to the user upon completion or failure.
    """
    logger.info(f"Telethon background task started for order: {order_number}")
    await event.respond(f"🚀 **Lancement du copy trading pour l'ordre `{order_number}`...**\n\nTraitement des comptes en cours, veuillez patienter.")

    accounts_to_process = get_accounts_to_process()
    if not accounts_to_process:
        logger.warning("No accounts found for background task.")
        await event.respond("⚠️ **Aucun compte n'a été trouvé.**\n\nVeuillez configurer le fichier `accounts.json`.")
        return

    try:
        async with PlaywrightAdapter() as adapter:
            browser = await adapter.launch_browser(headless=True)
            results = await orchestrate_accounts(
                accounts=accounts_to_process,
                run_for_account=run_submit_order_for_account,
                max_concurrency=app_config.max_concurrent_accounts,
                browser=browser,
                adapter=adapter,
                telethon_client=event.client,
                chat_id=event.chat_id,
                order_number=order_number,
                dry_run=False,
                headless=True,
                performant=True,
                skip_history_verification=True,
            )
            await browser.close()

        success_count = 0
        failure_count = 0
        account_summaries = []

        for report in results:
            if isinstance(report, dict):
                account_name = report.get("account_name", "Unknown Account")
                if report.get("success"):
                    success_count += 1
                    toast_message = report.get("toast_message")
                    if toast_message:
                        account_summaries.append(f"✅ **{account_name}:** SUCCÈS\n   - _Message: {toast_message}_")
                    else:
                        account_summaries.append(f"✅ **{account_name}:** SUCCÈS")
                else:
                    failure_count += 1
                    error_msg = report.get("error", "Erreur inconnue")
                    formatted_error = format_error_message(error_msg)
                    account_summaries.append(f"❌ **{account_name}:** ÉCHEC\n   - _Raison: {formatted_error}_")
            else:  # An unexpected exception was returned by gather
                failure_count += 1
                account_summaries.append(f"🚨 **ERREUR INATTENDUE:**\n   - _{str(report)}_")

        summary_header = f"📋 **Rapport d'exécution pour l'ordre `{order_number}`**\n\n"
        summary_counts = f"**Succès:** {success_count} | **Échecs:** {failure_count}\n\n"
        final_summary = summary_header + summary_counts + "\n".join(account_summaries)

        logger.info(f"Background task finished for order: {order_number}", results=results)
        await event.respond(final_summary)

    except Exception as e:
        logger.error(f"Error during Telethon background task for order {order_number}: {e}", exc_info=True)
        await event.respond(f"🆘 **Erreur critique lors du traitement de l'ordre `{order_number}`.**\n\nConsultez les logs pour plus de détails.")


def run_bot():
    """Starts the Telegram bot using Telethon."""
    if not all([app_config.telegram_api_id, app_config.telegram_api_hash, app_config.telegram_bot_token]):
        raise ValueError("Telegram API ID, Hash, and Bot Token must be configured in .env file.")

    bot = TelegramClient(
        'bot',
        app_config.telegram_api_id,
        app_config.telegram_api_hash
    ).start(bot_token=app_config.telegram_bot_token.get_secret_value())

    @bot.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        sender = await event.get_sender()
        gif_url = "https://media.tenor.com/2hA5tZ9eAOMAAAAC/crypto-arbitrage-bot-trading-bot.gif"
        
        caption = f"""
**✨ Assistant de Trading OPTCOIN ✨**

Bonjour, {sender.first_name}. Je suis votre assistant personnel pour le copy trading sur OPTCOIN.

**Mes fonctionnalités :**
- **Exécution Automatisée :** Je place vos ordres de copy trading de manière rapide et fiable.
- **Rapports en Temps Réel :** Vous recevez un rapport détaillé après chaque exécution.
- **Haute Performance :** Conçu pour une efficacité maximale.

**Commandes :**
- `/copy <ID_ordre>` : Exécute un ordre de copy trading.
- `/help` : Affiche ce message.

**Pour commencer :**
Envoyez `/copy` suivi de l'identifiant de l'ordre. Exemple :
`/copy 12345`
"""
        
        await event.respond(file=gif_url, message=caption)

    @bot.on(events.NewMessage(pattern=re.compile(r'/copy(?:\s+)(\S+)')))
    async def copy_handler(event):
        try:
            order_number = event.pattern_match.group(1)
            logger.info(f"Received /copy command for order: {order_number} from user: {event.sender_id}")
            await event.respond(f"✅ Ordre `{order_number}` reçu. Lancement du processus de copy trading...")
            asyncio.create_task(run_trade_task(order_number, event))
        except (IndexError, ValueError):
            await event.respond("❌ Commande invalide. Utilisation : /copy <ID_ordre>")

    logger.info("Telethon bot is starting...")
    bot.run_until_disconnected()
    logger.info("Telethon bot stopped.")


if __name__ == "__main__":
    run_bot()
