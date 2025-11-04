import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from pydantic import SecretStr
from playwright.async_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from optcoin_bot.config import app_config
from optcoin_bot.utils.logging import get_logger
from optcoin_bot.utils.retry import async_retry


class OptcoinWorkflow:
    """Gère et exécute le processus de copy trading d'OPTCOIN."""

    def __init__(
        self,
        username: str,
        password: SecretStr,
        browser_context: Optional[BrowserContext] = None,
        storage_state_path: Optional[str] = None,
        page: Optional[Page] = None,
    ):
        self.username = username
        self.password = password
        self.logger = get_logger("OptcoinWorkflow", account_name=self.username)
        self.browser_context = browser_context
        self.storage_state_path = storage_state_path
        self.page = page
        self._last_alert_message: Optional[str] = None

    async def execute_login(self, dry_run: bool = True) -> Dict[str, Any]:
        self.logger.info("Démarrage du processus de connexion", dry_run=dry_run)

        start_time = datetime.utcnow()
        report = {
            "account_name": self.username,
            "dry_run": dry_run,
            "start_time_utc": start_time.isoformat(),
            "steps": [],
            "success": False,
        }

        try:
            if not self.browser_context:
                raise Exception("BrowserContext non fourni au processus.")

            if not self.page:
                self.page = await self.browser_context.new_page()

            login_result = await self._step_login(self.page, dry_run)
            report["steps"].append(login_result)
            if not login_result.get("success", False):
                raise Exception(f"L'étape 'login' a échoué : {login_result.get('error')}")

            report["success"] = True
            self.logger.info("Processus de connexion terminé avec succès.")

        except Exception as e:
            report["error"] = str(e)
            self.logger.error("Le processus de connexion a échoué", error=str(e))

        finally:
            pass

        end_time = datetime.utcnow()
        elapsed = (end_time - start_time).total_seconds()

        if app_config.enforce_min_run_per_account:
            remaining = max(0.0, float(app_config.min_run_seconds) - float(elapsed))
            if remaining > 0:
                await asyncio.sleep(remaining)
                end_time = datetime.utcnow()
                elapsed = (end_time - start_time).total_seconds()

        report["end_time_utc"] = end_time.isoformat()
        report["duration_seconds"] = elapsed

        return report

    async def execute_submit_order(
        self,
        order_number: str,
        dry_run: bool = True,
        headless: bool = True,
        performant: bool = False,
        skip_history_verification: bool = False,
    ) -> Dict[str, Any]:
        self.logger.info(
            "Démarrage du processus de soumission d'ordre",
            order_number=order_number,
            dry_run=dry_run,
            performant=performant,
            skip_history_verification=skip_history_verification,
        )

        start_time = datetime.utcnow()
        report = {
            "account_name": self.username,
            "order_number": order_number,
            "dry_run": dry_run,
            "start_time_utc": start_time.isoformat(),
            "steps": [],
            "success": False,
        }

        try:
            if dry_run:
                self.logger.info("Exécution en mode test (dry run) pour la soumission d'ordre.")
                report["steps"] = []
                report["success"] = True
                self.logger.info("Mode test (dry run) terminé avec succès.")
            else:
                if not self.browser_context:
                    raise Exception("BrowserContext non fourni pour l'exécution réelle.")

                if not self.page:
                    self.page = await self.browser_context.new_page()

                steps_to_execute = [
                    self._step_login,
                    self._step_navigate_to_delivery,
                    self._step_click_invited_me,
                    lambda p, dr: self._step_enter_order_and_recognize(p, order_number, dr),
                    self._step_confirm_order,
                ]

                for step_func in steps_to_execute:
                    result = await step_func(self.page, dry_run)
                    report["steps"].append(result)
                    if not result.get("success", False):
                        raise Exception(f"L'étape '{result.get('step')}' a échoué : {result.get('error')}")

                report["success"] = True
                self.logger.info("Processus d'exécution réelle terminé avec succès.")

        except Exception as e:
            report["error"] = str(e)
        finally:
            end_time = datetime.utcnow()
            elapsed = (end_time - start_time).total_seconds()

            if app_config.enforce_min_run_per_account:
                remaining = max(0.0, float(app_config.min_run_seconds) - float(elapsed))
                if remaining > 0:
                    await asyncio.sleep(remaining)
                    end_time = datetime.utcnow()
                    elapsed = (end_time - start_time).total_seconds()

            report["end_time_utc"] = end_time.isoformat()
            report["duration_seconds"] = elapsed
            self.logger.info(f"Rapport final de execute_submit_order: {report}")
        return report

    async def _capture_alert_message(self, page: Page, timeout: int = 5000) -> Optional[str]:
        try:
            dialog = await page.wait_for_event("dialog", timeout=timeout)
            msg = dialog.message
            await dialog.accept()
            if msg:
                self._last_alert_message = msg
                return msg
        except PlaywrightTimeoutError:
            pass
        try:
            alerts = await page.query_selector_all('[role="alert"]')
            for a in alerts:
                if await a.is_visible():
                    txt = await a.text_content()
                    if txt and txt.strip():
                        self._last_alert_message = txt.strip()
                        return txt.strip()
        except Exception:
            pass
        try:
            err_loc = page.locator(app_config.selector_login_error_message)
            if await err_loc.is_visible(timeout=500):
                txt = await err_loc.text_content()
                if txt and txt.strip():
                    self._last_alert_message = txt.strip()
                    return txt.strip()
        except Exception:
            pass
        return None

    @async_retry(max_attempts=3)
    async def _step_login(self, page: Page, dry_run: bool) -> Dict[str, Any]:
        self.logger.info("Exécution de l'étape : Connexion standard")
        if dry_run:
            return {"step": "login", "success": True, "simulated": True}

        try:
            if self.storage_state_path and Path(self.storage_state_path).exists():
                self.logger.info("Fichier de session existant trouvé. Validation de la session.")
                await page.goto(f"{app_config.optcoin_base_url}#/delivery", timeout=app_config.default_timeout)
                try:
                    await page.wait_for_url(lambda url: "/login" in url, timeout=5000)
                    self.logger.warning("Session expirée. Redirigé vers la page de connexion. Ré-authentification.")
                    try:
                        Path(self.storage_state_path).unlink()
                        self.logger.info(f"Fichier de session expiré supprimé : {self.storage_state_path}")
                    except Exception as e:
                        self.logger.error(f"Échec de la suppression du fichier de session : {e}")
                except PlaywrightTimeoutError:
                    try:
                        await page.locator(app_config.selector_delivery_invited_me_tab).first.wait_for(state="visible", timeout=1000)
                        self.logger.info("La session est toujours valide.")
                        return {"step": "login", "success": True, "cached": True}
                    except PlaywrightTimeoutError:
                        self.logger.warning("Session expirée. Élément non trouvé sur la page de livraison. Ré-authentification.")
                        try:
                            Path(self.storage_state_path).unlink()
                            self.logger.info(f"Fichier de session expiré supprimé : {self.storage_state_path}")
                        except Exception as e:
                            self.logger.error(f"Échec de la suppression du fichier de session : {e}")

            self.logger.info(f"Navigation directe vers la page de connexion : {app_config.optcoin_login_url}")
            await page.goto(app_config.optcoin_login_url, timeout=app_config.default_timeout)
            await page.locator(app_config.selector_login_username_input).wait_for(timeout=app_config.default_timeout)
            self.logger.info("Le formulaire de connexion est visible.")
            await page.locator(app_config.selector_login_username_input).fill(self.username)
            await page.locator(app_config.selector_login_password_input).fill(self.password.get_secret_value())
            await page.locator(app_config.selector_login_submit_button).click()
            await page.wait_for_url(lambda url: "/login" not in url.lower(), timeout=app_config.default_timeout)
            if self.browser_context and self.storage_state_path:
                await self.browser_context.storage_state(path=self.storage_state_path)
                self.logger.info(f"État de la session sauvegardé dans {self.storage_state_path}")
            self.logger.info("Connexion réussie.")
            return {"step": "login", "success": True}
        except Exception as e:
            error_msg = f"Échec de la connexion : {e}"
            self.logger.error(error_msg)
            return {"step": "login", "success": False, "error": error_msg}

    @async_retry(max_attempts=3)
    async def _step_navigate_to_delivery(self, page: Page, dry_run: bool) -> Dict[str, Any]:
        self.logger.info("Exécution de l'étape : Navigation vers la livraison")
        if dry_run:
            return {"step": "navigate_to_delivery", "success": True, "simulated": True}
        try:
            delivery_url = f"{app_config.optcoin_base_url}#/delivery"
            await page.goto(delivery_url, timeout=app_config.default_timeout, wait_until="domcontentloaded")
            await page.locator(app_config.selector_delivery_invited_me_tab).first.wait_for(state="visible", timeout=app_config.default_timeout)
            self.logger.info("Navigation vers la page de livraison réussie.")
            return {"step": "navigate_to_delivery", "success": True}
        except PlaywrightTimeoutError as e:
            error_msg = f"Délai d'attente dépassé lors de la navigation vers la page de livraison : {e}"
            self.logger.error(f"{error_msg} URL actuelle : {page.url}")
            return {"step": "navigate_to_delivery", "success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"Erreur inattendue lors de la navigation vers la page de livraison : {e}"
            self.logger.error(f"{error_msg} URL actuelle : {page.url}", exc_info=True)
            return {"step": "navigate_to_delivery", "success": False, "error": error_msg}

    @async_retry(max_attempts=3)
    async def _step_click_invited_me(self, page: Page, dry_run: bool) -> Dict[str, Any]:
        self.logger.info("Exécution de l'étape : Clic sur l'onglet 'Invited Me'")
        if dry_run:
            return {"step": "click_invited_me", "success": True, "simulated": True}
        try:
            await page.locator(app_config.selector_delivery_invited_me_tab).first.click(timeout=app_config.default_timeout)
            await page.wait_for_timeout(1000)
            self.logger.info("Clic sur l'onglet 'Invited Me' réussi.")
            return {"step": "click_invited_me", "success": True}
        except PlaywrightTimeoutError as e:
            error_msg = f"Délai d'attente dépassé en cliquant sur l'onglet 'Invited Me' : {e}"
            self.logger.error(f"{error_msg} URL actuelle : {page.url}")
            return {"step": "click_invited_me", "success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"Erreur inattendue en cliquant sur l'onglet 'Invited Me' : {e}"
            self.logger.error(f"{error_msg} URL actuelle : {page.url}", exc_info=True)
            return {"step": "click_invited_me", "success": False, "error": error_msg}

    @async_retry(max_attempts=3)
    async def _step_enter_order_and_recognize(self, page: Page, order_number: str, dry_run: bool) -> Dict[str, Any]:
        self.logger.info("Exécution de l'étape : Saisir l'ordre et Reconnaître")
        if dry_run:
            return {"step": "enter_order_and_recognize", "success": True, "simulated": True, "order_number": order_number}
        try:
            if "/login" in page.url.lower():
                return {"step": "enter_order_and_recognize", "success": False, "error": "Redirigé vers la page de connexion - la session a peut-être expiré"}
            await page.locator(app_config.selector_delivery_order_input).fill(order_number)
            await page.locator(app_config.selector_delivery_recognize_button).click()
            recognize_alert = await self._capture_alert_message(page, timeout=3000)
            if recognize_alert:
                msg_lower = (recognize_alert or "").lower()
                if any(phrase in msg_lower for phrase in ["already followed", "already", "suivi", "followed", "已跟", "跟单", "已关注", "已跟随", "跟随"]):
                    self.logger.info(f"Reconnaissance a retourné un message informatif traité comme un succès : {recognize_alert}")
                    return {"step": "enter_order_and_recognize", "success": True, "order_number": order_number, "alert_message": recognize_alert}
                if any(error_phrase in msg_lower for error_phrase in ["invalid", "not found", "error", "incorrect", "not exist", "invalide", "non trouvé", "erreur"]):
                    return {"step": "enter_order_and_recognize", "success": False, "error": f"Code d'ordre invalide : {recognize_alert}", "alert_message": recognize_alert}
                return {"step": "enter_order_and_recognize", "success": False, "error": f"La reconnaissance a échoué : {recognize_alert}", "alert_message": recognize_alert}
            try:
                await page.locator(app_config.selector_delivery_confirm_button).wait_for(state="visible", timeout=8000)
                self.logger.info("Bouton de confirmation apparu - reconnaissance de l'ordre réussie.")
                return {"step": "enter_order_and_recognize", "success": True, "order_number": order_number}
            except PlaywrightTimeoutError:
                if "/login" in page.url.lower():
                    return {"step": "enter_order_and_recognize", "success": False, "error": "Redirigé vers la page de connexion après la tentative de reconnaissance - session expirée ou bloquée"}
                return {"step": "enter_order_and_recognize", "success": False, "error": "Le bouton de confirmation n'est pas apparu après la reconnaissance - l'ordre est probablement invalide"}
        except PlaywrightTimeoutError as e:
            error_msg = f"Délai d'attente dépassé lors de la saisie ou de la reconnaissance de l'ordre : {e}"
            if "/login" in page.url.lower():
                error_msg += " - Redirigé vers la page de connexion pendant l'opération"
            self.logger.error(f"{error_msg} URL actuelle : {page.url}")
            return {"step": "enter_order_and_recognize", "success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"Erreur inattendue lors de la saisie ou de la reconnaissance de l'ordre : {e}"
            if "/login" in page.url.lower():
                error_msg += " - Redirigé vers la page de connexion pendant l'opération"
            self.logger.error(f"{error_msg} URL actuelle : {page.url}", exc_info=True)
            return {"step": "enter_order_and_recognize", "success": False, "error": error_msg}

    @async_retry(max_attempts=3)
    async def _step_confirm_order(self, page: Page, dry_run: bool) -> Dict[str, Any]:
        self.logger.info("Exécution de l'étape : Confirmer l'ordre")
        if dry_run:
            return {"step": "confirm_order", "success": True, "simulated": True}
        try:
            await page.locator(app_config.selector_delivery_confirm_button).wait_for(state="visible", timeout=app_config.default_timeout)
            await page.locator(app_config.selector_delivery_confirm_button).click()
            confirm_alert = await self._capture_alert_message(page, timeout=800)
            if confirm_alert:
                msg_lower = (confirm_alert or "").lower()
                if "already followed the order" in msg_lower or ("already" in msg_lower and any(term in msg_lower for term in ["follow", "followed", "follow this", "已跟", "跟单", "已关注", "已跟随", "跟随"])):
                    self.logger.info(f"Confirmation a retourné un message informatif traité comme un succès : {confirm_alert}")
                    return {"step": "confirm_order", "success": True, "alert_message": confirm_alert}
                
                error_message = f"La confirmation a retourné une alerte : {confirm_alert}"
                if "Invalid parameter" in confirm_alert:
                    error_message = "Paramètre invalide détecté lors de la confirmation. Le numéro d'ordre est probablement expiré ou incorrect."

                return {
                    "step": "confirm_order",
                    "success": False,
                    "error": error_message,
                    "alert_message": confirm_alert,
                }
            await page.wait_for_timeout(1000)
            self.logger.info("Ordre confirmé avec succès.")
            return {"step": "confirm_order", "success": True}
        except PlaywrightTimeoutError as e:
            error_msg = f"Délai d'attente dépassé lors de la confirmation de l'ordre : {e}"
            self.logger.error(f"{error_msg} URL actuelle : {page.url}")
            return {"step": "confirm_order", "success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"Erreur inattendue lors de la confirmation de l'ordre : {e}"
            self.logger.error(f"{error_msg} URL actuelle : {page.url}", exc_info=True)
            return {"step": "confirm_order", "success": False, "error": error_msg}