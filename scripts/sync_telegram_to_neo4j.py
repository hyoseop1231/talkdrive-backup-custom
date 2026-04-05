#!/usr/bin/env python3
"""
OpenClaw Telegram Session Logs → Neo4j Sync Script

텔레그램 세션 로그를 파싱하여 Neo4j에 동기화합니다.
"""

import os
import json
import re
import glob
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from dotenv import load_dotenv
from neo4j import GraphDatabase
from tqdm import tqdm

# 환경 변수 로드
load_dotenv(os.path.expanduser("~/Development/Kitech_mail/.env"))

# 설정
SESSIONS_DIR = os.path.expanduser("~/.openclaw/agents/main/sessions")
BATCH_SIZE = 100
MAX_TEXT_LENGTH = 5000

# Neo4j 연결 설정
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "CHANGE_ME_PASSWORD")


class TelegramMessageParser:
    """텔레그램 메시지 파서"""
    
    # 텔레그램 메시지 패턴
    TELEGRAM_PATTERN = re.compile(
        r'\[Telegram\s+(?P<sender_name>[^(@]+)\s+\(@(?P<username>[^)]+)\)\s+'
        r'id:(?P<telegram_id>\d+)\s+(?P<offset>\+\d+s)?\s*'
        r'(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+GMT[+-]\d+?)\]\s*'
        r'(?P<text>.*?)(?:\[message_id:\s*(?P<message_id>\d+)\])?$',
        re.DOTALL
    )
    
    # 스킵할 시스템 메시지 패턴
    SKIP_PATTERNS = [
        re.compile(r'^\s*$'),  # 빈 메시지
        re.compile(r'^NO_REPLY$', re.IGNORECASE),
        re.compile(r'^HEARTBEAT_OK$', re.IGNORECASE),
        re.compile(r'^System:', re.IGNORECASE),
        re.compile(r'^Read HEARTBEAT', re.IGNORECASE),
        re.compile(r'^\[.*heartbeat.*\]', re.IGNORECASE),
    ]
    
    @classmethod
    def should_skip(cls, text: str) -> bool:
        """스킵해야 할 메시지인지 확인"""
        if not text or len(text.strip()) < 5:
            return True
        for pattern in cls.SKIP_PATTERNS:
            if pattern.match(text.strip()):
                return True
        return False
    
    @classmethod
    def parse_telegram_message(cls, content: str) -> Optional[Dict[str, Any]]:
        """텔레그램 메시지 파싱"""
        if not content or "[Telegram" not in content:
            return None
        
        # 멀티라인 content 처리
        lines = content.split('\n')
        first_line = lines[0] if lines else ""
        remaining_text = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""
        
        match = cls.TELEGRAM_PATTERN.match(first_line)
        if not match:
            return None
        
        parsed = match.groupdict()
        text = parsed.get('text', '').strip()
        
        # 나머지 라인이 있으면 추가
        if remaining_text and not remaining_text.startswith('[message_id:'):
            text = (text + '\n' + remaining_text).strip() if text else remaining_text
        
        # message_id 파싱 (별도 라인에 있을 수 있음)
        message_id = parsed.get('message_id')
        if not message_id:
            msg_id_match = re.search(r'\[message_id:\s*(\d+)\]', content)
            if msg_id_match:
                message_id = msg_id_match.group(1)
        
        return {
            'sender_name': parsed.get('sender_name', '').strip(),
            'username': parsed.get('username', '').strip(),
            'telegram_id': parsed.get('telegram_id', '').strip(),
            'timestamp': parsed.get('timestamp', '').strip(),
            'text': text,
            'telegram_message_id': message_id,
        }


