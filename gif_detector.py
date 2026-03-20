from __future__ import annotations

import re
from urllib.parse import urlparse

import discord


URL_REGEX = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)

GIF_HOST_KEYWORDS = (
    "tenor.com",
    "giphy.com",
    "media.giphy.com",
    "i.giphy.com",
)


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return URL_REGEX.findall(text)


def is_gif_url(url: str) -> bool:
    lowered = url.lower()

    if lowered.endswith(".gif"):
        return True

    parsed = urlparse(lowered)
    netloc = parsed.netloc

    return any(host in netloc for host in GIF_HOST_KEYWORDS)


def attachment_is_gif(attachment: discord.Attachment) -> bool:
    name = (attachment.filename or "").lower()
    content_type = (attachment.content_type or "").lower()

    if name.endswith(".gif"):
        return True

    if content_type == "image/gif":
        return True

    return False


def embed_looks_like_gif(embed: discord.Embed) -> bool:
    possible_urls = []

    if embed.url:
        possible_urls.append(embed.url)
    if embed.thumbnail and embed.thumbnail.url:
        possible_urls.append(embed.thumbnail.url)
    if embed.image and embed.image.url:
        possible_urls.append(embed.image.url)

    return any(is_gif_url(url) for url in possible_urls)


def message_contains_gif(message: discord.Message) -> bool:
    for attachment in message.attachments:
        if attachment_is_gif(attachment):
            return True

    for url in extract_urls(message.content):
        if is_gif_url(url):
            return True

    for embed in message.embeds:
        if embed_looks_like_gif(embed):
            return True

    return False