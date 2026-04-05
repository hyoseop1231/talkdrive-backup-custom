# Android KakaoTalk2.db (SQLCipher) Analysis

## Status: Not started

## Overview

KakaoTalk on Android stores chat history in an encrypted SQLite database
(`KakaoTalk2.db`) using SQLCipher. The encryption key is derived from
device-specific and user-specific identifiers.

## Database Location

```
/data/data/com.kakao.talk/databases/KakaoTalk2.db
```

Requires root access or ADB backup extraction.

## Known Key Derivation

Based on community research, the SQLCipher passphrase is derived from:

- **IMEI** (or MEID) of the device
- **userId** (KakaoTalk internal user ID, numeric)

Possible formula (unverified):
```
key = some_hash(IMEI + userId)
```

## Tables of Interest

- `chat_logs` - Message text, timestamps, sender
- `chat_room` - Room metadata, member lists
- `friends` - Contact information

## Requirements

1. Rooted Android device or emulator with KakaoTalk installed
2. ADB access to pull database file
3. IMEI of the specific device used for backup
4. KakaoTalk userId (available from TalkCloud API)

## Risks

- Key derivation formula may have changed across app versions
- Database schema varies between KakaoTalk versions
- Root detection in newer KakaoTalk versions

## References

- SQLCipher documentation
- Community reverse-engineering efforts (search: kakaotalk db decrypt)