class Neo4jSync:
    """Neo4j 동기화 클래스"""
    
    def __init__(self, uri: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=("neo4j", password))
    
    def close(self):
        self.driver.close()
    
    def create_telegram_user(self, tx, user_id: str, username: str, display_name: str):
        """텔레그램 사용자 노드 생성/업데이트"""
        query = """
        MERGE (u:Entity {id: $user_id})
        ON CREATE SET 
            u.type = 'telegram_user',
            u.source = 'telegram',
            u.username = $username,
            u.display_name = $display_name,
            u.created_at = datetime(),
            u.updated_at = datetime()
        ON MATCH SET 
            u.source = 'telegram',
            u.username = $username,
            u.display_name = $display_name,
            u.updated_at = datetime()
        """
        tx.run(query, user_id=user_id, username=username, display_name=display_name)
    
    def create_telegram_session(self, tx, session_id: str, start_time: str, 
                                 end_time: Optional[str] = None, message_count: int = 0):
        """텔레그램 세션 노드 생성/업데이트"""
        query = """
        MERGE (s:Entity {id: $session_id})
        ON CREATE SET 
            s.type = 'telegram_session',
            s.source = 'telegram',
            s.start_time = $start_time,
            s.end_time = $end_time,
            s.message_count = $message_count,
            s.created_at = datetime(),
            s.updated_at = datetime()
        ON MATCH SET 
            s.source = 'telegram',
            s.end_time = COALESCE($end_time, s.end_time),
            s.message_count = s.message_count + $message_count,
            s.updated_at = datetime()
        """
        tx.run(query, session_id=session_id, start_time=start_time, 
               end_time=end_time, message_count=message_count)
    
    def create_telegram_message(self, tx, msg_id: str, session_id: str, text: str,
                                 role: str, timestamp: str, 
                                 telegram_message_id: Optional[str] = None):
        """텔레그램 메시지 노드 생성/업데이트"""
        # 텍스트가 너무 길면 미리보기 저장
        text_preview = text[:MAX_TEXT_LENGTH] if len(text) > MAX_TEXT_LENGTH else text
        full_length = len(text)
        
        query = """
        MERGE (m:Entity {id: $msg_id})
        ON CREATE SET 
            m:TelegramMessage,
            m.type = 'telegram_message',
            m.source = 'telegram',
            m.text = $text_preview,
            m.full_length = $full_length,
            m.role = $role,
            m.timestamp = $timestamp,
            m.telegram_message_id = $telegram_message_id,
            m.created_at = datetime(),
            m.updated_at = datetime()
        ON MATCH SET 
            m:TelegramMessage,
            m.source = 'telegram',
            m.text = $text_preview,
            m.full_length = $full_length,
            m.role = $role,
            m.updated_at = datetime()
        """
        tx.run(query, msg_id=msg_id, text_preview=text_preview, full_length=full_length,
               role=role, timestamp=timestamp, telegram_message_id=telegram_message_id)
    
    def create_relationships(self, tx, msg_id: str, session_id: str, 
                             user_id: Optional[str] = None):
        """관계 생성"""
        # 메시지 → 세션 관계
        query1 = """
        MATCH (m:Entity {id: $msg_id})
        MATCH (s:Entity {id: $session_id})
        MERGE (m)-[:IN_SESSION]->(s)
        """
        tx.run(query1, msg_id=msg_id, session_id=session_id)
        
        # 사용자 → 메시지 관계
        if user_id:
            query2 = """
            MATCH (u:Entity {id: $user_id})
            MATCH (m:Entity {id: $msg_id})
            MERGE (u)-[:SENT]->(m)
            """
            tx.run(query2, user_id=user_id, msg_id=msg_id)
    
    def create_same_as_relationships(self, tx):
        """SAME_AS 관계 생성 (효섭 김 연결)"""
        # tg_user:hyoseop1231 → person:hyoseop1231@kitech.re.kr
        query1 = """
        MATCH (tg:Entity {id: 'tg_user:hyoseop1231'})
        MATCH (p:Entity {id: 'person:hyoseop1231@kitech.re.kr'})
        MERGE (tg)-[:SAME_AS]->(p)
        """
        tx.run(query1)
        
        # tg_user:hyoseop1231 → kakao_local_user:236788016
        query2 = """
        MATCH (tg:Entity {id: 'tg_user:hyoseop1231'})
        MATCH (k:Entity {id: 'kakao_local_user:236788016'})
        MERGE (tg)-[:SAME_AS]->(k)
        """
        tx.run(query2)
    
    def get_stats(self) -> Dict[str, int]:
        """현재 통계 조회"""
        with self.driver.session() as session:
            # 노드 타입별 카운트
            result = session.run("""
                MATCH (e:Entity)
                RETURN e.type AS type, count(*) AS count
            """)
            node_counts = {record["type"]: record["count"] for record in result}
            
            # 관계 타입별 카운트
            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(*) AS count
            """)
            rel_counts = {record["type"]: record["count"] for record in result}
            
            return {
                'nodes': node_counts,
                'relationships': rel_counts
            }


class TelegramLogSync:
    """텔레그램 로그 동기화 메인 클래스"""
    
    def __init__(self):
        self.neo4j = Neo4jSync(NEO4J_URI, NEO4J_PASSWORD)
        self.stats = {
            'files_processed': 0,
            'messages_processed': 0,
            'user_messages': 0,
            'assistant_messages': 0,
            'skipped_messages': 0,
            'errors': 0,
        }
    
    def extract_content(self, message_data: Dict) -> str:
        """메시지에서 텍스트 콘텐츠 추출"""
        content = message_data.get('content', '')
        
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # content가 배열인 경우 text 타입만 추출
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'text':
                    texts.append(item.get('text', ''))
            return '\n'.join(texts)
        return ''
    
    def parse_session_file(self, filepath: str) -> Tuple[str, List[Dict]]:
        """세션 파일 파싱"""
        session_id = Path(filepath).stem
        messages = []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get('type') == 'message':
                        msg_data = data.get('message', {})
                        role = msg_data.get('role', '')
                        content = self.extract_content(msg_data)
                        timestamp = data.get('timestamp', '')
                        msg_id = data.get('id', '')
                        
                        messages.append({
                            'id': msg_id,
                            'role': role,
                            'content': content,
                            'timestamp': timestamp,
                        })
                except json.JSONDecodeError:
                    continue
        
        return session_id, messages
    
    def process_message(self, session_id: str, msg: Dict) -> Optional[Dict]:
        """단일 메시지 처리"""
        role = msg['role']
        content = msg['content']
        timestamp = msg['timestamp']
        msg_id = msg['id']
        
        # toolResult 스킵
        if role == 'toolResult':
            return None
        
        # 스킵 패턴 확인
        if TelegramMessageParser.should_skip(content):
            return None
        
        processed = None
        
        if role == 'user':
            # 텔레그램 메시지 파싱
            parsed = TelegramMessageParser.parse_telegram_message(content)
            if parsed:
                telegram_id = parsed.get('username') or parsed.get('telegram_id')
                user_id = f"tg_user:{telegram_id}"
                
                processed = {
                    'msg_id': f"tg_msg:{session_id}:{msg_id}",
                    'session_id': f"tg_session:{session_id}",
                    'user_id': user_id,
                    'text': parsed['text'],
                    'role': 'user',
                    'timestamp': parsed.get('timestamp') or timestamp,
                    'telegram_message_id': parsed.get('telegram_message_id'),
                    'sender_name': parsed.get('sender_name'),
                    'username': telegram_id,
                }
                self.stats['user_messages'] += 1
        
        elif role == 'assistant':
            # assistant 메시지는 wangcheonjae 사용자로 연결
            processed = {
                'msg_id': f"tg_msg:{session_id}:{msg_id}",
                'session_id': f"tg_session:{session_id}",
                'user_id': "tg_user:wangcheonjae",
                'text': content,
                'role': 'assistant',
                'timestamp': timestamp,
                'telegram_message_id': None,
            }
            self.stats['assistant_messages'] += 1
        
        return processed
    
    def sync_batch(self, batch: List[Dict]):
        """배치 동기화"""
        with self.neo4j.driver.session() as session:
            with session.begin_transaction() as tx:
                for item in batch:
                    # 사용자 생성
                    if item.get('sender_name') or item.get('username'):
                        self.neo4j.create_telegram_user(
                            tx, 
                            item['user_id'],
                            item.get('username', ''),
                            item.get('sender_name', '')
                        )
                    
                    # 메시지 생성
                    self.neo4j.create_telegram_message(
                        tx,
                        item['msg_id'],
                        item['session_id'],
                        item['text'],
                        item['role'],
                        item['timestamp'],
                        item.get('telegram_message_id')
                    )
                    
                    # 관계 생성
                    self.neo4j.create_relationships(
                        tx,
                        item['msg_id'],
                        item['session_id'],
                        item.get('user_id')
                    )
    
    def run(self):
        """메인 실행"""
        print("=" * 60)
        print("OpenClaw Telegram Session Logs → Neo4j Sync")
        print("=" * 60)
        
        # 파일 목록 수집
        pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
        files = glob.glob(pattern)
        print(f"\n📁 총 {len(files)}개 파일 발견")
        
        if not files:
            print("❌ 처리할 파일이 없습니다.")
            return
        
        # 처리할 메시지 수집
        all_messages = []
        session_info = {}
        
        print("\n🔍 파일 분석 중...")
        for filepath in tqdm(files, desc="파일 분석"):
            try:
                session_id, messages = self.parse_session_file(filepath)
                session_info[session_id] = {
                    'filepath': filepath,
                    'message_count': len(messages),
                    'start_time': messages[0]['timestamp'] if messages else None,
                    'end_time': messages[-1]['timestamp'] if messages else None,
                }
                
                for msg in messages:
                    processed = self.process_message(session_id, msg)
                    if processed:
                        all_messages.append(processed)
                    else:
                        self.stats['skipped_messages'] += 1
                
                self.stats['files_processed'] += 1
            except Exception as e:
                print(f"\n⚠️ 파일 처리 오류: {filepath} - {e}")
                self.stats['errors'] += 1
        
        print(f"\n📊 분석 결과:")
        print(f"   - 처리된 파일: {self.stats['files_processed']}")
        print(f"   - 총 메시지: {len(all_messages)}")
        print(f"   - User 메시지: {self.stats['user_messages']}")
        print(f"   - Assistant 메시지: {self.stats['assistant_messages']}")
        print(f"   - 스킵된 메시지: {self.stats['skipped_messages']}")
        
        if not all_messages:
            print("\n❌ 동기화할 메시지가 없습니다.")
            return
        
        # 세션 노드 생성
        print("\n📝 세션 정보 동기화 중...")
        with self.neo4j.driver.session() as session:
            with session.begin_transaction() as tx:
                for session_id, info in session_info.items():
                    self.neo4j.create_telegram_session(
                        tx,
                        f"tg_session:{session_id}",
                        info['start_time'],
                        info['end_time'],
                        info['message_count']
                    )
        
        # 메시지 배치 처리
        print("\n💾 메시지 동기화 중...")
        batches = [all_messages[i:i+BATCH_SIZE] 
                   for i in range(0, len(all_messages), BATCH_SIZE)]
        
        for i, batch in enumerate(tqdm(batches, desc="배치 처리")):
            try:
                self.sync_batch(batch)
            except Exception as e:
                print(f"\n⚠️ 배치 처리 오류 (batch {i+1}): {e}")
                self.stats['errors'] += 1
        
        # SAME_AS 관계 생성
        print("\n🔗 SAME_AS 관계 생성 중...")
        with self.neo4j.driver.session() as session:
            with session.begin_transaction() as tx:
                self.neo4j.create_same_as_relationships(tx)
        
        # 최종 통계
        print("\n" + "=" * 60)
        print("✅ 동기화 완료!")
        print("=" * 60)
        
        stats = self.neo4j.get_stats()
        print("\n📈 Neo4j 현황:")
        print("\n[노드]")
        for node_type, count in sorted([k for k in stats['nodes'].items() if k[0] is not None]):
            print(f"   - {node_type}: {count:,}개")

        print("\n[관계]")
        for rel_type, count in sorted([k for k in stats['relationships'].items() if k[0] is not None]):
            print(f"   - {rel_type}: {count:,}개")
        
        self.neo4j.close()


def main():
    sync = TelegramLogSync()
    sync.run()


if __name__ == "__main__":
    main()
