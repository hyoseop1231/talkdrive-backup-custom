# TalkCloud Web API Encrypted Endpoint Analysis

## Status: Preliminary (explored)

## Overview

The TalkCloud web interface at `talkcloud.kakao.com` provides access to media,
files, and links but NOT to encrypted chat message backups. This document
records findings from API exploration attempts.

## Endpoints Tested

### Accessible (metadata only)

| Endpoint | Result |
|----------|--------|
| `/backup/info` | Returns backup stats (chat count, log count, timestamps) |
| `/chat/list?verticalType=MEDIA` | Chat rooms with media metadata |
| `/chat/list?verticalType=FILE` | Chat rooms with file metadata |
| `/chat/list?verticalType=LINK` | Chat rooms with link metadata |
| `/mediaFile/list` | Full media file list with download URLs |
| `/link/list` | Shared links with metadata |

### Blocked / No Data

| Endpoint | Result |
|----------|--------|
| `/backup/chatRoom/list` | Error / blocked |
| `/backup/chatLog/list` | Error / blocked |
| `/chat/encrypted/{chatId}` | Error / blocked |
| `/chatLog/list` | Error / blocked |
| Various `/v2/backup/*` | Error / blocked |

## Key Finding

The backup system has 18,222 encrypted chat messages stored server-side,
but the web API intentionally restricts access to message content.
The restore flow is:

1. Mobile app requests restore
2. Server decrypts and pushes to device
3. No web-accessible decryption endpoint exists

## Data Available via Web API

- Media metadata: 7,597+ items (images, videos) with download URLs
- Files: 5,088+ items with download URLs
- Links: 1,623+ items with full metadata
- Friend list, contact backups, chatroom structure
- Profile images, chatbot subscriptions

## Data NOT Available via Web API

- Chat message text (encrypted backup)
- Message read receipts
- Voice/video call history
- Deleted message history

## Conclusion

Web API extraction is limited to metadata and media files.
For actual chat message text, device-side extraction (Android SQLCipher
or iOS backup) is the only viable approach.
