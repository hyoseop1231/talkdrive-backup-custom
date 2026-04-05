"""Unified configuration — all credentials and paths from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Kakao API ---
API_BASE = "https://drawer-api.kakao.com"
CDN_BASE = "https://drawer-cdn.kakao.com"
HEADERS = {"Accept": "application/json+javascript"}

# --- Chrome CDP ---
CHROME_DEBUG_PORT = int(os.getenv("CHROME_DEBUG_PORT", "18792"))
CHROME_DEBUG_URL = f"http://localhost:{CHROME_DEBUG_PORT}"

# --- Pagination / download defaults ---
DEFAULT_FETCH_COUNT = 100
DOWNLOAD_THREADS = 5
DOWNLOAD_DELAY = 0.1  # seconds between requests

# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_PATH = Path(os.getenv("BACKUP_PATH", str(PROJECT_ROOT / "backups")))
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
DEFAULT_OUTPUT_DIR = str(DATA_DIR / "media")
COOKIE_FILE = Path(os.getenv("COOKIE_FILE", str(PROJECT_ROOT / "drive.kakao.com_cookies.txt")))

# --- Neo4j ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "")

# --- Kakao user ---
KAKAO_MY_HASHED_ID = os.getenv("KAKAO_MY_HASHED_ID", "")

# --- API endpoints ---
ENDPOINTS = {
    "user_info": "/user/info",
    "friend_list": "/friend/list",
    "chat_list": "/chat/list",
    "backup_info": "/backup/info",
    "chatbot_list": "/chatbot/list",
    "media_list": "/mediaFile/list",
    "media_tags": "/mediaFile/tag/all",
    "label_list": "/label/list",
    "folder_list": "/folder/list",
    "cloud_list": "/v2/cloud/list",
    "contact_snapshot_list": "/contactSnapshot/list",
    "contact_list": "/contact/list",
    "contact_snapshot_detail": "/contactSnapshot",
    "media_friend_latest": "/mediaFile/friend/latest",
    "chat_media": "/chat",
    "notice_cards": "/v3/noticeCard/list",
    "side_web": "/side/web",
}
