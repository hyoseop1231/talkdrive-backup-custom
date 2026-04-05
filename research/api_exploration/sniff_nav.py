#!/usr/bin/env python3
"""Navigate to backup page and capture all network requests via CDP"""
import asyncio, json
import aiohttp, websockets

async def main():
    async with aiohttp.ClientSession() as s:
        async with s.get("http://localhost:18792/json") as r:
            tabs = await r.json()

    tab = next(t for t in tabs if "talkcloud" in t.get("url", ""))
    ws = await websockets.connect(tab["webSocketDebuggerUrl"], max_size=50*1024*1024)
    
    msg_id = [0]
    async def cdp(method, params=None):
        msg_id[0] += 1
        m = {"id": msg_id[0], "method": method}
        if params: m["params"] = params
        await ws.send(json.dumps(m))

    captured = []
    
    # Enable network monitoring
    await cdp("Network.enable")
    # Navigate to talk backup page
    await cdp("Page.navigate", {"url": "https://talkcloud.kakao.com/talk"})
    
    print("🔍 Monitoring network after navigating to /talk ...")
    deadline = asyncio.get_event_loop().time() + 20
    
    while asyncio.get_event_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            data = json.loads(raw)
            method = data.get("method", "")
            
            if method == "Network.requestWillBeSent":
                req = data["params"]["request"]
                url = req["url"]
                if "kakao" in url and not any(x in url for x in [".js", ".css", ".png", ".jpg", ".svg", ".woff", "tiara", "daumcdn"]):
                    entry = {
                        "requestId": data["params"]["requestId"],
                        "method": req["method"],
                        "url": url,
                        "headers": dict(req.get("headers", {})),
                    }
                    if req.get("postData"):
                        entry["postData"] = req["postData"]
                    captured.append(entry)
                    print(f"  📡 {req['method']} {url}")
                    
            elif method == "Network.responseReceived":
                rid = data["params"]["requestId"]
                resp = data["params"]["response"]
                for c in captured:
                    if c["requestId"] == rid:
                        c["status"] = resp["status"]
                        c["responseHeaders"] = dict(resp.get("headers", {}))
                        # Try to get response body
                        break
                        
        except asyncio.TimeoutError:
            pass
    
    # Get response bodies
    for c in captured:
        try:
            msg_id[0] += 1
            await ws.send(json.dumps({
                "id": msg_id[0],
                "method": "Network.getResponseBody",
                "params": {"requestId": c["requestId"]}
            }))
            while True:
                raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                if raw.get("id") == msg_id[0]:
                    body = raw.get("result", {}).get("body", "")
                    c["responseBody"] = body[:2000]
                    break
        except:
            pass
    
    print(f"\n📋 Total captured: {len(captured)} requests")
    for c in captured:
        print(f"\n  {c['method']} {c['url']}")
        if "responseBody" in c:
            print(f"  → {c['responseBody'][:300]}")
    
    with open("data/nav_capture.json", "w") as f:
        json.dump(captured, f, ensure_ascii=False, indent=2)
    
    await ws.close()
    print("\n💾 Saved to data/nav_capture.json")

asyncio.run(main())
