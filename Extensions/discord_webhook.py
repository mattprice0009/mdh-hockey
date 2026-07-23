"""Small Discord incoming-webhook client for extension announcements."""

from __future__ import annotations

from typing import Any

import requests

from mdhhockey.helpers import DISCORD_WEBHOOK_URL

DISCORD_CONTENT_LIMIT = 2_000

class DiscordWebhookError(RuntimeError):
    """The announcement cannot be sent through a Discord webhook."""

def post_to_discord(
    content: str,
    *,
    timeout: float = 30,
) -> dict[str, Any]:
    """Post content and return Discord's created-message response."""
    if not DISCORD_WEBHOOK_URL.strip():
        raise DiscordWebhookError("Discord webhook URL is not configured.")
    if not content.strip():
        raise DiscordWebhookError("Discord webhook content cannot be empty.")
    if len(content) > DISCORD_CONTENT_LIMIT:
        raise DiscordWebhookError(
            f"Discord webhook content exceeds {DISCORD_CONTENT_LIMIT} characters."
        )

    response = requests.post(
        DISCORD_WEBHOOK_URL,
        params={"wait": "true"},
        json={"content": content},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
