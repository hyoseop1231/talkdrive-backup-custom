# macOS KakaoTalk DB Decryption (Verified)

macOS 카카오톡 앱의 로컬 SQLCipher DB를 복호화하여 전체 채팅 메시지를 추출하는 방법.

**상태: VERIFIED** - 2026-02-03 실제 테스트 완료 (18,620 메시지, 27 채팅방)

## Prerequisites

```bash
# 1. SQLCipher 설치
brew install sqlcipher

# 2. pysqlcipher3 설치 (SQLCipher 헤더 경로 지정 필요)
C_INCLUDE_PATH=$(brew --prefix sqlcipher)/include \
  LIBRARY_PATH=$(brew --prefix sqlcipher)/lib \
  pip install pysqlcipher3

# 3. Python 3.10+
python --version  # >= 3.10 필요
```

## 개요

macOS 카카오톡(`com.kakao.KakaoTalkMac`)은 채팅 메시지를 SQLCipher로 암호화된
로컬 SQLite DB에 저장한다. 복호화에 필요한 두 가지 값:

1. **deviceUUID** - macOS의 `IOPlatformUUID` (하드웨어 고유값)
2. **userId** - 카카오톡 사용자 ID (숫자)

이 두 값으로 **DB 파일명**과 **복호화 키**를 유도(derive)할 수 있다.

## Step 1: deviceUUID 획득

```bash
ioreg -d2 -c IOPlatformExpertDevice | grep IOPlatformUUID
```

출력 예시:
```
"IOPlatformUUID" = "554BBCDB-F13D-5C81-BF26-0E7D16DFDD46"
```

## Step 2: userId 찾기

userId는 직접 저장되어 있지 않다. 대신 카카오톡 plist에 `SHA512(str(userId))`가
디렉토리명으로 사용되므로, 브루트포스로 역산한다.

### 2-1. SHA512 타겟 해시 추출

```bash
# plist에서 DESIGNATEDFRIENDSREVISION 키의 128자리 hex 해시 추출
plutil -p ~/Library/Containers/com.kakao.KakaoTalkMac/Data/Library/Preferences/com.kakao.KakaoTalkMac.*.plist \
  | grep DESIGNATEDFRIENDSREVISION
```

### 2-2. 브루트포스

0 ~ 500,000,000 범위에서 `SHA512(str(n))`이 타겟 해시와 일치하는 n을 찾는다.
멀티코어 병렬 처리 시 10~30초 소요.

```python
import hashlib
import multiprocessing

def search_chunk(args):
    start, end, target = args
    for uid in range(start, end):
        if hashlib.sha512(str(uid).encode()).hexdigest() == target:
            return uid
    return None

# 5M 단위로 분할, CPU 전체 코어 사용
chunk = 5_000_000
max_id = 500_000_000
ranges = [(i, min(i + chunk, max_id), target_hash) for i in range(0, max_id, chunk)]

with multiprocessing.Pool() as pool:
    for result in pool.imap_unordered(search_chunk, ranges):
        if result is not None:
            print(f"userId = {result}")
            pool.terminate()
            break
```

## Step 3: Key Derivation

### 공통 함수

```python
import hashlib
import base64

def pbkdf2(password: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password, salt, 100_000, 128)

def hashed_device_uuid(uuid: str) -> str:
    uuid_bytes = uuid.encode("ascii")
    combined = hashlib.sha1(uuid_bytes).digest() + hashlib.sha256(uuid_bytes).digest()
    return base64.b64encode(combined).decode("ascii")
```

### DB 파일명 유도

```python
def get_database_name(user_id: int, uuid: str) -> str:
    payload = ".".join([".", "F", str(user_id), "A", "F", "".join(reversed(uuid)), ".", "|"])
    salt = "".join(reversed(hashed_device_uuid(uuid))).encode("ascii")
    return pbkdf2(payload.encode("ascii"), salt).hex()[28:28 + 78]
```

- PBKDF2-HMAC-SHA256, 100,000 iterations, 128바이트 출력
- 결과 hex의 28번째부터 78자리가 DB 파일명

