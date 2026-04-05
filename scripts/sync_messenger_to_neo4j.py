#!/usr/bin/env python3
"""
Facebook Messenger 데이터 다운로드 (GDPR) → Neo4j 동기화

입력: Facebook 데이터 다운로드 압축 해제 후 messages/ 폴터
출처: https://www.facebook.com/dyi

지원 포맷:
- messages/inbox/<thread_name>/message_1.json
- messages/archived_threads/<thread_name>/message_1.json

Neo4j 노드 타입:
- messenger_message (type 프로퍼티로 구분, :Entity 라벨)
- messenger_thread (대화방 정보)
- messenger_user (발신자 정보)

관계 타입:
- SENT (User → Message)
- IN_THREAD (Message → Thread)
- PARTICIPANT (User → Thread)
"""

import json
import os
import re
import glob
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
from dotenv import load_dotenv
from neo4j import GraphDatabase
from tqdm import tqdm

# 환경 변수 로드
load_dotenv(Path.home() / "Development" / "Kitech_mail" / ".env")

# 설정
MESSAGES_DIR = Path.home() / "Development" / "talkdrive-backup" / "data" / "facebook_messages"
BATCH_SIZE = 100
MAX_TEXT_LENGTH = 5000

# Neo4j 연결 설정
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")


def parse_facebook_timestamp(ts_ms: Optional[int]) -> Optional[str]:
    """Facebook timestamp (밀리초)를 ISO 8601 형식으로 변환"""
    if not ts_ms:
        return None
    try:
        # Facebook은 밀리초 단위 Unix timestamp
        return datetime.fromtimestamp(ts_ms / 1000).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def sanitize_text(text: Optional[str]) -> str:
    """텍스트 정제 (Neo4j 저장용)"""
    if not text:
        return ""
    # 제어 문자 제거
    text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', text)
    # 너무 긴 텍스트는 미리보기만 저장
    if len(text) > MAX_TEXT_LENGTH:
        return text[:MAX_TEXT_LENGTH] + "..."
    return text


def sanitize_properties(props: dict[str, Any]) -> dict[str, Any]:
    """Neo4j에 저장 가능한 primitive 타입으로 properties 변환"""
    sanitized: dict[str, Any] = {}
    for k, v in props.items():
        if isinstance(v, dict):
            sanitized[k] = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, list):
            if v and any(isinstance(item, (dict, list)) for item in v):
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


class MessengerMessage:
    """Facebook Messenger 메시지 모델"""
    
    def __init__(self, data: dict, thread_id: str):
        self.raw_data = data
        self.thread_id = thread_id
        
        # 기본 필드
        self.sender_id = data.get('sender_name', 'Unknown')
        self.sender_name = data.get('sender_name', 'Unknown')
        self.timestamp_ms = data.get('timestamp_ms')
        self.content = data.get('content', '')
        self.message_id = data.get('timestamp_ms')  # Facebook은 고유 ID 대신 timestamp_ms 사용
        
        # 추가 필드
        self.type = data.get('type', 'Generic')
        self.is_unsent = data.get('is_unsent', False)
        self.share = data.get('share', {})
        self.files = data.get('files', [])
        self.photos = data.get('photos', [])
        self.videos = data.get('videos', [])
        self.audio_files = data.get('audio_files', [])
        self.reactions = data.get('reactions', [])
        
    @property
    def id(self) -> str:
        """고유 메시지 ID 생성"""
        return f"msg_{self.thread_id}_{self.message_id}"
    
    @property
    def timestamp_iso(self) -> Optional[str]:
        return parse_facebook_timestamp(self.timestamp_ms)
    
    @property
    def has_media(self) -> bool:
        return bool(self.files or self.photos or self.videos or self.audio_files)
    
    def to_neo4j_properties(self) -> dict[str, Any]:
        """Neo4j 저장용 속성 딕셔너리"""
        props = {
            'message_id': str(self.message_id),
            'sender_id': self.sender_id,
            'sender_name': self.sender_name,
            'thread_id': self.thread_id,
            'message': sanitize_text(self.content),
            'timestamp_ms': self.timestamp_ms,
            'timestamp': self.timestamp_iso,
            'type': self.type,
            'is_unsent': self.is_unsent,
            'has_media': self.has_media,
            'media_count': len(self.files) + len(self.photos) + len(self.videos) + len(self.audio_files),
            'reactions_count': len(self.reactions),
        }
        
        # 미디어 정보가 있으면 JSON으로 저장
        if self.photos:
            props['photos'] = json.dumps(self.photos, ensure_ascii=False)
        if self.videos:
            props['videos'] = json.dumps(self.videos, ensure_ascii=False)
        if self.reactions:
            props['reactions'] = json.dumps(self.reactions, ensure_ascii=False)
            
        return sanitize_properties(props)


