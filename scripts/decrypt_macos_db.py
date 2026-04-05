#!/usr/bin/env python3
"""Decrypt and export macOS KakaoTalk chat database.

Derives the SQLCipher key from deviceUUID + userId, opens the encrypted
database, and exports messages to JSON.

Prerequisite:
    brew install sqlcipher
    pip install pysqlcipher3   # build with: C_INCLUDE_PATH=$(brew --prefix sqlcipher)/include \
                               #   LIBRARY_PATH=$(brew --prefix sqlcipher)/lib pip install pysqlcipher3

Usage:
    # Auto-detect everything, show stats
    python scripts/decrypt_macos_db.py

    # Export all messages to JSON
    python scripts/decrypt_macos_db.py --export data/kakaotalk_messages.json

    # Export specific chatroom
    python scripts/decrypt_macos_db.py --export data/chat.json --chat-id 163787201460229

    # Run a custom SQL query
    python scripts/decrypt_macos_db.py --query "SELECT count(*) FROM NTChatMessage"

    # Specify userId directly (skip brute-force)
    python scripts/decrypt_macos_db.py --user-id 236788016
"""

import argparse
import hashlib
import base64
import json
import multiprocessing
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Key derivation (from blluv's gist) ──────────────────────────────

def _pbkdf2(password: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password, salt, 100_000, 128)


def _hashed_device_uuid(uuid: str) -> str:
    uuid_bytes = uuid.encode("ascii")
    combined = hashlib.sha1(uuid_bytes).digest() + hashlib.sha256(uuid_bytes).digest()
    return base64.b64encode(combined).decode("ascii")


def get_database_name(user_id: int, uuid: str) -> str:
    """Derive the encrypted database filename from userId + deviceUUID."""
    payload = ".".join([".", "F", str(user_id), "A", "F", "".join(reversed(uuid)), ".", "|"])
    salt = "".join(reversed(_hashed_device_uuid(uuid))).encode("ascii")
    return _pbkdf2(payload.encode("ascii"), salt).hex()[28:28 + 78]


def get_secure_key(user_id: int, uuid: str) -> str:
    """Derive the SQLCipher decryption key from userId + deviceUUID."""
    hashed = _hashed_device_uuid(uuid)
    payload = "F".join(["A", hashed, "|", "F", uuid[:5], "H", str(user_id), "|", uuid[7:]])
    salt = uuid[int(len(uuid) * 0.3):].encode("ascii")
    return _pbkdf2("".join(reversed(payload)).encode("ascii"), salt).hex()


# ── deviceUUID ───────────────────────────────────────────────────────

def get_device_uuid() -> str:
    """Read the IOPlatformUUID from macOS ioreg."""
    result = subprocess.run(
        ["/usr/sbin/ioreg", "-d2", "-c", "IOPlatformExpertDevice"],
        capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if "IOPlatformUUID" in line:
            return line.split('"')[-2]
    raise RuntimeError("Could not read IOPlatformUUID from ioreg")


# ── userId brute-force ───────────────────────────────────────────────

KAKAOTALK_DATA_DIR = Path.home() / "Library/Containers/com.kakao.KakaoTalkMac/Data/Library/Application Support/com.kakao.KakaoTalkMac"


def _find_target_sha512() -> str | None:
    """Extract the SHA512 hash used as the user directory name from plist keys."""
    plist_dir = Path.home() / "Library/Containers/com.kakao.KakaoTalkMac/Data/Library/Preferences"
    for plist in plist_dir.glob("com.kakao.KakaoTalkMac.*.plist"):
        result = subprocess.run(["plutil", "-p", str(plist)], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if "DESIGNATEDFRIENDSREVISION:" in line:
                # The key format is: DESIGNATEDFRIENDSREVISION:<128-char-sha512>
                parts = line.split("DESIGNATEDFRIENDSREVISION:")
                if len(parts) > 1:
                    # Extract the 128-char hex hash
                    candidate = parts[1].strip().strip('"').split('"')[0]
                    if len(candidate) == 128 and all(c in "0123456789abcdef" for c in candidate):
                        return candidate
    return None


def _search_chunk(args):
    start, end, target = args
    for uid in range(start, end):
        if hashlib.sha512(str(uid).encode()).hexdigest() == target:
            return uid
    return None


def find_user_id(target_hash: str, max_id: int = 500_000_000) -> int | None:
    """Brute-force the userId by matching SHA512(str(userId)) to target_hash."""
    chunk = 5_000_000
    ranges = [(i, min(i + chunk, max_id), target_hash) for i in range(0, max_id, chunk)]
    cores = multiprocessing.cpu_count()

    print(f"Brute-forcing userId (0..{max_id:,}, {cores} cores)...")
    start = time.time()

    with multiprocessing.Pool(cores) as pool:
        for i, result in enumerate(pool.imap_unordered(_search_chunk, ranges)):
            if result is not None:
                elapsed = time.time() - start
                print(f"Found userId = {result} ({elapsed:.1f}s)")
                pool.terminate()
                return result
            if (i + 1) % 20 == 0:
                searched = (i + 1) * chunk
                elapsed = time.time() - start
                print(f"  {searched:,} searched ({searched / elapsed / 1e6:.1f}M/s)...")

    return None


# ── Database access ──────────────────────────────────────────────────

def open_db(db_path: str, secure_key: str):
    """Open a SQLCipher-encrypted KakaoTalk database. Returns a connection.
    
    Tries pysqlcipher3 first, falls back to sqlcipher CLI + plain sqlite3.
    """
    try:
        from sqlcipher3 import dbapi2 as sqlite
        conn = sqlite.connect(db_path)
        conn.execute(f"PRAGMA key = '{secure_key}'")
        conn.execute("PRAGMA cipher_compatibility = 3")
        conn.execute("SELECT count(*) FROM sqlite_master")
        return conn
    except (ImportError, ModuleNotFoundError):
        pass

    # Fallback: decrypt via sqlcipher CLI to a plain sqlite3 db
    import subprocess
    import sqlite3
    import tempfile

    plain_db = tempfile.mktemp(suffix=".db")
    sql_commands = f"""PRAGMA key = '{secure_key}';
PRAGMA cipher_compatibility = 3;
ATTACH DATABASE '{plain_db}' AS plaintext KEY '';
SELECT sqlcipher_export('plaintext');
DETACH DATABASE plaintext;
"""
    result = subprocess.run(
        ["sqlcipher", db_path],
        input=sql_commands, capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"sqlcipher CLI failed: {result.stderr}")

    conn = sqlite3.connect(plain_db)
    try:
        conn.execute("SELECT count(*) FROM sqlite_master")
    except Exception:
        raise RuntimeError("Failed to decrypt database.")
    return conn


MESSAGE_TYPES = {
    0: "feed/system",
    1: "text",
    2: "photo",
    3: "video",
    12: "voice",
    13: "map",
    16: "sticker",
    18: "file",
    20: "contact",
    24: "schedule",
    26: "reply",
    27: "shareable",
    51: "emoticon",
    71: "voicechat",
    72: "long_text",
    16385: "long_text_v2",
    16402: "file_v2",
}


def get_stats(conn) -> dict:
    """Collect database statistics."""
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM NTChatMessage")
    total_messages = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM NTChatRoom")
    total_rooms = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM NTUser")
    total_users = cur.fetchone()[0]

    cur.execute("""
        SELECT datetime(min(sentAt), 'unixepoch', 'localtime'),
               datetime(max(sentAt), 'unixepoch', 'localtime')
        FROM NTChatMessage WHERE sentAt > 0
    """)
    earliest, latest = cur.fetchone()

    cur.execute("""
        SELECT type, count(*) as cnt FROM NTChatMessage
        GROUP BY type ORDER BY cnt DESC
    """)
    type_dist = {MESSAGE_TYPES.get(row[0], f"type_{row[0]}"): row[1] for row in cur.fetchall()}

    cur.execute("""
        SELECT r.chatId, r.chatName, r.activeMembersCount, count(m.logId) as cnt,
               datetime(min(m.sentAt), 'unixepoch', 'localtime'),
               datetime(max(m.sentAt), 'unixepoch', 'localtime')
        FROM NTChatRoom r
        LEFT JOIN NTChatMessage m ON r.chatId = m.chatId
        WHERE m.sentAt > 0
        GROUP BY r.chatId ORDER BY cnt DESC
    """)
    rooms = []
    for row in cur.fetchall():
        rooms.append({
            "chatId": row[0], "chatName": row[1] or "", "members": row[2],
            "messages": row[3], "first": row[4], "last": row[5],
        })

    return {
        "total_messages": total_messages,
        "total_rooms": total_rooms,
        "total_users": total_users,
        "date_range": {"earliest": earliest, "latest": latest},
        "message_types": type_dist,
        "chatrooms": rooms,
    }


def export_messages(conn, output_path: str, chat_id: int | None = None):
    """Export messages to JSON, optionally filtered by chatId."""
    cur = conn.cursor()

    # Build user map
    cur.execute("SELECT userId, nickName, friendNickName, displayName FROM NTUser")
    user_map = {}
    for row in cur.fetchall():
        uid, nick, friend_nick, display = row
        user_map[uid] = friend_nick or display or nick or str(uid)

    # Build chatroom map
    cur.execute("SELECT chatId, chatName, activeMembersCount, type FROM NTChatRoom")
    room_map = {}
    for row in cur.fetchall():
        room_map[row[0]] = {"chatName": row[1] or "", "members": row[2], "type": row[3]}

    # Query messages
    query = """
        SELECT chatId, logId, authorId, type, message, attachment, supplement,
               sentAt, status
        FROM NTChatMessage WHERE sentAt > 0
    """
    params = []
    if chat_id:
        query += " AND chatId = ?"
        params.append(chat_id)
    query += " ORDER BY sentAt ASC"

    cur.execute(query, params)

    messages = []
    for row in cur.fetchall():
        cid, log_id, author_id, msg_type, message, attachment, supplement, sent_at, status = row

        # Parse attachment JSON if present
        attach_data = None
        if attachment:
            try:
                attach_data = json.loads(attachment)
            except (json.JSONDecodeError, TypeError):
                attach_data = attachment

        messages.append({
            "chatId": cid,
            "logId": log_id,
            "author": user_map.get(author_id, str(author_id)),
            "authorId": author_id,
            "type": MESSAGE_TYPES.get(msg_type, f"type_{msg_type}"),
            "typeCode": msg_type,
            "message": message,
            "attachment": attach_data,
            "sentAt": datetime.utcfromtimestamp(sent_at).strftime("%Y-%m-%d %H:%M:%S") if sent_at else None,
            "sentAtUnix": sent_at,
        })

    # Group by chatroom
    export = {"exported_at": datetime.now().isoformat(), "total": len(messages), "chatrooms": {}}

    for msg in messages:
        cid = str(msg["chatId"])
        if cid not in export["chatrooms"]:
            room_info = room_map.get(msg["chatId"], {})
            export["chatrooms"][cid] = {
                "chatName": room_info.get("chatName", ""),
                "members": room_info.get("members", 0),
                "messages": [],
            }
        export["chatrooms"][cid]["messages"].append(msg)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(messages)} messages to {output_path}")
    print(f"  Chatrooms: {len(export['chatrooms'])}")


def run_query(conn, sql: str):
    """Execute a SQL query and print results."""
    cur = conn.cursor()
    cur.execute(sql)
    cols = [desc[0] for desc in cur.description] if cur.description else []
    rows = cur.fetchall()

    if cols:
        # Print header
        widths = [max(len(str(c)), max((len(str(r[i])) for r in rows), default=0)) for i, c in enumerate(cols)]
        header = "  ".join(c.ljust(w) for c, w in zip(cols, widths))
        print(header)
        print("  ".join("-" * w for w in widths))
        for row in rows[:100]:
            print("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))
        if len(rows) > 100:
            print(f"  ... ({len(rows)} total rows, showing first 100)")
    else:
        print(f"Query executed. Rows affected: {len(rows)}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Decrypt and export macOS KakaoTalk chat database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s                              Show stats
  %(prog)s --export messages.json       Export all messages
  %(prog)s --export chat.json --chat-id 163787201460229
  %(prog)s --query "SELECT count(*) FROM NTChatMessage"
  %(prog)s --user-id 236788016          Skip brute-force
        """,
    )
    parser.add_argument("--user-id", type=int, default=None,
                        help="KakaoTalk userId (skip brute-force if known)")
    parser.add_argument("--uuid", default=None,
                        help="IOPlatformUUID (auto-detected if omitted)")
    parser.add_argument("--db-path", default=None,
                        help="Path to encrypted DB file (auto-detected if omitted)")
    parser.add_argument("--export", metavar="PATH",
                        help="Export messages to JSON file")
    parser.add_argument("--chat-id", type=int, default=None,
                        help="Filter export to a specific chatId")
    parser.add_argument("--query", metavar="SQL",
                        help="Run a custom SQL query")
    parser.add_argument("--stats-json", metavar="PATH",
                        help="Save stats to JSON file")
    args = parser.parse_args()

    # 1. Get deviceUUID
    uuid = args.uuid or get_device_uuid()
    print(f"deviceUUID: {uuid}")

    # 2. Find userId
    user_id = args.user_id
    if user_id is None:
        target_hash = _find_target_sha512()
        if target_hash is None:
            print("Could not find target SHA512 hash in plist.")
            print("Try specifying --user-id manually.")
            sys.exit(1)
        print(f"Target SHA512: {target_hash[:40]}...")
        user_id = find_user_id(target_hash)
        if user_id is None:
            print("userId not found in range 0..500M.")
            sys.exit(1)
    print(f"userId: {user_id}")

    # 3. Derive keys
    db_name = get_database_name(user_id, uuid)
    secure_key = get_secure_key(user_id, uuid)
    print(f"DB filename: {db_name}")
    print(f"SecureKey: {secure_key[:32]}...")

    # 4. Locate DB file
    db_path = args.db_path
    if db_path is None:
        db_path = str(KAKAOTALK_DATA_DIR / db_name)
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        sys.exit(1)
    print(f"DB path: {db_path}")

    # 5. Open database
    conn = open_db(db_path, secure_key)
    print("Database decrypted successfully.\n")

    # 6. Execute requested action
    if args.query:
        run_query(conn, args.query)
    elif args.export:
        export_messages(conn, args.export, args.chat_id)
    else:
        # Default: show stats
        stats = get_stats(conn)
        print(f"Messages: {stats['total_messages']:,}")
        print(f"Chatrooms: {stats['total_rooms']}")
        print(f"Users: {stats['total_users']}")
        print(f"Period: {stats['date_range']['earliest']} ~ {stats['date_range']['latest']}")
        print(f"\nMessage types:")
        for t, cnt in stats["message_types"].items():
            print(f"  {t}: {cnt:,}")
        print(f"\nChatrooms:")
        for r in stats["chatrooms"]:
            name = r["chatName"] or f"(chatId: {r['chatId']})"
            print(f"  {name}: {r['messages']:,} msgs ({r['first']} ~ {r['last']})")

        if args.stats_json:
            os.makedirs(os.path.dirname(os.path.abspath(args.stats_json)), exist_ok=True)
            with open(args.stats_json, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            print(f"\nStats saved to {args.stats_json}")

    conn.close()


if __name__ == "__main__":
    main()
