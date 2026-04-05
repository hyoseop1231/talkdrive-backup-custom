#!/usr/bin/env python3
"""Extract and organize TalkCloud content by chatroom (7 stages).

Fetches all accessible content (media metadata, files, links) and
organizes it per chatroom with author name resolution and chronological
sorting.

Note: Encrypted chat messages (backup) are NOT accessible via the web API.

Usage:
    python scripts/extract_content.py
    python scripts/extract_content.py --output data/messages
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kakao_backup.cdp_client import TalkCloudClient
from kakao_backup.config import DATA_DIR
from kakao_backup.utils import sanitize_filename, ts_to_str


OUTPUT_DIR = str(DATA_DIR / "messages")
RAW_DIR = str(DATA_DIR / "raw")


async def fetch_all_paginated_drawer(
    client: TalkCloudClient, path: str, params: dict, label: str = ""
) -> list:
    """Paginate using the drawerId-based offset parameter."""
    base_params = {**params, "fetchCount": 100, "direction": "DESC"}
    all_items: list = []
    page = 0

    while True:
        page += 1
        req_params = {**base_params}
        if page > 1:
            last_item = all_items[-1]
            offset_value = last_item.get("drawerId")
            if offset_value:
                req_params["offset"] = offset_value

        result = await client.get(path, req_params)
        items = result.get("items", [])
        all_items.extend(items)

        has_more = result.get("hasMore", False)
        print(
            f"  {label} page {page}: +{len(items)} "
            f"(total: {len(all_items)}{', hasMore' if has_more else ', done'})"
        )

        if not items or not has_more:
            break
        await asyncio.sleep(0.15)

    return all_items


async def extract_all(output_dir: str, raw_dir: str):
    """Run the 7-stage content extraction pipeline."""
    start_time = time.time()
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(raw_dir, exist_ok=True)

    client = TalkCloudClient()
    await client.connect()

    try:
        # === Stage 1: Basic info ===
        print("\n" + "=" * 60)
        print("Stage 1: Basic info")
        print("=" * 60)

        backup_info = await client.get_backup_info()
        print(
            f"  Backup: {backup_info.get('backupChatCount')} rooms, "
            f"{backup_info.get('backupChatLogCount')} messages"
        )
        print("  Note: chat message text is encrypted (mobile-restore only)")

        friends_data = await client.get_friends()
        friends = friends_data.get("friends", [])
        friend_map: dict[str, str] = {}
        for f in friends:
            hid = f.get("hashedTalkUserId") or f.get("hashedAccountId")
            if hid:
                friend_map[hid] = f.get("displayName", f.get("nickName", "Unknown"))
        print(f"  Friends: {len(friends)} (for name resolution)")

        with open(os.path.join(raw_dir, "backup_info.json"), "w", encoding="utf-8") as fp:
            json.dump(backup_info, fp, ensure_ascii=False, indent=2)
        with open(os.path.join(raw_dir, "friends.json"), "w", encoding="utf-8") as fp:
            json.dump(friends_data, fp, ensure_ascii=False, indent=2)

        # === Stage 2: Chatroom metadata ===
        print("\n" + "=" * 60)
        print("Stage 2: Chatroom metadata")
        print("=" * 60)

        chatroom_map: dict = {}
        for vtype in ["MEDIA", "FILE", "LINK"]:
            try:
                data = await client.get("/chat/list", {"verticalType": vtype})
                items = data.get("items", [])
                print(f"  {vtype}: {len(items)} chatrooms")
                for item in items:
                    hcid = item.get("hashedChatId", "")
                    if hcid not in chatroom_map:
                        chatroom_map[hcid] = {
                            "title": item.get("title", "Unknown"),
                            "chatType": item.get("chatType", "Unknown"),
                            "memberCount": item.get("memberCount", 0),
                            "displayMembers": item.get("displayMembers", []),
                            "hashedChatId": hcid,
                            "counts": {},
                        }
                    chatroom_map[hcid]["counts"][vtype] = {
                        "count": int(item.get("count", 0)),
                        "size": int(item.get("size", 0)),
                    }
            except Exception as e:
                print(f"  {vtype} failed: {e}")

        print(f"\n  Total unique chatrooms: {len(chatroom_map)}")
        with open(os.path.join(raw_dir, "chatrooms.json"), "w", encoding="utf-8") as fp:
            json.dump(chatroom_map, fp, ensure_ascii=False, indent=2)

        # === Stage 3: Media files ===
        print("\n" + "=" * 60)
        print("Stage 3: Media files (images/videos)")
        print("=" * 60)

        all_media = await fetch_all_paginated_drawer(
            client, "/mediaFile/list",
            {"verticalType": "MEDIA", "joined": "true"}, label="MEDIA",
        )
        print(f"  Total media: {len(all_media)}")
        with open(os.path.join(raw_dir, "all_media.json"), "w", encoding="utf-8") as fp:
            json.dump(all_media, fp, ensure_ascii=False, indent=2)

        # === Stage 4: Files ===
        print("\n" + "=" * 60)
        print("Stage 4: Files")
        print("=" * 60)

        all_files = await fetch_all_paginated_drawer(
            client, "/mediaFile/list",
            {"verticalType": "FILE", "joined": "true"}, label="FILE",
        )
        print(f"  Total files: {len(all_files)}")
        with open(os.path.join(raw_dir, "all_files.json"), "w", encoding="utf-8") as fp:
            json.dump(all_files, fp, ensure_ascii=False, indent=2)

        # === Stage 5: Links ===
        print("\n" + "=" * 60)
        print("Stage 5: Links")
        print("=" * 60)

        all_links = await fetch_all_paginated_drawer(
            client, "/link/list", {"verticalType": "LINK"}, label="LINK",
        )
        print(f"  Total links: {len(all_links)}")
        with open(os.path.join(raw_dir, "all_links.json"), "w", encoding="utf-8") as fp:
            json.dump(all_links, fp, ensure_ascii=False, indent=2)

        # === Stage 6: Contacts ===
        print("\n" + "=" * 60)
        print("Stage 6: Contacts")
        print("=" * 60)

        try:
            snapshots = await client.get("/contactSnapshot/list", {"fetchCount": 50})
            snap_items = snapshots.get("items", [])
            print(f"  Contact snapshots: {len(snap_items)}")
            all_contacts = []
            for snap in snap_items:
                sid = snap.get("id")
                if sid:
                    contacts = await client.get(
                        "/contact/list", {"snapshotId": str(sid), "fetchCount": 100}
                    )
                    snap["contacts"] = contacts.get("items", [])
                    all_contacts.extend(snap["contacts"])
                    await asyncio.sleep(0.2)
            with open(os.path.join(raw_dir, "contacts.json"), "w", encoding="utf-8") as fp:
                json.dump(snapshots, fp, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  Failed: {e}")

        # === Stage 7: Organize by chatroom ===
        print("\n" + "=" * 60)
        print("Stage 7: Organize by chatroom")
        print("=" * 60)

        content_by_chat: dict = defaultdict(lambda: {"media": [], "files": [], "links": []})
        for item in all_media:
            content_by_chat[item.get("hashedChatId", "unknown")]["media"].append(item)
        for item in all_files:
            content_by_chat[item.get("hashedChatId", "unknown")]["files"].append(item)
        for item in all_links:
            content_by_chat[item.get("hashedChatId", "unknown")]["links"].append(item)

        chatroom_stats = []
        for hcid, content in content_by_chat.items():
            room_info = chatroom_map.get(hcid, {"title": f"Unknown_{hcid[:8]}", "chatType": "Unknown", "memberCount": 0})
            title = room_info.get("title", f"chat_{hcid[:8]}")
            safe_title = sanitize_filename(title)[:100]
            total_items = len(content["media"]) + len(content["files"]) + len(content["links"])

            # Author name mapping
            for category in ("media", "files", "links"):
                for item in content[category]:
                    haid = item.get("hashedAuthorId", "")
                    item["authorName"] = friend_map.get(haid)

            # Sort chronologically
            for category in ("media", "files", "links"):
                content[category].sort(key=lambda x: int(x.get("createdAt", 0)))

            # Build unified content list
            all_content: list = []
            for item in content["media"]:
                all_content.append({
                    "type": "media",
                    "contentType": item.get("contentType", ""),
                    "timestamp": ts_to_str(item.get("createdAt")),
                    "createdAt": item.get("createdAt"),
                    "author": item.get("authorName") or item.get("hashedAuthorId", ""),
                    "mimeType": item.get("mimeType", ""),
                    "size": item.get("size"),
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "url": item.get("url", ""),
                    "thumbnailUrl": item.get("thumbnailUrl", ""),
                    "id": item.get("id"),
                    "drawerId": item.get("drawerId"),
                })
            for item in content["files"]:
                all_content.append({
                    "type": "file",
                    "timestamp": ts_to_str(item.get("createdAt")),
                    "createdAt": item.get("createdAt"),
                    "author": item.get("authorName") or item.get("hashedAuthorId", ""),
                    "fileName": item.get("originalFileName", ""),
                    "mimeType": item.get("mimeType", ""),
                    "size": item.get("size"),
                    "url": item.get("url", ""),
                    "id": item.get("id"),
                    "drawerId": item.get("drawerId"),
                })
            for item in content["links"]:
                all_content.append({
                    "type": "link",
                    "timestamp": ts_to_str(item.get("createdAt")),
                    "createdAt": item.get("createdAt"),
                    "author": item.get("authorName") or item.get("hashedAuthorId", ""),
                    "url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "imageUrl": item.get("imageUrl", ""),
                    "id": item.get("id"),
                    "drawerId": item.get("drawerId"),
                })
            all_content.sort(key=lambda x: int(x.get("createdAt", 0)))

            room_data = {
                "chatroom": {
                    "title": title,
                    "hashedChatId": hcid,
                    "chatType": room_info.get("chatType", "Unknown"),
                    "memberCount": room_info.get("memberCount", 0),
                    "members": [
                        {"nickName": m.get("nickName", ""), "hashedUserId": m.get("hashedUserId", "")}
                        for m in room_info.get("displayMembers", [])
                    ],
                },
                "summary": {
                    "total_items": total_items,
                    "media_count": len(content["media"]),
                    "file_count": len(content["files"]),
                    "link_count": len(content["links"]),
                    "date_range": {
                        "earliest": ts_to_str(all_content[0]["createdAt"]) if all_content else None,
                        "latest": ts_to_str(all_content[-1]["createdAt"]) if all_content else None,
                    },
                },
                "content": all_content,
            }

            filename = f"{safe_title}_{hcid[:8]}.json"
            with open(os.path.join(output_dir, filename), "w", encoding="utf-8") as fp:
                json.dump(room_data, fp, ensure_ascii=False, indent=2)

            chatroom_stats.append({
                "title": title, "hashedChatId": hcid,
                "total_items": total_items,
                "media": len(content["media"]),
                "files": len(content["files"]),
                "links": len(content["links"]),
                "filename": filename,
            })
            if total_items > 0:
                print(f"  {title}: {total_items} items")

        chatroom_stats.sort(key=lambda x: x["total_items"], reverse=True)

        # Final stats
        elapsed = time.time() - start_time
        total_content = len(all_media) + len(all_files) + len(all_links)
        stats = {
            "extraction_time": datetime.now().isoformat(),
            "total_chatrooms": len(chatroom_map),
            "chatrooms_with_content": sum(1 for s in chatroom_stats if s["total_items"] > 0),
            "total_content_items": total_content,
            "media_count": len(all_media),
            "file_count": len(all_files),
            "link_count": len(all_links),
            "elapsed_seconds": round(elapsed, 1),
            "chatroom_stats": chatroom_stats,
        }

        stats_path = os.path.join(str(DATA_DIR), "extraction_stats.json")
        os.makedirs(os.path.dirname(stats_path), exist_ok=True)
        with open(stats_path, "w", encoding="utf-8") as fp:
            json.dump(stats, fp, ensure_ascii=False, indent=2)

        print(f"\nExtraction complete in {elapsed:.1f}s")
        print(f"  Chatrooms: {len(chatroom_map)}")
        print(f"  Media: {len(all_media):,}  Files: {len(all_files):,}  Links: {len(all_links):,}")
        print(f"  Total: {total_content:,} items")

    finally:
        await client.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description="Extract TalkCloud content by chatroom")
    parser.add_argument("--output", "-o", default=OUTPUT_DIR, help="Output directory for per-room JSON")
    parser.add_argument("--raw-dir", default=RAW_DIR, help="Directory for raw API dumps")
    args = parser.parse_args()
    asyncio.run(extract_all(args.output, args.raw_dir))


if __name__ == "__main__":
    main()