class MessengerThread:
    """Facebook Messenger 대화방(스레드) 모델"""
    
    def __init__(self, thread_id: str, data: dict):
        self.thread_id = thread_id
        self.title = data.get('title', 'Unknown')
        self.is_still_participant = data.get('is_still_participant', True)
        self.thread_type = data.get('thread_type', 'Regular')
        self.thread_path = data.get('thread_path', '')
        
        # 참여자 목록
        self.participants = [
            p.get('name', '') 
            for p in data.get('participants', [])
        ]
        
    @property
    def id(self) -> str:
        return f"thread_{self.thread_id}"
    
    def to_neo4j_properties(self) -> dict[str, Any]:
        props = {
            'thread_id': self.thread_id,
            'title': self.title,
            'thread_type': self.thread_type,
            'is_still_participant': self.is_still_participant,
            'thread_path': self.thread_path,
            'participants': self.participants,
            'participant_count': len(self.participants),
        }
        return sanitize_properties(props)


class MessengerNeo4jSync:
    """Facebook Messenger → Neo4j 동기화 클래스"""
    
    def __init__(self):
        if not NEO4J_PASSWORD:
            raise ValueError("NEO4J_PASSWORD environment variable is not set")
        
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=("neo4j", NEO4J_PASSWORD))
        self.stats = {
            'threads': 0,
            'messages': 0,
            'users': 0,
            'sent_edges': 0,
            'in_thread_edges': 0,
            'participant_edges': 0,
        }
    
    def close(self):
        self.driver.close()
    
    def init_schema(self):
        """Neo4j 스키마 초기화 (인덱스/제약조건)"""
        with self.driver.session() as session:
            # Entity ID 유니크 제약조건
            session.run("""
                CREATE CONSTRAINT messenger_entity_id IF NOT EXISTS
                FOR (e:Entity) REQUIRE e.id IS UNIQUE
            """)
            # 타입 인덱스
            session.run("""
                CREATE INDEX messenger_entity_type IF NOT EXISTS
                FOR (e:Entity) ON (e.type)
            """)
            # 타임스탬프 인덱스
            session.run("""
                CREATE INDEX messenger_message_timestamp IF NOT EXISTS
                FOR (e:Entity) ON (e.timestamp)
            """)
            print("✅ 스키마 초기화 완료")
    
    def create_thread(self, tx, thread: MessengerThread):
        """대화방 노드 생성/업데이트"""
        query = """
        MERGE (t:Entity {id: $id})
        ON CREATE SET 
            t.type = 'messenger_thread',
            t.source = 'facebook_messenger',
            t.created_at = datetime(),
            t.updated_at = datetime(),
            t += $props
        ON MATCH SET 
            t.source = 'facebook_messenger',
            t.updated_at = datetime(),
            t += $props
        """
        tx.run(query, id=thread.id, props=thread.to_neo4j_properties())
    
    def create_message(self, tx, msg: MessengerMessage):
        """메시지 노드 생성/업데이트"""
        query = """
        MERGE (m:Entity {id: $id})
        ON CREATE SET 
            m.type = 'messenger_message',
            m.source = 'facebook_messenger',
            m.created_at = datetime(),
            m.updated_at = datetime(),
            m += $props
        ON MATCH SET 
            m.source = 'facebook_messenger',
            m.updated_at = datetime(),
            m += $props
        """
        tx.run(query, id=msg.id, props=msg.to_neo4j_properties())
    
    def create_user(self, tx, sender_name: str, sender_id: str = ""):
        """사용자 노드 생성/업데이트"""
        user_id = f"messenger_user_{sender_name.replace(' ', '_')}"
        query = """
        MERGE (u:Entity {id: $id})
        ON CREATE SET 
            u.type = 'messenger_user',
            u.source = 'facebook_messenger',
            u.name = $name,
            u.sender_id = $sender_id,
            u.created_at = datetime(),
            u.updated_at = datetime()
        ON MATCH SET 
            u.source = 'facebook_messenger',
            u.updated_at = datetime()
        """
        tx.run(query, id=user_id, name=sender_name, sender_id=sender_id)
        return user_id
    
    def create_relationships(self, tx, msg: MessengerMessage, user_id: str):
        """관계 생성"""
        # SENT: User → Message
        query1 = """
        MATCH (u:Entity {id: $user_id})
        MATCH (m:Entity {id: $msg_id})
        MERGE (u)-[r:SENT]->(m)
        """
        tx.run(query1, user_id=user_id, msg_id=msg.id)
        
        # IN_THREAD: Message → Thread
        query2 = """
        MATCH (m:Entity {id: $msg_id})
        MATCH (t:Entity {id: $thread_id})
        MERGE (m)-[r:IN_THREAD]->(t)
        """
        tx.run(query2, msg_id=msg.id, thread_id=f"thread_{msg.thread_id}")
    
    def create_participant_relations(self, tx, thread: MessengerThread):
        """참여자 관계 생성 (User → Thread)"""
        for participant in thread.participants:
            user_id = f"messenger_user_{participant.replace(' ', '_')}"
            query = """
            MATCH (u:Entity {id: $user_id})
            MATCH (t:Entity {id: $thread_id})
            MERGE (u)-[r:PARTICIPANT]->(t)
            """
            tx.run(query, user_id=user_id, thread_id=thread.id)
    
    def sync_batch(self, items: list, item_type: str):
        """배치 동기화"""
        with self.driver.session() as session:
            with session.begin_transaction() as tx:
                if item_type == 'threads':
                    for thread in items:
                        self.create_thread(tx, thread)
                        self.create_participant_relations(tx, thread)
                        self.stats['threads'] += 1
                        self.stats['participant_edges'] += len(thread.participants)
                        
                elif item_type == 'messages':
                    for msg in items:
                        user_id = self.create_user(tx, msg.sender_name, msg.sender_id)
                        self.create_message(tx, msg)
                        self.create_relationships(tx, msg, user_id)
                        self.stats['messages'] += 1
                        self.stats['users'] = len(set([
                            m.sender_name for m in items
                        ]))  # 대략적인 유저 수
    
    def get_stats(self) -> dict[str, int]:
        """현재 통계 조회"""
        with self.driver.session() as session:
            # 노드 타입별 카운트
            result = session.run("""
                MATCH (e:Entity)
                WHERE e.type STARTS WITH 'messenger'
                RETURN e.type AS type, count(*) AS count
            """)
            node_counts = {record["type"]: record["count"] for record in result}
            
            # 관계 타입별 카운트
            result = session.run("""
                MATCH ()-[r]->()
                WHERE type(r) IN ['SENT', 'IN_THREAD', 'PARTICIPANT']
                RETURN type(r) AS type, count(*) AS count
            """)
            rel_counts = {record["type"]: record["count"] for record in result}
            
            return {
                'nodes': node_counts,
                'relationships': rel_counts
            }


