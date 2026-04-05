#!/usr/bin/env python3
"""Probe warehouse and chat endpoints discovered from JS bundle"""
import asyncio, json
from api_client import TalkCloudClient

async def main():
    client = TalkCloudClient()
    await client.connect()
    results = {}

    # 1. Warehouse chat list (paginated with lastChatId)
    print("\n🏠 /warehouse/chat/chats")
    try:
        data = await client.get("/warehouse/chat/chats")
        results["warehouse_chats"] = data
        print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
    except Exception as e:
        print(f"  ❌ {e}")
        results["warehouse_chats_error"] = str(e)

    # 2. Chat list variants (MEDIA, FILE, LINK, MEMO)
    for vtype in ["MEDIA", "FILE", "LINK"]:
        print(f"\n💬 /chat/list?verticalType={vtype}")
        try:
            data = await client.get("/chat/list", {"verticalType": vtype})
            results[f"chat_list_{vtype}"] = data
            items = data.get("items", [])
            print(f"  hasMore: {data.get('hasMore')}, items: {len(items)}")
            if items:
                print(f"  First: {json.dumps(items[0], ensure_ascii=False)[:500]}")
        except Exception as e:
            print(f"  ❌ {e}")

    # 3. Get a chatId from chat list to probe content endpoints
    chat_list = results.get("chat_list_MEDIA", {})
    items = chat_list.get("items", [])
    if items:
        chat_id = items[0]["chatId"]
        chat_title = items[0].get("title", "unknown")
        print(f"\n🔍 Testing with chatId: {chat_title} ({chat_id[:30]}...)")

        # 3a. Encrypted chat
        print(f"\n🔐 /chat/encrypted/{chat_id[:20]}...")
        try:
            data = await client.get(f"/chat/encrypted/{chat_id}")
            results["encrypted_chat"] = data
            print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
        except Exception as e:
            print(f"  ❌ {e}")
            results["encrypted_chat_error"] = str(e)

        # 3b. Content list (mediaFile)
        for api_url in ["mediaFile", "file", "link", "memo"]:
            print(f"\n📦 /warehouse/{chat_id[:20]}.../{api_url}/list")
            try:
                # Try warehouse style
                data = await client.get(f"/warehouse/{chat_id}/{api_url}/list", {
                    "verticalType": api_url.upper() if api_url != "mediaFile" else "MEDIA",
                    "fetchCount": 5,
                    "direction": "DESC"
                })
                results[f"warehouse_{api_url}"] = data
                print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
            except Exception as e:
                print(f"  ❌ {e}")

        # 3c. ChatInfo
        print(f"\n📋 /chatInfo")
        try:
            data = await client.post("/chatInfo", {"chatIds": [chat_id]})
            results["chat_info"] = data
            print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
        except Exception as e:
            print(f"  ❌ {e}")

    # 4. MediaFile list with different params
    print(f"\n📸 /mediaFile/list (global)")
    try:
        data = await client.get("/mediaFile/list", {
            "verticalType": "MEDIA",
            "fetchCount": 3,
            "joined": "true",
            "direction": "DESC"
        })
        results["media_list_sample"] = data
        items = data.get("items", [])
        total = data.get("totalCount", 0)
        print(f"  Total: {total}, This page: {len(items)}")
        if items:
            print(f"  First item keys: {list(items[0].keys())}")
            print(f"  First: {json.dumps(items[0], ensure_ascii=False)[:500]}")
    except Exception as e:
        print(f"  ❌ {e}")

    # 5. Global content endpoints
    for vtype in ["FILE", "LINK", "MEMO"]:
        path = "file" if vtype == "FILE" else vtype.lower()
        print(f"\n📋 /{path}/list?verticalType={vtype}")
        try:
            data = await client.get(f"/{path}/list", {
                "verticalType": vtype,
                "fetchCount": 3,
                "direction": "DESC"
            })
            results[f"global_{vtype}"] = data
            items = data.get("items", [])
            total = data.get("totalCount", 0)
            print(f"  Total: {total}, items: {len(items)}")
            if items:
                print(f"  Keys: {list(items[0].keys())}")
                first_str = json.dumps(items[0], ensure_ascii=False)[:400]
                print(f"  First: {first_str}")
        except Exception as e:
            print(f"  ❌ {e}")

    # 6. Contact snapshots
    print(f"\n📇 /contactSnapshot/list")
    try:
        data = await client.get("/contactSnapshot/list", {"fetchCount": 5})
        results["contact_snapshots"] = data
        items = data.get("items", [])
        print(f"  Items: {len(items)}")
        if items:
            print(f"  First: {json.dumps(items[0], ensure_ascii=False)[:300]}")
    except Exception as e:
        print(f"  ❌ {e}")

    await client.close()

    with open("data/probe_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n💾 Saved to data/probe_results.json")

asyncio.run(main())
