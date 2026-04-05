#!/usr/bin/env python3
"""백업 API 엔드포인트 탐색"""
import asyncio, json
from api_client import TalkCloudClient

async def explore():
    client = TalkCloudClient()
    await client.connect()

    endpoints = [
        # 대화방 목록 관련
        ("/backup/chatRoom/list", {}),
        ("/backup/chatRoom/list", {"fetchCount": 100}),
        ("/backup/chat/list", {}),
        ("/backup/chat/list", {"fetchCount": 100}),
        ("/backup/chatlog/list", {}),
        ("/backup/chatLog/list", {}),
        ("/backup/list", {}),
        # v2
        ("/v2/backup/chatRoom/list", {}),
        ("/v2/backup/chat/list", {}),
        # chatLog variants
        ("/backup/chatLog/count", {}),
        ("/backup/chatRoom", {}),
        ("/chatLog/list", {}),
        ("/chatLog/list", {"fetchCount": 10}),
        # chat log with chatId from dump
        ("/backup/chatLog/list", {"chatId": "w_B-WtDOm-jUMcMDKCfIQb5gCtWWcUFvK241Ehfwe54=", "fetchCount": 10}),
        ("/chatLog/list", {"chatId": "w_B-WtDOm-jUMcMDKCfIQb5gCtWWcUFvK241Ehfwe54=", "fetchCount": 10}),
        ("/backup/chatLog", {"chatId": "w_B-WtDOm-jUMcMDKCfIQb5gCtWWcUFvK241Ehfwe54=", "fetchCount": 10}),
    ]

    results = {}
    for path, params in endpoints:
        key = f"{path}?{json.dumps(params)}" if params else path
        print(f"\n🔍 {key}")
        try:
            data = await client.get(path, params if params else None)
            results[key] = {"status": "ok", "data": data}
            summary = json.dumps(data, ensure_ascii=False)[:500]
            print(f"  ✅ {summary}")
        except Exception as e:
            err = str(e)
            results[key] = {"status": "error", "error": err}
            print(f"  ❌ {err[:300]}")
        await asyncio.sleep(0.3)

    await client.close()
    with open("data/backup_explore.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n💾 Saved to data/backup_explore.json")

asyncio.run(explore())
