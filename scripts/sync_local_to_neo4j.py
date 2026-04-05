#!/usr/bin/env python3
"""
카카오톡 로컬 DB JSON 데이터 → Neo4j 동기화

입력 파일:
- users.json: KakaoTalk 유저 목록
- chatrooms.json: 채팅방 목록
- messages.json: 메시지 목록

노드 타입:
- kakao_local_user (type 프로퍼티로 구분, :Entity 라벨)
- kakao_local_chatroom (type 프로퍼티로 구분, :Entity 라벨)
- kakao_local_message (type 프로퍼티로 구분, :Entity 라벨)

관계 타입:
- MEMBER_OF (User → ChatRoom)
- SENT (User → Message)
- IN_ROOM (Message → ChatRoom)
- SAME_AS (kakao_local_user → kakao_user, 매칭 시)
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Any
from neo4j import GraphDatabase

# Load .env manually
def load_env_file(env_path: Path):
    """Manually load .env file"""
    if not env_path.exists():
        return
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

# Load .env from Kitech_mail
load_env_file(Path.home() / "Development" / "Kitech_mail" / ".env")


def sanitize_properties(props: dict[str, Any]) -> dict[str, Any]:
    """
    Neo4j에 저장 가능한 primitive 타입으로 properties 변환.
    dict/list 타입은 JSON 문자열로 변환.
    """
    sanitized: dict[str, Any] = {}
    for k, v in props.items():
        if isinstance(v, dict):
            sanitized[k] = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, list):
            if v and any(isinstance(item, dict) for item in v):
                sanitized[k] = json.dumps(v, ensure_ascii=False)
            else:
                sanitized[k] = v
        elif isinstance(v, bool):
            sanitized[k] = str(v).lower()
        elif v is None:
            continue
        else:
            sanitized[k] = v
    return sanitized


def unix_to_iso(unix_timestamp: int | None) -> str | None:
    """Unix timestamp를 ISO 8601 datetime string으로 변환"""
    if unix_timestamp is None or unix_timestamp == 0:
        return None
    try:
        return datetime.fromtimestamp(unix_timestamp).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


class KakaoLocalSync:
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.password = os.getenv("NEO4J_PASSWORD", "CHANGE_ME_PASSWORD")
        
        self.driver = GraphDatabase.driver(self.uri, auth=("neo4j", self.password))
        self.data_dir = Path.home() / "Development" / "talkdrive-backup" / "data"
        self.batch_size = 100
        
        # 통계
        self.stats = {
            'users': 0,
            'chatrooms': 0,
            'messages': 0,
            'member_of_edges': 0,
            'sent_edges': 0,
            'in_room_edges': 0,
            'same_as_edges': 0
        }
    
    def close(self):
        """Neo4j 연결 종료"""
        if self.driver:
            self.driver.close()
    
    def load_json(self, filename: str, flatten_messages: bool = False) -> list[dict] | dict:
        """
        JSON 파일 로드

        Args:
            filename: JSON 파일명
            flatten_messages: True인 경우, messages.json의 chatrooms 구조를 플랫 리스트로 변환

        Returns:
            로드된 JSON 데이터 (dict 또는 list)
        """
        filepath = self.data_dir / filename
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # messages.json의 경우 chatrooms 구조를 플랫 리스트로 변환
        if flatten_messages and filename == 'messages.json' and isinstance(data, dict):
            # 구조 1: { "chatrooms": { chatroom_id: { messages: [...] } } }
            if 'chatrooms' in data:
                messages = []
                for chatroom_id, room_data in data.get('chatrooms', {}).items():
                    messages.extend(room_data.get('messages', []))
                print(f"   messages.json: {len(messages):,}개 (chatrooms 구조에서 플랫 리스트로 변환)")
                return messages
            # 구조 2: 이미 플랫 리스트인 경우 그대로 반환
            elif isinstance(data, list):
                print(f"   messages.json: {len(data):,}개 (이미 플랫 리스트 구조)")
                return data

        return data
    
    def init_schema(self):
        """Neo4j 스키마 초기화 (인덱스/제약조건)"""
        with self.driver.session() as session:
            # Entity ID 유니크 제약조건
            session.run("""
                CREATE CONSTRAINT kakao_local_entity_id IF NOT EXISTS
                FOR (e:Entity) REQUIRE e.id IS UNIQUE
            """)
            # type 인덱스
            session.run("""
                CREATE INDEX kakao_local_entity_type IF NOT EXISTS
                FOR (e:Entity) ON (e.type)
            """)
            print("✅ 스키마 초기화 완료")
    
    def sync_users(self, users: list[dict]):
        """Users 동기화"""
        print(f"\n👤 Users 동기화 중... (총 {len(users):,}명)")
        
        with self.driver.session() as session:
            for i in range(0, len(users), self.batch_size):
                batch = users[i:i + self.batch_size]
                
                # 배치 데이터 준비
                user_data = []
                for user in batch:
                    user_id = user.get('userId')
                    if not user_id:
                        continue
                    
                    # 프로퍼티 구성
                    properties = {
                        'nickName': user.get('nickName', ''),
                        'friendNickName': user.get('friendNickName', ''),
                        'displayName': user.get('displayName', ''),
                        'profileImageUrl': user.get('profileImageUrl', ''),
                        'statusMessage': user.get('statusMessage', '')
                    }
                    
                    user_data.append({
                        'id': f"kakao_local_user:{user_id}",
                        'type': 'kakao_local_user',
                        'user_id': user_id,
                        'properties': sanitize_properties(properties)
                    })
                
                # UNWIND로 배치 삽입 (새 노드만 CREATE)
                result = session.run("""
                    UNWIND $users AS user
                    OPTIONAL MATCH (existing:Entity {id: user.id})
                    WITH user, existing
                    WHERE existing IS NULL
                    CREATE (e:Entity {id: user.id})
                    SET e.type = user.type,
                        e.user_id = user.user_id,
                        e += user.properties
                    RETURN count(e) AS new_count
                """, users=user_data)
                
                record = result.single()
                new_count = record['new_count'] if record else 0
                self.stats['users'] += new_count
                print(f"   진행: {min(i + self.batch_size, len(users)):,} / {len(users):,} (신규: {new_count})")
        
        print(f"✅ Users 동기화 완료: {self.stats['users']:,}명")
    
    def sync_chatrooms(self, chatrooms: list[dict]):
        """Chatrooms 동기화"""
        print(f"\n💬 Chatrooms 동기화 중... (총 {len(chatrooms):,}개)")
        
        with self.driver.session() as session:
            for i in range(0, len(chatrooms), self.batch_size):
                batch = chatrooms[i:i + self.batch_size]
                
                room_data = []
                for room in batch:
                    chat_id = room.get('chatId')
                    if not chat_id:
                        continue
                    
                    last_updated_iso = unix_to_iso(room.get('lastUpdatedAt'))
                    
                    properties = {
                        'chatId': chat_id,
                        'linkId': room.get('linkId', 0),
                        'room_type': room.get('type', 0),
                        'chatName': room.get('chatName', ''),
                        'activeMembersCount': room.get('activeMembersCount', 0),
                        'lastLogId': str(room.get('lastLogId', '')),
                        'lastUpdatedAt': room.get('lastUpdatedAt', 0),
                        'lastUpdatedAt_iso': last_updated_iso or '',
                        'directChatMemberUserId': room.get('directChatMemberUserId', 0)
                    }
                    
                    room_data.append({
                        'id': f"kakao_local_room:{chat_id}",
                        'type': 'kakao_local_chatroom',
                        'chat_id': chat_id,
                        'properties': sanitize_properties(properties)
                    })
                
                result = session.run("""
                    UNWIND $rooms AS room
                    OPTIONAL MATCH (existing:Entity {id: room.id})
                    WITH room, existing
                    WHERE existing IS NULL
                    CREATE (e:Entity {id: room.id})
                    SET e.type = room.type,
                        e.chat_id = room.chat_id,
                        e += room.properties
                    RETURN count(e) AS new_count
                """, rooms=room_data)
                
                record = result.single()
                new_count = record['new_count'] if record else 0
                self.stats['chatrooms'] += new_count
                print(f"   진행: {min(i + self.batch_size, len(chatrooms)):,} / {len(chatrooms):,} (신규: {new_count})")
        
        print(f"✅ Chatrooms 동기화 완료: {self.stats['chatrooms']:,}개")
    
    def sync_messages(self, messages: list[dict]):
        """Messages 동기화"""
        print(f"\n💌 Messages 동기화 중... (총 {len(messages):,}개)")
        
        with self.driver.session() as session:
            for i in range(0, len(messages), self.batch_size):
                batch = messages[i:i + self.batch_size]
                
                msg_data = []
                for msg in batch:
                    log_id = msg.get('logId')
                    chat_id = msg.get('chatId')
                    author_id = msg.get('authorId')
                    
                    if not log_id:
                        continue
                    
                    sent_at_iso = unix_to_iso(msg.get('sentAtUnix'))
                    timestamp = msg.get('sentAtUnix') or msg.get('sentAt')
                    
                    # attachment는 JSON string 또는 dict로 저장
                    attachment = msg.get('attachment')
                    if attachment:
                        # 이미 dict인 경우
                        if isinstance(attachment, dict):
                            if attachment:  # 비어있지 않은 dict만 저장
                                attachment = json.dumps(attachment, ensure_ascii=False)
                            else:
                                attachment = None
                        # string인 경우
                        elif isinstance(attachment, str):
                            if attachment != '{}':
                                try:
                                    # 유효한 JSON인지 확인
                                    json.loads(attachment)
                                except json.JSONDecodeError:
                                    attachment = json.dumps({'raw': attachment}, ensure_ascii=False)
                            else:
                                attachment = None
                        else:
                            attachment = None
                    else:
                        attachment = None
                    
                    properties = {
                        'logId': str(log_id),
                        'chatId': chat_id,
                        'authorId': author_id,
                        'msg_type': msg.get('type', 0),
                        'message': msg.get('message') or None,
                        'attachment': attachment,
                        'sentAt': msg.get('sentAt', 0),
                        'sentAt_iso': sent_at_iso,
                        'timestamp': timestamp,
                        'status': msg.get('status', 0)
                    }
                    
                    msg_data.append({
                        'id': f"kakao_local_msg:{log_id}",
                        'type': 'kakao_local_message',
                        'log_id': str(log_id),
                        'chat_id': chat_id,
                        'author_id': author_id,
                        'properties': sanitize_properties(properties)
                    })
                
                result = session.run("""
                    UNWIND $messages AS msg
                    OPTIONAL MATCH (existing:Entity {id: msg.id})
                    WITH msg, existing
                    WHERE existing IS NULL
                    CREATE (e:Entity {id: msg.id})
                    SET e:KakaoMessage,
                        e.source = 'kakaotalk',
                        e.type = msg.type,
                        e.log_id = msg.log_id,
                        e.chat_id = msg.chat_id,
                        e.author_id = msg.author_id,
                        e += msg.properties
                    RETURN count(e) AS new_count
                """, messages=msg_data)
                
                record = result.single()
                new_count = record['new_count'] if record else 0
                self.stats['messages'] += new_count
                if (i // self.batch_size) % 10 == 0 or i + self.batch_size >= len(messages):
                    print(f"   진행: {min(i + self.batch_size, len(messages)):,} / {len(messages):,} (신규누계: {self.stats['messages']:,})")
        
        print(f"✅ Messages 동기화 완료: {self.stats['messages']:,}개")
    
    def create_member_relations(self, chatrooms: list[dict], users: list[dict]):
        """MEMBER_OF 관계 생성 (User → ChatRoom)"""
        print(f"\n🔗 MEMBER_OF 관계 생성 중...")
        
        # userId 집합 생성
        user_ids = {u.get('userId') for u in users if u.get('userId')}
        
        # chatroom에서 멤버 관계 수집
        relations = []
        for room in chatrooms:
            chat_id = room.get('chatId')
            if not chat_id:
                continue
            
            # 1:1 채팅방의 경우 directChatMemberUserId 사용
            direct_member = room.get('directChatMemberUserId', 0)
            if direct_member and direct_member in user_ids:
                relations.append({
                    'user_id': f"kakao_local_user:{direct_member}",
                    'room_id': f"kakao_local_room:{chat_id}"
                })
        
        if not relations:
            print("⚠️  생성할 MEMBER_OF 관계가 없습니다")
            return
        
        print(f"   {len(relations):,}개의 관계 생성 예정")
        
        with self.driver.session() as session:
            for i in range(0, len(relations), self.batch_size):
                batch = relations[i:i + self.batch_size]
                
                session.run("""
                    UNWIND $relations AS rel
                    MATCH (u:Entity {id: rel.user_id})
                    MATCH (r:Entity {id: rel.room_id})
                    MERGE (u)-[e:MEMBER_OF]->(r)
                """, relations=batch)
                
                self.stats['member_of_edges'] += len(batch)
                print(f"   진행: {min(i + self.batch_size, len(relations)):,} / {len(relations):,}")
        
        print(f"✅ MEMBER_OF 관계 생성 완료: {self.stats['member_of_edges']:,}개")
    
    def create_message_relations(self, messages: list[dict]):
        """SENT 및 IN_ROOM 관계 생성"""
        print(f"\n🔗 SENT/IN_ROOM 관계 생성 중...")
        
        sent_relations = []
        in_room_relations = []
        
        for msg in messages:
            log_id = msg.get('logId')
            chat_id = msg.get('chatId')
            author_id = msg.get('authorId')
            
            if not log_id:
                continue
            
            # SENT: User → Message (authorId가 있는 경우)
            if author_id:
                sent_relations.append({
                    'user_id': f"kakao_local_user:{author_id}",
                    'msg_id': f"kakao_local_msg:{log_id}"
                })
            
            # IN_ROOM: Message → ChatRoom
            if chat_id:
                in_room_relations.append({
                    'msg_id': f"kakao_local_msg:{log_id}",
                    'room_id': f"kakao_local_room:{chat_id}"
                })
        
        print(f"   SENT 관계: {len(sent_relations):,}개 예정")
        print(f"   IN_ROOM 관계: {len(in_room_relations):,}개 예정")
        
        with self.driver.session() as session:
            # SENT 관계 생성
            for i in range(0, len(sent_relations), self.batch_size):
                batch = sent_relations[i:i + self.batch_size]
                session.run("""
                    UNWIND $relations AS rel
                    MATCH (u:Entity {id: rel.user_id})
                    MATCH (m:Entity {id: rel.msg_id})
                    MERGE (u)-[e:SENT]->(m)
                """, relations=batch)
                self.stats['sent_edges'] += len(batch)
                if (i // self.batch_size) % 10 == 0:
                    print(f"   SENT 진행: {min(i + self.batch_size, len(sent_relations)):,} / {len(sent_relations):,}")
            
            # IN_ROOM 관계 생성
            for i in range(0, len(in_room_relations), self.batch_size):
                batch = in_room_relations[i:i + self.batch_size]
                session.run("""
                    UNWIND $relations AS rel
                    MATCH (m:Entity {id: rel.msg_id})
                    MATCH (r:Entity {id: rel.room_id})
                    MERGE (m)-[e:IN_ROOM]->(r)
                """, relations=batch)
                self.stats['in_room_edges'] += len(batch)
                if (i // self.batch_size) % 10 == 0:
                    print(f"   IN_ROOM 진행: {min(i + self.batch_size, len(in_room_relations)):,} / {len(in_room_relations):,}")
        
        print(f"✅ SENT 관계 생성 완료: {self.stats['sent_edges']:,}개")
        print(f"✅ IN_ROOM 관계 생성 완료: {self.stats['in_room_edges']:,}개")
    
    def create_same_as_relations(self, users: list[dict]):
        """기존 kakao_user와 SAME_AS 관계 생성 (userId 매칭)"""
        print(f"\n🔗 SAME_AS 관계 생성 중 (기존 kakao_user와 매칭)...")
        
        with self.driver.session() as session:
            # 기존 kakao_user 노드들의 hashed_id 수집
            result = session.run("""
                MATCH (e:Entity {type: 'KakaoUser'})
                WHERE e.hashed_id IS NOT NULL
                RETURN e.hashed_id AS hashed_id, e.id AS node_id
            """)
            
            hashed_to_node = {record['hashed_id']: record['node_id'] for record in result}
            
            if not hashed_to_node:
                print("⚠️  기존 kakao_user 노드가 없습니다")
                return
            
            print(f"   기존 kakao_user: {len(hashed_to_node):,}명")
            
            # userId를 hashed_id로 변환하여 매칭 시도
            # 참고: 로컬 DB의 userId는 숫자이고, 기존 kakao_user의 hashed_id는 MD5 해시값
            # 이 경우 직접 매칭은 어렵지만, SAME_AS 패턴을 위해 노드만 생성핤 수 있음
            
            # 대안: 동일한 displayName이나 nickName으로 매칭 시도
            user_names = {}
            for user in users:
                name = user.get('displayName') or user.get('nickName')
                if name:
                    user_names[name] = f"kakao_local_user:{user.get('userId')}"
            
            # 기존 kakao_user 중 이름이 매칭되는 경우 SAME_AS 관계 생성
            result = session.run("""
                MATCH (e:Entity {type: 'KakaoUser'})
                WHERE e.name IS NOT NULL
                RETURN e.name AS name, e.id AS node_id
            """)
            
            same_as_relations = []
            for record in result:
                name = record['name']
                kakao_user_id = record['node_id']
                if name in user_names:
                    same_as_relations.append({
                        'local_user_id': user_names[name],
                        'kakao_user_id': kakao_user_id
                    })
            
            if not same_as_relations:
                print("⚠️  매칭되는 SAME_AS 관계가 없습니다")
                return
            
            print(f"   SAME_AS 관계: {len(same_as_relations):,}개 예정")
            
            for i in range(0, len(same_as_relations), self.batch_size):
                batch = same_as_relations[i:i + self.batch_size]
                session.run("""
                    UNWIND $relations AS rel
                    MATCH (local:Entity {id: rel.local_user_id})
                    MATCH (kakao:Entity {id: rel.kakao_user_id})
                    MERGE (local)-[e:SAME_AS]->(kakao)
                """, relations=batch)
                self.stats['same_as_edges'] += len(batch)
            
            print(f"✅ SAME_AS 관계 생성 완료: {self.stats['same_as_edges']:,}개")
    
    def run(self):
        """전체 동기화 실행"""
        print("=" * 60)
        print("카카오톡 로컬 DB → Neo4j 동기화 시작")
        print("=" * 60)
        
        try:
            # 1. 데이터 로드
            print("\n📂 데이터 로드 중...")
            users = self.load_json('users.json')
            chatrooms = self.load_json('chatrooms.json')
            messages = self.load_json('messages.json', flatten_messages=True)

            print(f"   Users: {len(users):,}명")
            print(f"   Chatrooms: {len(chatrooms):,}개")
            print(f"   Messages: {len(messages):,}개")
            
            # 2. 스키마 초기화
            self.init_schema()
            
            # 3. Users 동기화
            self.sync_users(users)
            
            # 4. Chatrooms 동기화
            self.sync_chatrooms(chatrooms)
            
            # 5. MEMBER_OF 관계 생성
            self.create_member_relations(chatrooms, users)
            
            # 6. Messages 동기화
            self.sync_messages(messages)
            
            # 7. SENT/IN_ROOM 관계 생성
            self.create_message_relations(messages)
            
            # 8. SAME_AS 관계 생성 (기존 kakao_user와 매칭)
            self.create_same_as_relations(users)
            
            # 결과 출력
            print("\n" + "=" * 60)
            print("📊 동기화 완료 통계 (새로 추가된 노드만)")
            print("=" * 60)
            print(f"   신규 Users: {self.stats['users']:,}명")
            print(f"   신규 Chatrooms: {self.stats['chatrooms']:,}개")
            print(f"   신규 Messages: {self.stats['messages']:,}개")
            print(f"   MEMBER_OF 관계: {self.stats['member_of_edges']:,}개")
            print(f"   SENT 관계: {self.stats['sent_edges']:,}개")
            print(f"   IN_ROOM 관계: {self.stats['in_room_edges']:,}개")
            print(f"   SAME_AS 관계: {self.stats['same_as_edges']:,}개")
            print("=" * 60)
            
        except Exception as e:
            print(f"\n❌ 오류 발생: {e}")
            raise


def main():
    sync = KakaoLocalSync()
    try:
        sync.run()
    finally:
        sync.close()


if __name__ == "__main__":
    main()