### SecureKey 유도 (복호화 키)

```python
def get_secure_key(user_id: int, uuid: str) -> str:
    hashed = hashed_device_uuid(uuid)
    payload = "F".join(["A", hashed, "|", "F", uuid[:5], "H", str(user_id), "|", uuid[7:]])
    salt = uuid[int(len(uuid) * 0.3):].encode("ascii")
    return pbkdf2("".join(reversed(payload)).encode("ascii"), salt).hex()
```

## Step 4: DB 열기

```python
from pysqlcipher3 import dbapi2 as sqlite

db_path = f"~/Library/Containers/com.kakao.KakaoTalkMac/Data/Library/Application Support/com.kakao.KakaoTalkMac/{db_name}"

conn = sqlite.connect(db_path)
conn.execute(f"PRAGMA key = '{secure_key}'")
conn.execute("PRAGMA cipher_compatibility = 3")  # 필수!

# 검증
conn.execute("SELECT count(*) FROM sqlite_master")
```

**주의**: `cipher_compatibility = 3`이 반드시 필요하다. 이 설정 없이는 복호화 실패.

## DB Schema

### NTChatMessage (메시지)

| Column | Type | Description |
|--------|------|-------------|
| chatId | INTEGER | 채팅방 ID |
| logId | INTEGER | 메시지 고유 ID |
| prevId | INTEGER | 이전 메시지 ID |
| msgId | TEXT | 메시지 식별자 |
| authorId | INTEGER | 작성자 userId |
| type | INTEGER | 메시지 타입 코드 |
| status | INTEGER | 전송 상태 |
| message | TEXT | 메시지 본문 |
| attachment | TEXT | 첨부 JSON |
| supplement | TEXT | 보충 데이터 |
| sentAt | INTEGER | Unix timestamp |
| localFilePath | TEXT | 로컬 파일 경로 |

### NTChatRoom (채팅방)

| Column | Type | Description |
|--------|------|-------------|
| chatId | INTEGER | 채팅방 ID (PK) |
| linkId | INTEGER | 링크 ID |
| type | INTEGER | 채팅방 타입 |
| chatName | TEXT | 채팅방 이름 |
| activeMembersCount | INTEGER | 활성 멤버 수 |
| displayMemberIds | TEXT | 표시 멤버 목록 |
| fullImageUrl | TEXT | 프로필 이미지 URL |

### NTUser (사용자)

| Column | Type | Description |
|--------|------|-------------|
| userId | INTEGER | 사용자 ID (PK) |
| accountId | INTEGER | 계정 ID |
| nickName | TEXT | 닉네임 |
| friendNickName | TEXT | 친구 설정 닉네임 |
| displayName | TEXT | 표시 이름 |
| profileImageUrl | TEXT | 프로필 이미지 URL |
| friendType | INTEGER | 친구 타입 |
| userType | INTEGER | 사용자 타입 |

## Message Type Codes

| Code | Type | Description |
|------|------|-------------|
| 0 | feed/system | 시스템 메시지 (입장, 퇴장 등) |
| 1 | text | 일반 텍스트 |
| 2 | photo | 사진 |
| 3 | video | 동영상 |
| 12 | voice | 음성 메시지 |
| 13 | map | 지도/위치 |
| 16 | sticker | 스티커 |
| 18 | file | 파일 |
| 20 | contact | 연락처 |
| 24 | schedule | 일정 |
| 26 | reply | 답장 |
| 27 | shareable | 공유 콘텐츠 |
| 51 | emoticon | 이모티콘 |
| 71 | voicechat | 보이스톡 |
| 72 | long_text | 긴 텍스트 |
| 16385 | long_text_v2 | 긴 텍스트 v2 |
| 16402 | file_v2 | 파일 v2 |

## CLI 사용법

통합 스크립트 `scripts/decrypt_macos_db.py`:

