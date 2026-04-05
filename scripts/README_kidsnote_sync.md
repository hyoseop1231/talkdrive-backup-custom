# KidsNote → Neo4j 동기화 가이드

## 개요
KidsNote(키즈노트) 데이터를 Neo4j 온톨로지에 동기화하는 2단계 프로세스

## 파일 구조
```
~/Development/talkdrive-backup/scripts/
├── export_kidsnote_data.py    # NAS Docker에서 실행 (API → JSON)
└── sync_kidsnote_to_neo4j.py  # 맥프로에서 실행 (JSON → Neo4j)
```

---

## 1단계: Export (NAS Docker)

### 실행 방법
```bash
# NAS(10.0.0.20)에 SSH 접속
ssh hyoseop1231@10.0.0.20

# Docker 컨테이너 내에서 실행
docker exec -it smartkids-cron python3 /app/scripts/export_kidsnote_data.py
```

### docker-compose.yml 설정 추가
```yaml
services:
  smartkids-cron:
    volumes:
      - ./scripts:/app/scripts
      - ./output:/app/output
```

### 출력 파일
- `/app/output/kidsnote_export.json` (Docker 남부)
- NAS에서 맥프로로 복사 필요

---

## 2단계: Sync (맥프로)

### 사전 준비
```bash
# JSON 파일을 맥프로로 복사
scp hyoseop1231@10.0.0.20:~/smart-kids-diary/output/kidsnote_export.json \
   ~/Development/talkdrive-backup/data/
```

### 실행
```bash
# 가상환경 활성화
source ~/Development/Kitech_mail/.venv/bin/activate

# 동기화 실행
python3 ~/Development/talkdrive-backup/scripts/sync_kidsnote_to_neo4j.py
```

---

## Neo4j 온톨로지 구조

### 노드
| 타입 | ID 패턴 | 속성 |
|------|---------|------|
| `kidsnote_child` | `kidsnote_child:{id}` | name, birth_date, gender, order, role |
| `kidsnote_report` | `kidsnote_report:{id}` | date, text, author_name, class_name, child_id |
| `kidsnote_album` | `kidsnote_album:{id}` | date, title, image_count, child_id |
| `kidsnote_teacher` | `kidsnote_teacher:{id}` | name, center_id |
| `kidsnote_center` | `kidsnote_center:{id}` | name, address, phone |

### 관계
```
(kidsnote_child)-[:CHILD_OF]->(person:hyoseop1231@kitech.re.kr)
(kidsnote_child)-[:CHILD_OF]->(person:pbm0221@naver.com)
(kidsnote_report)-[:ABOUT]->(kidsnote_child)
(kidsnote_report)-[:WRITTEN_BY]->(kidsnote_teacher)
(kidsnote_album)-[:ABOUT]->(kidsnote_child)
(kidsnote_child)-[:ATTENDS]->(kidsnote_center)
(person:pbm0221@naver.com)-[:SAME_AS]->(kakao_local_user:228084491)
```

---

## 자동화 (선택)

### cron 설정 (NAS)
```bash
# 매일 새벽 2시에 export
0 2 * * * docker exec smartkids-cron python3 /app/scripts/export_kidsnote_data.py
```

### cron 설정 (맥프로)
```bash
# 매일 새벽 3시에 sync (NAS export 후)
0 3 * * * source ~/Development/Kitech_mail/.venv/bin/activate && \
          python3 ~/Development/talkdrive-backup/scripts/sync_kidsnote_to_neo4j.py
```

---

## 확인 쿼리

```cypher
// 아이 정보 확인
MATCH (c:kidsnote_child) RETURN c

// 알림장과 작성자 확인
MATCH (r:kidsnote_report)-[:WRITTEN_BY]->(t:kidsnote_teacher)
RETURN r.date, r.text[0..50], t.name

// 엄마 노드 SAME_AS 확인
MATCH (m:person {id: 'person:pbm0221@naver.com'})-[:SAME_AS]-(other)
RETURN m, other
```