#!/bin/bash
# 카카오톡 로컬 DB → messages.json 추출 → Neo4j 동기화
# Cron: 0 */6 * * * ~/Development/talkdrive-backup/scripts/periodic_kakao_msg_sync.sh

set -e
cd ~/Development/talkdrive-backup

LOG_FILE="output/kakao_msg_sync.log"
LOCK_FILE="/tmp/kakao_msg_sync.lock"
SUCCESS_FILE="output/kakao_sync_last_success.txt"

# 중복 실행 방지
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "[$(date)] 이미 실행 중 (PID: $PID)" >> "$LOG_FILE"
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

echo "========================================" >> "$LOG_FILE"
echo "[$(date)] 🔄 카카오 메시지 동기화 시작" >> "$LOG_FILE"

# 1. DB 복호화 + 메시지 추출
echo "[$(date)]    DB 복호화 중..." >> "$LOG_FILE"
.venv/bin/python3 scripts/decrypt_macos_db.py --user-id 236788016 --export data/messages.json >> "$LOG_FILE" 2>&1

# 2. Neo4j 동기화
echo "[$(date)]    Neo4j 동기화 중..." >> "$LOG_FILE"
.venv/bin/python3 scripts/sync_local_to_neo4j.py >> "$LOG_FILE" 2>&1

# 3. 성공 타임스탬프 기록
date -Iseconds > "$SUCCESS_FILE"

echo "[$(date)] ✅ 카카오 메시지 동기화 완료" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
