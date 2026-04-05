#!/usr/bin/env python3
"""Resume-capable media file downloader for Kakao TalkCloud.

Downloads media files organized by chatroom folder, with state persistence
so interrupted downloads can be resumed.

Supports two modes:
  browser  - Downloads via CDP (uses browser cookies automatically)
  direct   - Downloads via requests (extracts cookies from browser first)

Usage:
    python scripts/download_media.py
    python scripts/download_media.py --output ~/NAS/kakao-media --threads 10
    python scripts/download_media.py --dry-run
    python scripts/download_media.py --method direct --limit 500
"""

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kakao_backup.cdp_client import TalkCloudClient
from kakao_backup.config import DEFAULT_OUTPUT_DIR, DOWNLOAD_THREADS
from kakao_backup.utils import (
    load_state,
    sanitize_dirname,
    sanitize_filename,
    save_state,
)


def download_single_file(item: dict, output_dir: str, cookies: dict,
                         state: dict) -> tuple[str, bool, str]:
    """Download a single file using requests (direct mode).

    Returns:
        (file_id, success, message)
    """
    import requests

    file_id = str(item.get("id", ""))
    url = item.get("url", "")

    if not url:
        return file_id, False, "No URL"

    if file_id in state.get("downloaded", {}):
        return file_id, True, "Already downloaded"

    # Chatroom folder
    chat_title = item.get("chatTitle", "") or item.get("title", "")
    chat_id = item.get("hashedChatId", "unknown")
    folder_name = sanitize_dirname(f"{chat_title}_{chat_id[:8]}" if chat_title else chat_id[:16])
    folder_path = os.path.join(output_dir, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    # File name
    original_name = item.get("fileName", "")
    if not original_name:
        parsed = urlparse(url)
        original_name = os.path.basename(parsed.path)
    if not original_name:
        original_name = f"{file_id}.jpg"
    original_name = sanitize_filename(original_name)

    file_path = os.path.join(folder_path, f"{file_id}_{original_name}")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_id, True, f"File exists ({os.path.getsize(file_path)} bytes)"

    download_url = f"{url}?attach" if "?" not in url else f"{url}&attach=true"

    try:
        resp = requests.get(download_url, cookies=cookies, headers={"Accept": "*/*"},
                            timeout=60, stream=True)
        resp.raise_for_status()
        with open(file_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        size = os.path.getsize(file_path)
        return file_id, True, f"Downloaded ({size:,} bytes)"
    except Exception as e:
        if os.path.exists(file_path) and os.path.getsize(file_path) == 0:
            os.remove(file_path)
        return file_id, False, str(e)


async def download_with_browser(client: TalkCloudClient, item: dict,
                                output_dir: str) -> tuple[str, bool, str]:
    """Download a file through the browser session (CDP fetch)."""
    file_id = str(item.get("id", ""))
    url = item.get("url", "")

    if not url:
        return file_id, False, "No URL"

    download_url = f"{url}?attach" if "?" not in url else f"{url}&attach=true"

    chat_title = item.get("chatTitle", "") or item.get("title", "")
    chat_id = item.get("hashedChatId", "unknown")
    folder_name = sanitize_dirname(f"{chat_title}_{chat_id[:8]}" if chat_title else chat_id[:16])
    folder_path = os.path.join(output_dir, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    original_name = (
        item.get("fileName", "")
        or os.path.basename(urlparse(url).path)
        or f"{file_id}.jpg"
    )
    original_name = sanitize_filename(original_name)
    file_path = os.path.join(folder_path, f"{file_id}_{original_name}")

    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        return file_id, True, "File exists"

    try:
        b64_data = await client._evaluate(f"""
            (async () => {{
                const resp = await fetch('{download_url}', {{credentials: 'include'}});
                const blob = await resp.blob();
                return new Promise((resolve) => {{
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result.split(',')[1]);
                    reader.readAsDataURL(blob);
                }});
            }})()
        """)
        if b64_data:
            data = base64.b64decode(b64_data)
            with open(file_path, "wb") as f:
                f.write(data)
            return file_id, True, f"Downloaded ({len(data):,} bytes)"
        return file_id, False, "Empty response"
    except Exception as e:
        return file_id, False, str(e)


async def run(args):
    output_dir = os.path.expanduser(args.output)
    os.makedirs(output_dir, exist_ok=True)

    state = load_state(output_dir)

    client = TalkCloudClient()
    await client.connect()

    try:
        # Collect media list
        print("Collecting media file list...")
        all_items = await client.get_all_media()
        if not all_items:
            print("No media files found.")
            return

        list_path = os.path.join(output_dir, "media_list.json")
        with open(list_path, "w", encoding="utf-8") as f:
            json.dump(all_items, f, ensure_ascii=False, indent=2)
        print(f"Media list saved: {list_path} ({len(all_items)} files)")

        if args.dry_run:
            print(f"\nDry run complete. {len(all_items)} files found.")
            return

        # Filter already-downloaded
        to_download = [
            item for item in all_items
            if str(item.get("id", "")) not in state.get("downloaded", {})
        ]
        if args.limit > 0:
            to_download = to_download[:args.limit]

        already = len(all_items) - len(to_download)
        print(f"\nDownload plan:")
        print(f"   Total: {len(all_items)}, Already done: {already}, To download: {len(to_download)}")
        print(f"   Method: {args.method}, Output: {output_dir}")

        if not to_download:
            print("\nAll files already downloaded!")
            return

        if not state.get("started_at"):
            state["started_at"] = datetime.now().isoformat()
        state["total"] = len(all_items)

        success = 0
        failed = 0
        start_time = time.time()

        if args.method == "browser":
            for i, item in enumerate(to_download, 1):
                file_id, ok, msg = await download_with_browser(client, item, output_dir)
                if ok:
                    success += 1
                    state["downloaded"][file_id] = {"path": msg, "timestamp": datetime.now().isoformat()}
                else:
                    failed += 1
                    state["failed"].append({"id": file_id, "error": msg})

                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(to_download) - i) / rate if rate > 0 else 0
                status = "OK" if ok else "FAIL"
                print(f"  [{i}/{len(to_download)}] {status} {file_id}: {msg} ({rate:.1f}/s, ETA: {eta:.0f}s)")

                if i % 10 == 0:
                    save_state(output_dir, state)
                await asyncio.sleep(0.1)
        else:
            # Direct mode — extract cookies from browser first
            print("Extracting cookies from browser for direct download...")
            cookies_str = await client._evaluate("document.cookie")
            cookies = {}
            if cookies_str:
                for part in cookies_str.split(";"):
                    if "=" in part:
                        k, v = part.strip().split("=", 1)
                        cookies[k] = v

            with ThreadPoolExecutor(max_workers=args.threads) as executor:
                futures = {
                    executor.submit(download_single_file, item, output_dir, cookies, state): item
                    for item in to_download
                }
                for i, future in enumerate(as_completed(futures), 1):
                    file_id, ok, msg = future.result()
                    if ok:
                        success += 1
                        state["downloaded"][file_id] = {"timestamp": datetime.now().isoformat()}
                    else:
                        failed += 1
                        state["failed"].append({"id": file_id, "error": msg})
                    print(f"  [{i}/{len(to_download)}] {'OK' if ok else 'FAIL'} {file_id}: {msg}")
                    if i % 10 == 0:
                        save_state(output_dir, state)

        state["completed_at"] = datetime.now().isoformat()
        save_state(output_dir, state)

        elapsed = time.time() - start_time
        print(f"\nDownload complete!")
        print(f"   Success: {success}, Failed: {failed}, Time: {elapsed:.1f}s")
        print(f"   Output: {output_dir}")

    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description="Download TalkCloud media files")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--threads", "-t", type=int, default=DOWNLOAD_THREADS, help="Download threads")
    parser.add_argument("--dry-run", action="store_true", help="Only collect list, skip download")
    parser.add_argument("--method", choices=["browser", "direct"], default="browser",
                        help="Download method (browser=CDP, direct=requests)")
    parser.add_argument("--limit", type=int, default=0, help="Max files to download (0=all)")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