class MessengerDataLoader:
    """Facebook Messenger 데이터 로더"""
    
    def __init__(self, messages_dir: Path):
        self.messages_dir = messages_dir
        self.threads: list[MessengerThread] = []
        self.messages: list[MessengerMessage] = []
    
    def find_message_files(self) -> list[Path]:
        """모든 message_*.json 파일 찾기"""
        pattern = str(self.messages_dir / "**" / "message_*.json")
        files = glob.glob(pattern, recursive=True)
        return [Path(f) for f in sorted(files)]
    
    def parse_message_file(self, filepath: Path) -> tuple[MessengerThread, list[MessengerMessage]]:
        """단일 메시지 파일 파싱"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # thread_id 생성 (파일 경로 기반)
        thread_path = filepath.parent.name
        thread_id = thread_path.replace(' ', '_').replace('-', '_')
        
        # Thread 정보 추출
        thread = MessengerThread(thread_id, data)
        
        # Messages 추출
        messages = []
        for msg_data in data.get('messages', []):
            msg = MessengerMessage(msg_data, thread_id)
            messages.append(msg)
        
        return thread, messages
    
    def load_all(self) -> tuple[list[MessengerThread], list[MessengerMessage]]:
        """모든 데이터 로드"""
        files = self.find_message_files()
        print(f"📁 {len(files)}개의 메시지 파일 발견")
        
        if not files:
            print("⚠️  메시지 파일을 찾을 수 없습니다.")
            print(f"   경로 확인: {self.messages_dir}")
            return [], []
        
        all_threads = {}
        all_messages = []
        
        for filepath in tqdm(files, desc="파일 파싱"):
            try:
                thread, messages = self.parse_message_file(filepath)
                
                # 중복 thread 처리 (같은 대화방의 다른 파일)
                if thread.thread_id not in all_threads:
                    all_threads[thread.thread_id] = thread
                
                all_messages.extend(messages)
                
            except json.JSONDecodeError as e:
                print(f"\n⚠️ JSON 파싱 오류: {filepath} - {e}")
            except Exception as e:
                print(f"\n⚠️ 파일 처리 오류: {filepath} - {e}")
        
        return list(all_threads.values()), all_messages


class MessengerSync:
    """메인 동기화 클래스"""
    
    def __init__(self):
        self.neo4j = MessengerNeo4jSync()
        self.loader = MessengerDataLoader(MESSAGES_DIR)
    
    def close(self):
        self.neo4j.close()
    
    def run(self):
        """전체 동기화 실행"""
        print("=" * 60)
        print("Facebook Messenger → Neo4j 동기화")
        print("=" * 60)
        
        # 1. 스키마 초기화
        self.neo4j.init_schema()
        
        # 2. 데이터 로드
        print("\n📂 데이터 로드 중...")
        threads, messages = self.loader.load_all()
        
        if not threads and not messages:
            print("\n❌ 동기화할 데이터가 없습니다.")
            print("\nFacebook 데이터 다운로드 방법:")
            print("  1. https://www.facebook.com/dyi 접속")
            print("  2. '메시지' 카테고리 선택")
            print("  3. JSON 포맷으로 다운로드")
            print("  4. 압축 해제 후 messages/ 폴터를 아래 경로에 복사:")
            print(f"     {MESSAGES_DIR}")
            return
        
        print(f"\n📊 로드된 데이터:")
        print(f"   - 대화방(Threads): {len(threads):,}개")
        print(f"   - 메시지(Messages): {len(messages):,}개")
        
        # 3. Thread 동기화
        print("\n📝 대화방 동기화 중...")
        thread_batches = [
            threads[i:i+BATCH_SIZE] 
            for i in range(0, len(threads), BATCH_SIZE)
        ]
        for batch in tqdm(thread_batches, desc="Threads"):
            self.neo4j.sync_batch(batch, 'threads')
        
        # 4. Message 동기화
        print("\n💬 메시지 동기화 중...")
        message_batches = [
            messages[i:i+BATCH_SIZE] 
            for i in range(0, len(messages), BATCH_SIZE)
        ]
        for batch in tqdm(message_batches, desc="Messages"):
            self.neo4j.sync_batch(batch, 'messages')
        
        # 5. 결과 출력
        print("\n" + "=" * 60)
        print("✅ 동기화 완료!")
        print("=" * 60)
        
        stats = self.neo4j.get_stats()
        print("\n📈 Neo4j 현황:")
        print("\n[노드]")
        for node_type, count in sorted(stats['nodes'].items()):
            print(f"   - {node_type}: {count:,}개")
        
        print("\n[관계]")
        for rel_type, count in sorted(stats['relationships'].items()):
            print(f"   - {rel_type}: {count:,}개")


def main():
    sync = MessengerSync()
    try:
        sync.run()
    except KeyboardInterrupt:
        print("\n\n⚠️  사용자가 중단했습니다.")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        raise
    finally:
        sync.close()


if __name__ == "__main__":
    main()
