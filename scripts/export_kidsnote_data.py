#!/usr/bin/env python3
"""KidsNote 데이터 Export — Docker 컨테이너 내에서 실행"""
import json, os, sys
from datetime import datetime

sys.path.insert(0, "/app")
from config import Config
from src.clients.kidsnote import KidsNoteClient

CHILDREN = [
    {"id": 2795010, "name": "김아영", "birth": "2018-06-08", "gender": "girl", "order": 1, "role": "딸"},
    {"id": 4879900, "name": "김현서", "birth": "2023-02-14", "gender": "boy", "order": 2, "role": "아들"},
]
PARENT = {"id": 2836523, "name": "박보미", "username": "pbm0221", "email": "pbm0221@naver.com"}
BASE = "https://www.kidsnote.com"
EXPORT_PATH = "/app/output/kidsnote_export.json"


def paginate(session, url, params=None):
    """커서 기반 페이지네이션 (next = cursor token)"""
    all_results = []
    p = dict(params or {})
    page_num = 1
    while True:
        resp = session.get(url, params=p, timeout=30)
        if resp.status_code != 200:
            print(f"  ⚠ HTTP {resp.status_code} at page {page_num}")
            break
        data = resp.json()
        results = data.get("results", [])
        if not results:
            break
        all_results.extend(results)
        cursor = data.get("next")
        if not cursor:
            break
        p["page"] = cursor
        page_num += 1
    return all_results


def main():
    print("=" * 50)
    print("KidsNote 데이터 Export")
    print("=" * 50)

    kn = KidsNoteClient(Config.KIDSNOTE_USERNAME, Config.KIDSNOTE_PASSWORD, Config.KIDSNOTE_CHILD_ID)
    kn.login()
    session = kn.session

    export = {
        "export_timestamp": datetime.now().isoformat(),
        "parent": PARENT,
        "children": [],
        "reports": [],
        "albums": [],
        "teachers": {},
        "centers": {},
    }

    for child in CHILDREN:
        cid = child["id"]
        print(f"\n📌 {child['name']} (child_id={cid})")
        export["children"].append({**child, "type": "kidsnote_child"})

        # Reports
        raw_reports = paginate(session, f"{BASE}/api/v1/children/{cid}/reports/")
        for r in raw_reports:
            author = r.get("author", {}) or {}
            report = {
                "id": str(r["id"]),
                "date": r.get("date_written", ""),
                "text": r.get("content", ""),
                "author_name": author.get("name", "") if isinstance(author, dict) else str(author),
                "author_id": str(author.get("id", "")) if isinstance(author, dict) else "",
                "class_name": r.get("class_name", ""),
                "center_id": str(r.get("center", "")),
                "child_id": str(cid),
                "child_name": r.get("child_name", ""),
                "type": "kidsnote_report",
            }
            export["reports"].append(report)
            if report["author_id"]:
                export["teachers"][report["author_id"]] = {"id": report["author_id"], "name": report["author_name"], "type": "kidsnote_teacher"}
            if report["center_id"]:
                export["centers"][report["center_id"]] = {"id": report["center_id"], "type": "kidsnote_center"}
        print(f"  ✓ Reports: {len(raw_reports)}개")

        # Albums
        raw_albums = paginate(session, f"{BASE}/api/v1_3/children/{cid}/albums/", {"tz": "Asia/Seoul"})
        for a in raw_albums:
            author = a.get("author", {}) or {}
            album = {
                "id": str(a["id"]),
                "date": (a.get("date_created") or "")[:10],
                "title": a.get("title", ""),
                "image_count": len(a.get("attached_images", [])),
                "author_name": author.get("name", "") if isinstance(author, dict) else "",
                "author_id": str(author.get("id", "")) if isinstance(author, dict) else "",
                "center_id": str(a.get("center", "")),
                "child_id": str(cid),
                "type": "kidsnote_album",
            }
            export["albums"].append(album)
            if album["author_id"]:
                export["teachers"][album["author_id"]] = {"id": album["author_id"], "name": album["author_name"], "type": "kidsnote_teacher"}
        print(f"  ✓ Albums: {len(raw_albums)}개")

    export["teachers"] = list(export["teachers"].values())
    export["centers"] = list(export["centers"].values())

    with open(EXPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✓ Export: {EXPORT_PATH}")
    print(f"  아이: {len(export['children'])} | 알림장: {len(export['reports'])} | 앨범: {len(export['albums'])}")
    print(f"  교사: {len(export['teachers'])} | 어린이집: {len(export['centers'])}")
    print("=" * 50)


if __name__ == "__main__":
    main()
