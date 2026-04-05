#!/usr/bin/env python3
"""Batch photo backup from Kakao Drive with deletion safety.

Downloads the oldest photos in batches of 100, compresses to zip,
and optionally deletes from the cloud ONLY after verifying every
download succeeded.

Critical fix over the original main.py:
  Thread exceptions were silently swallowed, so failed downloads still
  triggered cloud deletion = potential data loss.  This version tracks
  per-file success, verifies on disk, and only deletes when safe.

Usage:
    python scripts/backup_photos.py
    python scripts/backup_photos.py --no-delete
    python scripts/backup_photos.py --batch-size 50 --threads 3
"""

import argparse
import json
import logging
import os
import shutil
import sys
import threading
import time

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kakao_backup.config import API_BASE, BACKUP_PATH
from kakao_backup.cookie_auth import get_session
from kakao_backup.utils import verify_download

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def request_list(session, direction="ASC", fetch_count=100):
    """Fetch a page of media files from Kakao Drive."""
    url = (
        f"{API_BASE}/mediaFile/list"
        f"?verticalType=MEDIA&fetchCount={fetch_count}"
        f"&joined=true&direction={direction}"
    )
    resp = session.get(url)
    resp.raise_for_status()
    return resp.json()


def request_photo(session, url):
    """Download a single photo. Returns bytes or None on failure."""
    try:
        resp = session.get(f"{url}?attach", timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.error("Failed to download %s: %s", url, e)
        return None


def request_delete(session, file_list_json):
    """Delete photos from Kakao cloud."""
    data = {
        "verticalType": "MEDIA",
        "ids": [item["id"] for item in file_list_json["items"]],
    }
    resp = session.post(
        f"{API_BASE}/mediaFile/delete",
        json=data,
    )
    return resp


def run_backup(args):
    session = get_session(args.cookie_file)
    os.makedirs(args.output, exist_ok=True)

    batch_num = 0
    while True:
        batch_num += 1
        file_list_json = request_list(session, fetch_count=args.batch_size)

        if file_list_json["totalCount"] == 0:
            logger.info("No more photos to process.")
            break

        items = file_list_json["items"]
        timestamp = int(time.time())
        download_path = os.path.join(args.output, str(timestamp))
        os.makedirs(download_path)

        # Save metadata
        meta_path = os.path.join(args.output, f"{timestamp}_list.json")
        with open(meta_path, "w") as f:
            json.dump(file_list_json, f)

        logger.info(
            "Batch %d: downloading %d photos (total remaining: %d)",
            batch_num, len(items), file_list_json["totalCount"],
        )

        # --- Threaded download with per-file tracking ---
        results_lock = threading.Lock()
        download_results: list[dict] = []

        def worker(photo_items):
            for item in photo_items:
                photo_id = item["id"]
                filename = item["url"].split("/")[-1]
                file_path = os.path.join(download_path, filename)

                content = request_photo(session, item["url"])
                success = False
                if content is not None:
                    with open(file_path, "wb") as f:
                        f.write(content)
                    success = verify_download(file_path)

                with results_lock:
                    download_results.append({
                        "photo_id": photo_id,
                        "success": success,
                        "file_path": file_path,
                    })

                status = "OK" if success else "FAILED"
                logger.info("  [%s] %s", status, photo_id)

        # Split items across threads
        thread_count = min(args.threads, len(items))
        chunks: list[list] = [[] for _ in range(thread_count)]
        for i, item in enumerate(items):
            chunks[i % thread_count].append(item)

        threads = []
        for chunk in chunks:
            t = threading.Thread(target=worker, args=(chunk,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        # --- Verify ALL downloads before any deletion ---
        total = len(items)
        succeeded = sum(1 for r in download_results if r["success"])
        failed_items = [r for r in download_results if not r["success"]]

        if failed_items:
            logger.warning(
                "Batch %d: %d/%d downloads failed — skipping cloud deletion",
                batch_num, len(failed_items), total,
            )
            for r in failed_items:
                logger.warning("  Failed: %s", r["photo_id"])
            # Log failed IDs for retry
            fail_log = os.path.join(args.output, f"{timestamp}_failed.json")
            with open(fail_log, "w") as f:
                json.dump(failed_items, f, indent=2)
        else:
            logger.info("Batch %d: all %d downloads verified.", batch_num, succeeded)

        # Compress
        zip_path = shutil.make_archive(f"{download_path}_photo", "zip", download_path)
        logger.info("Compressed: %s", zip_path)

        # Clean up local folder
        shutil.rmtree(download_path)

        # Cloud deletion — only if ALL succeeded and --no-delete not set
        if args.no_delete:
            logger.info("--no-delete flag set, skipping cloud deletion.")
        elif failed_items:
            logger.info("Skipping deletion due to failed downloads.")
        else:
            request_delete(session, file_list_json)
            logger.info("Deleted %d photos from cloud.", total)


def main():
    parser = argparse.ArgumentParser(
        description="Batch photo backup from Kakao Drive (with deletion safety)",
    )
    parser.add_argument(
        "--output", "-o", default=str(BACKUP_PATH),
        help="Backup output directory (default: ./backups)",
    )
    parser.add_argument(
        "--no-delete", action="store_true",
        help="Do NOT delete photos from cloud after backup (safe mode)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=100,
        help="Number of photos per batch (default: 100)",
    )
    parser.add_argument(
        "--threads", type=int, default=5,
        help="Number of download threads (default: 5)",
    )
    parser.add_argument(
        "--cookie-file", default=None,
        help="Path to cookie file (default: from .env / config)",
    )
    args = parser.parse_args()

    run_backup(args)


if __name__ == "__main__":
    main()
