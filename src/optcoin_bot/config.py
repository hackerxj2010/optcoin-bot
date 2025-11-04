import json
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# Define the project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")

    optcoin_login_url: str = Field(default="https://optcoin66.com/pc/#/login")
    optcoin_base_url: str = Field(default="https://optcoin66.com/pc/")

    optcoin_username: Optional[str] = Field(default=None)
    optcoin_password: Optional[SecretStr] = Field(default=None)

    default_timeout: int = Field(default=30000)  # Réduit pour une exécution plus rapide
    confirm_live_trades: bool = Field(default=True)  # Activé pour la sécurité
    save_debug_html: bool = Field(default=True)  # Activé pour un débogage plus facile
    enforce_min_run_per_execution: bool = Field(default=False)
    enforce_min_run_per_account: bool = Field(default=False)
    min_run_seconds: int = Field(default=0)
    low_resource_mode: bool = Field(default=True)  # Activé pour optimiser les performances
    chromium_launch_args: list[str] = Field(
        default_factory=lambda: [
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-default-browser-check",
            "--no-first-run",
            "--no-zygote",
            "--disable-extensions",
            "--mute-audio",
            "--blink-settings=imagesEnabled=false",
        ]
    )
    storage_state_enabled: bool = Field(default=True)  # Activé pour la mise en cache de session
    storage_state_dir: str = Field(default="storage_states")
    max_concurrent_accounts: int = Field(
        default=2,  # Augmenté pour un meilleur parallélisme
        description="Maximum number of accounts to process concurrently"
    )

    # -- Telegram / Webhook configuration --
    telegram_api_id: int = Field(env="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(env="TELEGRAM_API_HASH")
    telegram_bot_token: SecretStr = Field(env="TELEGRAM_BOT_TOKEN")
    telegram_mode: str = Field(default="headless")

    webhook_host: str = Field(default="0.0.0.0")
    webhook_port: int = Field(default=8000)
    max_run_seconds: int = Field(default=120)  # Réduit pour éviter les exécutions longues

    # -- Selectors --
    selector_login_username_input: str = Field(
        default='input[placeholder="Please enter your email"]',
    )
    selector_login_password_input: str = Field(
        default='input[placeholder="Please enter password"]',
    )
    selector_login_submit_button: str = Field(
        default='button:has-text("LOG IN")',
    )
    selector_login_error_message: str = Field(
        default='div.wrong-msg',  # Sélecteur plus fiable
    )

    selector_nav_delivery_link: str = Field(
        default='span:has-text("Delivery")',
    )

    selector_delivery_invited_me_tab: str = Field(
        default='div.tab:has-text("Invited Me")',
    )
    selector_delivery_order_input: str = Field(
        default='input[placeholder^="Please enter the order"]',  # Sélecteur plus flexible
    )
    selector_delivery_recognize_button: str = Field(
        default='button:has-text("RECOGNIZE")',
    )
    selector_delivery_confirm_button: str = Field(
        default='button:has-text("CONFIRM")',
    )

    selector_info_div: str = Field(
        default='div.info-div',  # Sélecteur plus spécifique
    )


app_config = AppConfig()


class AccountCredentials(BaseModel):
    account_name: str
    username: str
    password: SecretStr


class AccountsConfig(BaseModel):
    accounts: List[AccountCredentials]

def load_accounts_from_json(path: str = "accounts.json") -> AccountsConfig:
    config_path = Path(path)
    if not config_path.exists():
        # Try to resolve from one level above if running from src
        config_path = Path("../") / path
        if not config_path.exists():
            print(f"Warning: Accounts file not found at '{path}' or '{config_path}'. No accounts loaded.")
            return AccountsConfig(accounts=[])

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AccountsConfig(**data)
    except (json.JSONDecodeError, TypeError, KeyError, FileNotFoundError) as e:
        raise ValueError(f"Error parsing accounts file at '{config_path}': {e}")
