#!/usr/bin/env python3
"""
톡클라우드 웹앱이 실제로 어떤 API를 호출하는지 네트워크 스니핑
CDP Network domain 활용
"""
import asyncio, json
import aiohttp, websockets

CHROME_DEBUG_URL = "http://localhost:18792"

async def sniff():
    # 1. 탭 목록
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{CHROME_DEBUG_URL}/json") as r:
            tabs = await r.json()

    tab = None
    for t in tabs:
        if "talkcloud" in t.get("url", ""):
            tab = t
            break
    if not tab:
        tab = next(t for t in tabs if t.get("type") == "page")

    print(f"Tab: {tab['title']} - {tab['url']}")
    ws = await websockets.connect(tab["webSocketDebuggerUrl"], max_size=50*1024*1024)

    msg_id = 0
    async def send_cdp(method, params=None):
        nonlocal msg_id
        msg_id += 1
        m = {"id": msg_id, "method": method}
        if params: m["params"] = params
        await ws.send(json.dumps(m))
        while True:
            resp = json.loads(await ws.recv())
            if resp.get("id") == msg_id:
                return resp
            # Event - check if it's a network event
            if "method" in resp and resp["method"].startswith("Network."):
                yield_event(resp)

    events = []
    def yield_event(evt):
        method = evt.get("method", "")
        params = evt.get("params", {})
        if method == "Network.requestWillBeSent":
            url = params.get("request", {}).get("url", "")
            req_method = params.get("request", {}).get("method", "GET")
            if "kakao" in url or "talkcloud" in url:
                rid = params.get("requestId")
                events.append({"requestId": rid, "method": req_method, "url": url})
                print(f"  📡 {req_method} {url}")

    # Enable Network monitoring
    msg_id += 1
    await ws.send(json.dumps({"id": msg_id, "method": "Network.enable"}))

    print("\n🔍 Listening for 30 seconds... Navigate to backup page in browser!")
    print("   (Go to talkcloud.kakao.com → 대화 백업 section)")

    # Also navigate to backup page programmatically
    msg_id += 1
    await ws.send(json.dumps({
        "id": msg_id, "method": "Page.enable"
    }))

    # Try navigating to backup
    msg_id += 1
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": """
                // Try clicking the backup tab or navigating
                // First, let's see what APIs the page uses
                (function() {
                    // Intercept fetch
                    const origFetch = window.fetch;
                    window.__apiCalls = window.__apiCalls || [];
                    window.fetch = function(...args) {
                        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
                        if (url) window.__apiCalls.push({type: 'fetch', url, method: args[1]?.method || 'GET'});
                        return origFetch.apply(this, args);
                    };

                    // Intercept XMLHttpRequest
                    const origOpen = XMLHttpRequest.prototype.open;
                    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                        window.__apiCalls.push({type: 'xhr', url, method});
                        return origOpen.call(this, method, url, ...rest);
                    };

                    return 'Interceptors installed';
                })()
            """,
            "returnByValue": True
        }
    }))

    # Listen for events
    deadline = asyncio.get_event_loop().time() + 15
    while asyncio.get_event_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1)
            data = json.loads(raw)
            if "method" in data:
                yield_event(data)
        except asyncio.TimeoutError:
            pass

    # Grab intercepted calls
    msg_id += 1
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": "JSON.stringify(window.__apiCalls || [])",
            "returnByValue": True
        }
    }))
    while True:
        raw = json.loads(await ws.recv())
        if raw.get("id") == msg_id:
            val = raw.get("result", {}).get("result", {}).get("value", "[]")
            intercepted = json.loads(val) if isinstance(val, str) else val
            break

    print(f"\n📋 Intercepted {len(intercepted)} API calls:")
    for call in intercepted:
        print(f"  {call['method']} {call['url']}")

    print(f"\n📋 Network events: {len(events)}")
    for e in events:
        print(f"  {e['method']} {e['url']}")

    # Now check what JS sources/routes the app has
    msg_id += 1
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": """
                (function() {
                    // Get all script sources
                    const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
                    // Get current URL hash/path
                    return JSON.stringify({
                        scripts: scripts,
                        href: location.href,
                        hash: location.hash,
                        pathname: location.pathname
                    });
                })()
            """,
            "returnByValue": True
        }
    }))
    while True:
        raw = json.loads(await ws.recv())
        if raw.get("id") == msg_id:
            val = raw.get("result", {}).get("result", {}).get("value", "{}")
            page_info = json.loads(val) if isinstance(val, str) else val
            print(f"\n📄 Page info:")
            print(json.dumps(page_info, indent=2))
            break

    all_data = {"events": events, "intercepted": intercepted, "page_info": page_info}
    with open("data/network_sniff.json", "w") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    await ws.close()
    print("\n💾 Saved to data/network_sniff.json")

asyncio.run(sniff())
