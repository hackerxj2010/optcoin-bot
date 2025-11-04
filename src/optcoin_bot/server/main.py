from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request, BackgroundTasks, Response
from twilio.twiml.messaging_response import MessagingResponse

from optcoin_bot.actions import get_accounts_to_process, run_submit_order_for_account
from optcoin_bot.config import app_config
from optcoin_bot.orchestrator import orchestrate_accounts
from optcoin_bot.playwright_adapter import PlaywrightAdapter
from optcoin_bot.utils.logging import get_logger

logger = get_logger("WebhookServer")


async def run_trade_task(order_number: str, dry_run: bool = False):
    logger.info(f"Background task started for order: {order_number}")
    accounts_to_process = get_accounts_to_process()
    if not accounts_to_process:
        logger.warning("No accounts found for background task.")
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
                order_number=order_number,
                dry_run=dry_run,
                headless=True,
                performant=True,
                skip_history_verification=False,
            )
            await browser.close()
        logger.info(f"Background task finished for order: {order_number}", results=results)
    except Exception as e:
        logger.error(f"Error during background task for order {order_number}: {e}", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting FastAPI server",
        host=app_config.webhook_host,
        port=app_config.webhook_port,
    )
    yield


app = FastAPI(
    title="OPTCOIN Trading Bot Webhook Server",
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/whatsapp")
async def handle_whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    From: Optional[str] = Form(None),
    Body: Optional[str] = Form(None),
):
    client_host = request.client.host
    logger.info(
        "Received incoming message", source_ip=client_host, sender=From, body=Body
    )
    response = MessagingResponse()

    if not From or not Body:
        logger.warning("Received a request with missing From or Body fields.")
        raise HTTPException(status_code=400, detail="Missing 'From' or 'Body' fields")

    parts = Body.strip().lower().split()
    if len(parts) == 2 and parts[0] == "copy":
        order_number = parts[1]

        logger.info(f"Valid command received. Starting background task for order {order_number}.")

        background_tasks.add_task(run_trade_task, order_number=order_number, dry_run=False)

        response.message(f"✅ Ordre `{order_number}` reçu. Le processus de copy trading est en cours. Un rapport sera envoyé à la fin.")
    else:
        logger.warning(f"Invalid command format received: '{Body}'")
        response.message("❌ Commande invalide. Utilisation : copy <ID_ordre>")

    return Response(content=str(response), media_type="application/xml")


@app.get("/health")
def health_check():
    return {"status": "ok"}
