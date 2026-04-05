"""Synchronize Kakao TalkCloud data to Neo4j graph database.

Nodes:
    Person  (source: "kakao") - from friends + displayMembers
    ChatRoom (source: "kakao") - from chatMedia/chatFile/chatLink
    Contact  (source: "kakao") - from contacts

Relationships:
    MEMBER_OF  - Person -> ChatRoom
    FRIEND_OF  - Person -> Person
    SAME_AS    - kakao Person <-> existing Person (name match)
"""

import json
import logging

from neo4j import GraphDatabase

from kakao_backup.config import KAKAO_MY_HASHED_ID, NEO4J_PASS, NEO4J_URI, NEO4J_USER

logger = logging.getLogger(__name__)


def load_data(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_persons(data: dict) -> dict:
    """Extract Person records from friends + displayMembers (dedup by hashedUserId)."""
    persons: dict = {}

    # 1) friends
    for f in data.get("friends", {}).get("friends", []):
        hid = f.get("hashedTalkUserId", "")
        if hid:
            persons[hid] = {
                "hashedUserId": hid,
                "name": f.get("displayName", ""),
                "profileImageUrl": f.get("profileImageUrl", ""),
                "is_friend": True,
            }

    # 2) displayMembers from chat sections
    for section in ("chatMedia", "chatFile", "chatLink", "chat_media", "chat_file", "chat_link"):
        section_data = data.get(section, {})
        items = section_data.get("items", []) if isinstance(section_data, dict) else []
        for item in items:
            for m in item.get("displayMembers", []):
                hid = m.get("hashedUserId", "")
                if not hid:
                    continue
                if hid in persons:
                    if not persons[hid]["profileImageUrl"] and m.get("profileImageUrl"):
                        persons[hid]["profileImageUrl"] = m["profileImageUrl"]
                else:
                    persons[hid] = {
                        "hashedUserId": hid,
                        "name": m.get("nickName", ""),
                        "profileImageUrl": m.get("profileImageUrl", ""),
                        "is_friend": False,
                    }

    return persons


def extract_chatrooms(data: dict) -> tuple[dict, dict]:
    """Extract ChatRoom records + membership sets."""
    rooms: dict = {}
    room_members: dict = {}

    for section in ("chatMedia", "chatFile", "chatLink", "chat_media", "chat_file", "chat_link"):
        section_data = data.get(section, {})
        items = section_data.get("items", []) if isinstance(section_data, dict) else []
        for item in items:
            hcid = item.get("hashedChatId", "")
            if not hcid:
                continue
            if hcid not in rooms:
                rooms[hcid] = {
                    "hashedChatId": hcid,
                    "title": item.get("title", ""),
                    "chatType": item.get("chatType", ""),
                    "memberCount": item.get("memberCount", 0),
                }
                room_members[hcid] = set()

            for m in item.get("displayMembers", []):
                huid = m.get("hashedUserId", "")
                if huid:
                    room_members[hcid].add(huid)

    return rooms, room_members


def extract_contacts(data: dict) -> list:
    """Extract Contact records."""
    contacts = []
    for c in data.get("contacts", data.get("contacts_all", [])):
        if isinstance(c, dict):
            phones = c.get("phones", [])
            phone = phones[0]["value"] if phones else ""
            contacts.append({
                "drawerId": c.get("drawerId", ""),
                "displayName": c.get("displayName", ""),
                "phone": phone,
                "company": c.get("company", ""),
            })
    return contacts


def sync_to_neo4j(persons, rooms, room_members, contacts, friends_ids,
                  my_hashed_id: str | None = None):
    """Write extracted data to Neo4j.

    Returns:
        Dictionary with creation/relationship counts.
    """
    my_id = my_hashed_id or KAKAO_MY_HASHED_ID
    if not my_id:
        logger.warning("KAKAO_MY_HASHED_ID not set — FRIEND_OF relations will be skipped")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    stats = {
        "persons_created": 0,
        "chatrooms_created": 0,
        "contacts_created": 0,
        "member_of": 0,
        "friend_of": 0,
        "same_as": 0,
    }

    with driver.session() as session:
        # 1. Person nodes
        for p in persons.values():
            result = session.run("""
                MERGE (p:Person {hashedUserId: $hashedUserId})
                ON CREATE SET
                    p.name = $name,
                    p.profileImageUrl = $profileImageUrl,
                    p.platform = "kakao",
                    p.source = "kakao"
                ON MATCH SET
                    p.name = CASE WHEN p.name IS NULL OR p.name = '' THEN $name ELSE p.name END,
                    p.profileImageUrl = CASE WHEN p.profileImageUrl IS NULL OR p.profileImageUrl = ''
                        THEN $profileImageUrl ELSE p.profileImageUrl END,
                    p.platform = "kakao",
                    p.source = "kakao"
                RETURN p
            """, hashedUserId=p["hashedUserId"], name=p["name"],
                profileImageUrl=p["profileImageUrl"])
            summary = result.consume()
            stats["persons_created"] += summary.counters.nodes_created

        # 2. ChatRoom nodes
        for r in rooms.values():
            result = session.run("""
                MERGE (c:ChatRoom {hashedChatId: $hashedChatId})
                ON CREATE SET
                    c.title = $title, c.chatType = $chatType,
                    c.memberCount = $memberCount, c.source = "kakao"
                ON MATCH SET
                    c.title = $title, c.chatType = $chatType,
                    c.memberCount = $memberCount, c.source = "kakao"
                RETURN c
            """, hashedChatId=r["hashedChatId"], title=r["title"],
                chatType=r["chatType"], memberCount=r["memberCount"])
            summary = result.consume()
            stats["chatrooms_created"] += summary.counters.nodes_created

        # 3. Contact nodes
        for c in contacts:
            result = session.run("""
                MERGE (ct:Contact {drawerId: $drawerId})
                ON CREATE SET
                    ct.displayName = $displayName, ct.phone = $phone,
                    ct.company = $company, ct.source = "kakao"
                ON MATCH SET
                    ct.displayName = $displayName, ct.phone = $phone,
                    ct.company = $company, ct.source = "kakao"
                RETURN ct
            """, drawerId=c["drawerId"], displayName=c["displayName"],
                phone=c["phone"], company=c["company"])
            summary = result.consume()
            stats["contacts_created"] += summary.counters.nodes_created

        # 4. MEMBER_OF relationships
        for hcid, member_ids in room_members.items():
            for huid in member_ids:
                result = session.run("""
                    MATCH (p:Person {hashedUserId: $huid})
                    MATCH (c:ChatRoom {hashedChatId: $hcid})
                    MERGE (p)-[r:MEMBER_OF]->(c)
                    RETURN r
                """, huid=huid, hcid=hcid)
                summary = result.consume()
                stats["member_of"] += summary.counters.relationships_created

        # 5. FRIEND_OF relationships
        if my_id:
            for fid in friends_ids:
                result = session.run("""
                    MATCH (me:Person {hashedUserId: $myId})
                    MATCH (fr:Person {hashedUserId: $friendId})
                    MERGE (me)-[r:FRIEND_OF]->(fr)
                    RETURN r
                """, myId=my_id, friendId=fid)
                summary = result.consume()
                stats["friend_of"] += summary.counters.relationships_created

        # 6. SAME_AS relationships (name-based matching)
        result = session.run("""
            MATCH (kakao:Person {source: 'kakao'})
            WHERE kakao.name IS NOT NULL AND kakao.name <> ''
            MATCH (existing:Person)
            WHERE existing.hashedUserId IS NULL
              AND existing.name = kakao.name
              AND id(existing) <> id(kakao)
            MERGE (kakao)-[r:SAME_AS]->(existing)
            RETURN count(r) as cnt
        """)
        record = result.single()
        stats["same_as"] = record["cnt"] if record else 0

    driver.close()
    return stats
