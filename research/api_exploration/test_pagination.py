#!/usr/bin/env python3
"""TalkCloud backup message API exploration"""
import asyncio, json, aiohttp, websockets

async def main():
    async with aiohttp.ClientSession() as s:
        async with s.get("http://localhost:18792/json") as r:
            tabs = await r.json()
    
    tab = next(t for t in tabs if 'talkcloud' in t.get('url', ''))
    ws = await websockets.connect(tab['webSocketDebuggerUrl'], max_size=50*1024*1024)
    msg_id = [0]
    
    async def cdp(method, params=None):
        msg_id[0] += 1
        m = {'id': msg_id[0], 'method': method}
        if params: m['params'] = params
        await ws.send(json.dumps(m))
        while True:
            resp = json.loads(await ws.recv())
            if resp.get('id') == msg_id[0]:
                return resp
    
    await cdp("Network.enable")
    
    result = await cdp("Runtime.evaluate", {
        "expression": """
            (async () => {
                const results = [];
                
                // Page 1
                const r1 = await window.__axios.get('https://drawer-api.kakao.com/mediaFile/list', {
                    params: {verticalType: 'MEDIA', fetchCount: 3, joined: true, direction: 'DESC'},
                    headers: {'Accept': 'application/json+javascript'},
                    withCredentials: true
                });
                results.push({page: 1, hasMore: r1.data.hasMore, count: r1.data.items.length, totalCount: r1.data.totalCount});
                
                if (r1.data.items.length > 0) {
                    const last = r1.data.items[r1.data.items.length - 1];
                    
                    // Try offset parameter
                    try {
                        const r2 = await window.__axios.get('https://drawer-api.kakao.com/mediaFile/list', {
                            params: {
                                verticalType: 'MEDIA',
                                fetchCount: 2,
                                joined: true,
                                direction: 'DESC',
                                offset: 3
                            },
                            headers: {'Accept': 'application/json+javascript'},
                            withCredentials: true
                        });
                        results.push({
                            method: 'offset=3',
                            hasMore: r2.data.hasMore,
                            count: r2.data.items.length,
                            sameFirst: r2.data.items[0]?.id === r1.data.items[0]?.id
                        });
                    } catch (e) {
                        results.push({method: 'offset=3', error: e.message});
                    }
                }
                
                // Same for links
                const l1 = await window.__axios.get('https://drawer-api.kakao.com/link/list', {
                    params: {verticalType: 'LINK', fetchCount: 3, direction: 'DESC'},
                    headers: {'Accept': 'application/json+javascript'},
                    withCredentials: true
                });
                results.push({page: 'link-1', hasMore: l1.data.hasMore, count: l1.data.items.length});
                
                if (l1.data.items.length > 0) {
                    const last = l1.data.items[l1.data.items.length - 1];
                    try {
                        const l2 = await window.__axios.get('https://drawer-api.kakao.com/link/list', {
                            params: {
                                verticalType: 'LINK',
                                fetchCount: 2,
                                direction: 'DESC',
                                offset: 3
                            },
                            headers: {'Accept': 'application/json+javascript'},
                            withCredentials: true
                        });
                        results.push({
                            method: 'link-offset=3',
                            hasMore: l2.data.hasMore,
                            count: l2.data.items.length,
                            sameFirst: l2.data.items[0]?.id === l1.data.items[0]?.id
                        });
                    } catch (e) {
                        results.push({method: 'link-offset=3', error: e.message});
                    }
                }
                
                return results;
            })()
        """,
        "returnByValue": True,
        "awaitPromise": True,
    })
    
    await ws.close()
    
    print(json.dumps(result['result']['result']['value'], indent=2))

asyncio.run(main())
