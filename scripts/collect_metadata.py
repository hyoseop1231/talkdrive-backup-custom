#!/usr/bin/env python3
"""Collect all Kakao TalkCloud metadata via CDP API (13 steps).

Connects to Chrome debugging port and fetches every available API
endpoint, saving individual JSON files plus a combined dump.

Usage:
    python scripts/collect_metadata.py
    python scripts/collect_metadata.py --output data/custom_dir
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kakao_backup.cdp_client import TalkCloudClient
from kakao_backup.config import DATA_DIR


async def save_json(name: str, data, output_dir: str):
    """Write data to a JSON file."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {path}")


async def collect_all(output_base: str):
    """Run the 13-step metadata collection."""
    client = TalkCloudClient()
    await client.connect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(output_base, f"dump_{timestamp}")
    results = {}

    try:
        # 1. User Info
        print("\n[1/13] User Info...")
        try:
            results["user_info"] = await client.get_user_info()
            await save_json("user_info", results["user_info"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 2. Friends
        print("\n[2/13] Friends...")
        try:
            results["friends"] = await client.get_friends()
            count = len(results["friends"].get("friends", []))
            print(f"  Found {count} friends")
            await save_json("friends", results["friends"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 3. Chat Lists (MEDIA/FILE/LINK)
        for vtype in ["MEDIA", "FILE", "LINK"]:
            print(f"\n[3] Chat List ({vtype})...")
            try:
                data = await client.get_chat_list(vtype)
                key = f"chat_{vtype.lower()}"
                results[key] = data
                count = len(data.get("items", []))
                print(f"  Found {count} chats")
                await save_json(key, data, output_dir)
            except Exception as e:
                print(f"  Failed: {e}")

        # 4. Backup Info
        print("\n[4/13] Backup Info...")
        try:
            results["backup_info"] = await client.get_backup_info()
            await save_json("backup_info", results["backup_info"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 5. Chatbots
        print("\n[5/13] Chatbots...")
        try:
            results["chatbots"] = await client.get_chatbots()
            await save_json("chatbots", results["chatbots"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 6. All Media Files (paginated)
        print("\n[6/13] All Media Files (paginated)...")
        try:
            results["media_all"] = await client.get_all_media()
            print(f"  Total: {len(results['media_all'])} media files")
            await save_json("media_all", results["media_all"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 7. Media Tags
        print("\n[7/13] Media Tags...")
        try:
            results["media_tags"] = await client.get_media_tags()
            await save_json("media_tags", results["media_tags"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 8. Labels
        print("\n[8/13] Labels...")
        try:
            results["labels"] = await client.get_labels()
            await save_json("labels", results["labels"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 9. Folders
        print("\n[9/13] Folders...")
        try:
            results["folders"] = await client.get_folders()
            await save_json("folders", results["folders"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 10. Cloud Folders
        print("\n[10/13] Cloud Folders...")
        try:
            results["cloud_folders"] = await client.get_cloud_folders()
            await save_json("cloud_folders", results["cloud_folders"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 11. Contact Snapshots + Details
        print("\n[11/13] Contact Snapshots...")
        try:
            snapshots = await client.get_contact_snapshots()
            results["contact_snapshots"] = snapshots
            await save_json("contact_snapshots", snapshots, output_dir)

            all_contacts = []
            for snap in snapshots.get("items", []):
                sid = snap.get("id")
                if sid:
                    contacts = await client.get_contacts(str(sid))
                    all_contacts.extend(contacts.get("items", []))
                    await asyncio.sleep(0.2)

            results["contacts_all"] = all_contacts
            print(f"  Total contacts: {len(all_contacts)}")
            await save_json("contacts_all", all_contacts, output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 12. Friend Latest Media
        print("\n[12/13] Friend Latest Media...")
        try:
            results["friend_latest_media"] = await client.get_friend_latest_media()
            await save_json("friend_latest_media", results["friend_latest_media"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # 13. Notice Cards
        print("\n[13/13] Notice Cards...")
        try:
            results["notice_cards"] = await client.get_notice_cards()
            await save_json("notice_cards", results["notice_cards"], output_dir)
        except Exception as e:
            print(f"  Failed: {e}")

        # Combined dump
        print("\nSaving combined dump...")
        await save_json("kakao_talkcloud_dump", results, output_dir)

        print(f"\nCollection complete! Output: {output_dir}/")
        print(f"   Files: {len(os.listdir(output_dir))}")

    finally:
        await client.close()

    return results


def main():
    parser = argparse.ArgumentParser(description="Collect all TalkCloud metadata")
    parser.add_argument("--output", "-o", default=str(DATA_DIR),
                        help="Base output directory")
    args = parser.parse_args()
    asyncio.run(collect_all(args.output))


if __name__ == "__main__":
    main()
