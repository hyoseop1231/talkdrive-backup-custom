# KakaoTalk Chat Decryption Research

Status dashboard for efforts to access encrypted KakaoTalk chat backup data.

## Context

KakaoTalk's TalkCloud stores 18,222+ encrypted chat messages that are only
restorable via the mobile app. The web API (`drawer-api.kakao.com`) provides
metadata (media, files, links) but not message text.

However, **macOS 카카오톡 로컬 DB 복호화에 성공**하여 전체 메시지 추출이 가능해졌다.

## Research Tracks

| # | Track | Approach | Status | Details |
|---|-------|----------|--------|---------|
| 1 | Android SQLCipher | IMEI + userId key derivation for KakaoTalk2.db | Not started | [android_sqlcipher.md](android_sqlcipher.md) |
| 2 | iOS Backup | iTunes/Finder backup container extraction | Not started | [ios_backup.md](ios_backup.md) |
| 3 | TalkCloud Encrypted | Web API `/chat/encrypted/` endpoint analysis | Blocked | [talkcloud_encrypted.md](talkcloud_encrypted.md) |
| 4 | **macOS SQLCipher** | deviceUUID + userId key derivation | **VERIFIED** | [macos_sqlcipher.md](macos_sqlcipher.md) |

## Verified: macOS DB Decryption (Track 4)

**2026-02-03 테스트 결과:**

- 메시지: 18,620개
- 채팅방: 27개
- 사용자: 110명
- 기간: 2018-01-16 ~ 2026-02-03
- 스크립트: `scripts/decrypt_macos_db.py`

상세 문서: [macos_sqlcipher.md](macos_sqlcipher.md)

## Summary of Known Facts

- Backup email: configured for cloud backup
- Backup chat count: 31 rooms
- Backup log count: 18,222 messages (TalkCloud)
- macOS local DB: **18,620 messages (DECRYPTED)**
- Last backup: 2025-01-29
- Web API access to messages: **BLOCKED**
- macOS local DB access: **WORKING**

## Next Steps

1. ~~Root an Android device or use emulator to extract KakaoTalk2.db~~
2. ~~Research SQLCipher key derivation (IMEI-based)~~
3. ~~Test iOS backup extraction via libimobiledevice~~
4. (Optional) Android KakaoTalk2.db 복호화 연구 - IMEI 기반 키 유도
5. (Optional) 정기 백업 자동화 (cron + decrypt_macos_db.py --export)