```bash
# 기본: 통계 표시 (자동 감지)
python scripts/decrypt_macos_db.py

# JSON으로 전체 메시지 내보내기
python scripts/decrypt_macos_db.py --export data/kakaotalk_messages.json

# 특정 채팅방만 내보내기
python scripts/decrypt_macos_db.py --export data/chat.json --chat-id 163787201460229

# 커스텀 SQL 쿼리
python scripts/decrypt_macos_db.py --query "SELECT count(*) FROM NTChatMessage"

# userId를 이미 알고 있을 때 (브루트포스 생략)
python scripts/decrypt_macos_db.py --user-id 236788016

# 통계를 JSON으로 저장
python scripts/decrypt_macos_db.py --stats-json data/db_stats.json
```

## Export JSON 구조

```json
{
  "exported_at": "2026-02-03T15:30:00",
  "total": 18620,
  "chatrooms": {
    "163787201460229": {
      "chatName": "채팅방 이름",
      "members": 3,
      "messages": [
        {
          "chatId": 163787201460229,
          "logId": 123456789,
          "author": "홍길동",
          "authorId": 236788016,
          "type": "text",
          "typeCode": 1,
          "message": "안녕하세요",
          "attachment": null,
          "sentAt": "2024-01-15 14:30:00",
          "sentAtUnix": 1705312200
        }
      ]
    }
  }
}
```

## 유용한 SQL 쿼리

```sql
-- 전체 메시지 수
SELECT count(*) FROM NTChatMessage;

-- 채팅방별 메시지 수
SELECT r.chatName, count(m.logId) as cnt
FROM NTChatRoom r
LEFT JOIN NTChatMessage m ON r.chatId = m.chatId
GROUP BY r.chatId ORDER BY cnt DESC;

-- 특정 사용자의 메시지
SELECT m.message, datetime(m.sentAt, 'unixepoch', 'localtime') as time
FROM NTChatMessage m
JOIN NTUser u ON m.authorId = u.userId
WHERE u.friendNickName = '홍길동'
ORDER BY m.sentAt DESC LIMIT 20;

-- 메시지 타입별 통계
SELECT type, count(*) as cnt FROM NTChatMessage GROUP BY type ORDER BY cnt DESC;

-- 날짜 범위 조회
SELECT datetime(min(sentAt), 'unixepoch', 'localtime') as first,
       datetime(max(sentAt), 'unixepoch', 'localtime') as last
FROM NTChatMessage WHERE sentAt > 0;

-- 특정 키워드 검색
SELECT m.message, u.friendNickName, datetime(m.sentAt, 'unixepoch', 'localtime')
FROM NTChatMessage m
JOIN NTUser u ON m.authorId = u.userId
WHERE m.message LIKE '%검색어%'
ORDER BY m.sentAt DESC;
```

## Troubleshooting

### "file is not a database"
- `PRAGMA cipher_compatibility = 3` 누락 확인
- SecureKey가 올바른지 확인 (userId, UUID 정확히 입력)

### pysqlcipher3 설치 실패
```bash
# brew로 sqlcipher 설치 후 헤더 경로 명시
brew install sqlcipher
C_INCLUDE_PATH=$(brew --prefix sqlcipher)/include \
  LIBRARY_PATH=$(brew --prefix sqlcipher)/lib \
  pip install pysqlcipher3
```

### userId 브루트포스가 결과 없음
- plist 경로 확인: `~/Library/Containers/com.kakao.KakaoTalkMac/Data/Library/Preferences/`
- 카카오톡 Mac에 로그인되어 있는지 확인
- `--user-id` 옵션으로 직접 지정 시도

### DB 파일을 찾을 수 없음
- DB 경로: `~/Library/Containers/com.kakao.KakaoTalkMac/Data/Library/Application Support/com.kakao.KakaoTalkMac/`
- 해당 디렉토리에 긴 hex 문자열 파일명이 있어야 함

## References

- Key derivation algorithm: blluv's gist (GitHub)
- SQLCipher: https://www.zetetic.net/sqlcipher/
- pysqlcipher3: https://github.com/rigglemania/pysqlcipher3
