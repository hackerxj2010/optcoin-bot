from typing import Any, Optional
import asyncio
from pathlib import Path
from playwright.async_api import Page, async_playwright

from optcoin_bot.config import app_config


ANALYTICS_HOST_SUBSTRINGS = {
    "googletagmanager.com",
    "google-analytics.com",
    "www.google-analytics.com",
    "analytics.google.com",
    "doubleclick.net",
    "facebook.net",
    "connect.facebook.net",
    "mixpanel.com",
    "segment.io",
    "cdn.segment.com",
    "hotjar.com",
    "fullstory.com",
    "static.cloudflareinsights.com",
}


class PlaywrightAdapter:
    """Thin wrapper around playwright.async_api to allow DI and fakes in tests."""

    def __init__(self):
        self._pw_cm = None
        self._pw = None

    async def __aenter__(self):
        self._pw_cm = async_playwright()
        self._pw = await self._pw_cm.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._pw_cm:
            await self._pw_cm.__aexit__(exc_type, exc, tb)

    async def launch_browser(self, headless: bool = True):
        args = []
        if getattr(app_config, "low_resource_mode", True):
            try:
                args = list(getattr(app_config, "chromium_launch_args", []))
            except Exception:
                args = []
        return await self._pw.chromium.launch(headless=headless, args=args)

    async def new_context(
        self,
        browser,
        device: Optional[dict] = None,
        performant: bool = False,
        storage_state_path: Optional[str] = None,

    ):
        """
        Create a new browser context with optional device emulation, aggressive
        resource blocking, storage state loading, and default timeouts.
        """
        context_options: dict[str, Any] = {}
        if device:
            context_options.update(device)

        # Ensure a desktop-like viewport and user agent by default to reduce layout differences
        # between headless and headed modes. These defaults can be overridden by `device`.
        if "viewport" not in context_options:
            context_options["viewport"] = {"width": 1280, "height": 800}
        if "user_agent" not in context_options:
            # A common Chrome user agent string to reduce bot-detection and mobile fallbacks
            context_options["user_agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/116.0.0.0 Safari/537.36"
            )

        if storage_state_path:
            try:
                storage_file = Path(storage_state_path)
                if storage_file.exists():
                    context_options["storage_state"] = str(storage_file)
            except Exception:
                pass

        context = await browser.new_context(**context_options)

        try:
            context.set_default_timeout(app_config.default_timeout)
            context.set_default_navigation_timeout(app_config.default_timeout)
        except Exception:
            pass

        # Try to reduce headless/automation detection by web sites by masking webdriver flag
        # This is a best-effort mitigation for invisible/headless mode
        try:
            await context.add_init_script(
                """
                () => {
                    try {
                        Object.defineProperty(navigator, 'webdriver', { get: () => false });
                    } catch (e) {}
                }
                """
            )
        except Exception:
            # Non-fatal if the runtime doesn't support add_init_script
            pass

        if performant:
            async def handle_route(route):
                req = route.request
                url = req.url or ""
                rtype = req.resource_type or ""

                if rtype in {"image", "font", "media"}:
                    return await route.abort()

                lowered = url.lower()
                if any(host in lowered for host in ANALYTICS_HOST_SUBSTRINGS):
                    return await route.abort()

                return await route.continue_()

            await context.route("**/*", handle_route)

        return context

    async def wait_and_screenshot(self, page: Page, path: str, delay: float = 1.0):
        """Waits for a specified delay and then takes a screenshot of the page."""
        await asyncio.sleep(delay)
        await page.screenshot(path=path)
