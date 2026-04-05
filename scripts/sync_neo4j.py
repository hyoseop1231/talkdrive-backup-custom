#!/usr/bin/env python3
"""CLI wrapper for Neo4j synchronization.

Reads TalkCloud dump JSON and syncs Person, ChatRoom, Contact nodes
with MEMBER_OF, FRIEND_OF, SAME_AS relationships.

Usage:
    python scripts/sync_neo4j.py
    python scripts/sync_neo4j.py --data data/dump_20250129/kakao_talkcloud_dump.json
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kakao_backup.config import DATA_DIR
from kakao_backup.neo4j_sync import (
    extract_chatrooms,
    extract_contacts,
    extract_persons,
    load_data,
    sync_to_neo4j,
)

DEFAULT_DATA_FILE = str(DATA_DIR / "kakao_talkcloud_dump.json")


def main():
    parser = argparse.ArgumentParser(description="Sync TalkCloud data to Neo4j")
    parser.add_argument("--data", default=DEFAULT_DATA_FILE,
                        help="Path to kakao_talkcloud_dump.json")
    args = parser.parse_args()

    if not os.path.exists(args.data):
        print(f"Data file not found: {args.data}")
        print("Run scripts/collect_metadata.py first, or specify --data path")
        sys.exit(1)

    print(f"Loading {args.data} ...")
    data = load_data(args.data)

    print("Extracting data ...")
    persons = extract_persons(data)
    rooms, room_members = extract_chatrooms(data)
    contacts = extract_contacts(data)
    friends_ids = [
        f["hashedTalkUserId"]
        for f in data.get("friends", {}).get("friends", [])
        if f.get("hashedTalkUserId")
    ]

    print(f"   Persons: {len(persons)} (friends: {sum(1 for p in persons.values() if p['is_friend'])})")
    print(f"   ChatRooms: {len(rooms)}")
    print(f"   Contacts: {len(contacts)}")
    print(f"   Friend links: {len(friends_ids)}")
    print(f"   Member-of links: {sum(len(m) for m in room_members.values())}")

    print("\nSyncing to Neo4j ...")
    stats = sync_to_neo4j(persons, rooms, room_members, contacts, friends_ids)

    print("\nDone! Results:")
    for k, v in stats.items():
        print(f"   {k}: {v}")


if __name__ == "__main__":
    main()
