"""Cookie-based authentication for Kakao Drive API (direct HTTP requests)."""

import logging
from pathlib import Path

import requests

from kakao_backup.config import COOKIE_FILE, HEADERS

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/115.0.0.0 Safari/537.36"
)


def parse_cookies(cookie_file: str | Path | None = None) -> dict[str, str]:
    """Parse a Netscape-format cookie file and return Kakao cookies as a dict.

    Args:
        cookie_file: Path to cookie txt file. Defaults to config.COOKIE_FILE.

    Returns:
        Dictionary mapping cookie name -> value.
    """
    path = Path(cookie_file) if cookie_file else COOKIE_FILE

    if not path.exists():
        raise FileNotFoundError(
            f"Cookie file not found: {path}\n"
            "Export cookies from your browser using a cookie export extension."
        )

    cookies: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not (line.startswith("drive.kakao.com") or line.startswith(".kakao.com")):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                name = parts[5].strip()
                value = parts[6].strip()
                cookies[name] = value

    if not cookies:
        logger.warning("No Kakao cookies found in %s", path)

    return cookies


def get_session(cookie_file: str | Path | None = None) -> requests.Session:
    """Return a requests.Session pre-configured with Kakao cookies and headers.

    Args:
        cookie_file: Optional path to cookie file.

    Returns:
        Configured requests.Session.
    """
    cookies = parse_cookies(cookie_file)

    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent": USER_AGENT,
        **HEADERS,
    })
    return session
