# API Exploration Scripts

Non-production research scripts used to reverse-engineer the Kakao TalkCloud web API.
These scripts helped discover undocumented endpoints, pagination behavior, and
encrypted backup limitations.

## Scripts

| Script | Purpose |
|--------|---------|
| `explore_backup.py` | Probe backup-related endpoints (`/backup/chatLog/list`, etc.) |
| `probe_warehouse.py` | Discover `/warehouse/` API family, `/chatInfo` POST, content endpoints |
| `sniff_nav.py` | CDP Network monitoring during page navigation to `/talk` |
| `sniff_network.py` | Install fetch/XHR interceptors to capture all API calls |
| `test_pagination.py` | Test pagination parameters: `cursor`, `offset`, `lastDrawerId` |

## Prerequisites

- Chrome running with `--remote-debugging-port=18792`
- Logged into `talkcloud.kakao.com`
- Python packages: `websockets`, `aiohttp`

## Key Findings

1. **Pagination**: Drawer API uses `drawerId`-based offset, not numeric page numbers
2. **Encrypted backup**: 18,222 messages are encrypted; `/chat/encrypted/{chatId}` blocked
3. **Media access**: Direct URL download with `?attach` parameter; cookies required
4. **Content types**: MEDIA, FILE, LINK each have separate list endpoints
5. **Warehouse API**: Per-chat content lists exist but require specific chatId
