#!/usr/bin/env python3
"""
Synology Photos → Neo4j 동기화 스크립트 (Mac Pro에서 실행)
"""

import json
import os
import sys
from datetime import datetime
from neo4j import GraphDatabase

# Neo4j 설정
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "CHANGE_ME_PASSWORD"

# 배치 사이즈
BATCH_SIZE = 500


def log(msg):
    """타임스탬프와 함께 로그 출력"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def to_primitive(value):
    """값을 primitive 타입으로 변환"""
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def unix_to_iso(timestamp):
    """Unix timestamp를 ISO 8601 문자열로 변환"""
    if not timestamp:
        return ""
    try:
        ts = int(timestamp)
        if ts > 1e12:  # milliseconds
            ts = ts / 1000
        return datetime.fromtimestamp(ts).isoformat()
    except:
        return str(timestamp)


def safe_get(obj, key, default=""):
    """안전하게 딕셔너리 값 가져오기"""
    val = obj.get(key, default)
    return to_primitive(val)


class Neo4jSync:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.stats = {
            "photos_created": 0,
            "folders_created": 0,
            "persons_created": 0,
            "in_folder_rels": 0,
            "tagged_person_rels": 0,
            "child_of_rels": 0,
            "same_as_rels": 0
        }

    def close(self):
        self.driver.close()

    def test_connection(self):
        """Neo4j 연결 테스트"""
        try:
            with self.driver.session() as session:
                result = session.run("RETURN 1 as n")
                record = result.single()
                if record and record["n"] == 1:
                    log("✓ Neo4j 연결 성공")
                    return True
        except Exception as e:
            log(f"❌ Neo4j 연결 실패: {e}")
            return False
        return False

    def clear_existing_data(self):
        """기존 Synology Photos 데이터 삭제 (선택적)"""
        log("기존 Synology Photos 데이터 정리 중...")
        with self.driver.session() as session:
            # 관계 삭제
            session.run("""
                MATCH ()-[r:IN_FOLDER|TAGGED_PERSON|CHILD_OF|SYNOLOGY_SAME_AS]->()
                WHERE r.source = 'synology_photos'
                DELETE r
            """)
            # 노드 삭제
            session.run("""
                MATCH (n:Entity)
                WHERE n.id STARTS WITH 'synology_'
                DELETE n
            """)
        log("✓ 기존 데이터 정리 완료")

    def create_photos_batch(self, photos):
        """사진 노드 배치 생성"""
        with self.driver.session() as session:
            for i in range(0, len(photos), BATCH_SIZE):
                batch = photos[i:i+BATCH_SIZE]
                
                query = """
                UNWIND $batch as photo
                MERGE (p:Entity {id: 'synology_photo:' + photo.id})
                ON CREATE SET
                    p:synology_photo,
                    p.source = 'synology_photos',
                    p.filename = photo.filename,
                    p.taken_time = photo.taken_time,
                    p.time = photo.time,
                    p.type = photo.type,
                    p.width = photo.width,
                    p.height = photo.height,
                    p.filesize = photo.filesize,
                    p.folder_id = photo.folder_id,
                    p.folder_name = photo.folder_name,
                    p.latitude = photo.latitude,
                    p.longitude = photo.longitude,
                    p.city = photo.city,
                    p.country = photo.country,
                    p.additionals = photo.additionals,
                    p.created_at = datetime(),
                    p.updated_at = datetime()
                ON MATCH SET
                    p:synology_photo,
                    p.source = 'synology_photos',
                    p.filename = photo.filename,
                    p.taken_time = photo.taken_time,
                    p.time = photo.time,
                    p.updated_at = datetime()
                """
                
                params = []
                for photo in batch:
                    additional = photo.get("additional", {})
                    geocoding = additional.get("geocoding", {}) if isinstance(additional, dict) else {}
                    
                    p = {
                        "id": str(photo.get("id", "")),
                        "filename": safe_get(photo, "filename"),
                        "taken_time": unix_to_iso(photo.get("time")),
                        "time": photo.get("time", 0),
                        "type": "photo" if photo.get("type") in [0, "0"] else "video",
                        "width": safe_get(photo, "resolutionwidth") or safe_get(photo, "resolution_width", 0),
                        "height": safe_get(photo, "resolutionheight") or safe_get(photo, "resolution_height", 0),
                        "filesize": safe_get(photo, "filesize", 0),
                        "folder_id": str(photo.get("folder_id", "")),
                        "folder_name": safe_get(photo, "folder_name"),
                        "latitude": geocoding.get("latitude", "") if isinstance(geocoding, dict) else "",
                        "longitude": geocoding.get("longitude", "") if isinstance(geocoding, dict) else "",
                        "city": geocoding.get("city", "") if isinstance(geocoding, dict) else "",
                        "country": geocoding.get("country", "") if isinstance(geocoding, dict) else "",
                        "additionals": json.dumps(additional, ensure_ascii=False) if additional else ""
                    }
                    params.append(p)
                
                session.run(query, batch=params)
                self.stats["photos_created"] += len(batch)
                
                if (i // BATCH_SIZE + 1) % 10 == 0:
                    log(f"  사진 진행: {self.stats['photos_created']:,}개 생성")

    def create_folders_batch(self, folders):
        """폴�더 노드 배치 생성"""
        with self.driver.session() as session:
            for i in range(0, len(folders), BATCH_SIZE):
                batch = folders[i:i+BATCH_SIZE]
                
                query = """
                UNWIND $batch as folder
                MERGE (f:Entity {id: 'synology_folder:' + folder.id})
                ON CREATE SET
                    f:synology_folder,
                    f.source = 'synology_photos',
                    f.name = folder.name,
                    f.path = folder.path,
                    f.parent_id = folder.parent_id,
                    f.created_at = datetime(),
                    f.updated_at = datetime()
                ON MATCH SET
                    f:synology_folder,
                    f.source = 'synology_photos',
                    f.name = folder.name,
                    f.path = folder.path,
                    f.updated_at = datetime()
                """
                
                params = []
                for folder in batch:
                    f = {
                        "id": str(folder.get("id", "")),
                        "name": safe_get(folder, "name"),
                        "path": safe_get(folder, "path"),
                        "parent_id": str(folder.get("parent_id", "")) if folder.get("parent_id") else ""
                    }
                    params.append(f)
                
                session.run(query, batch=params)
                self.stats["folders_created"] += len(batch)

    def create_persons_batch(self, persons):
        """인물 노드 배치 생성"""
        with self.driver.session() as session:
            for i in range(0, len(persons), BATCH_SIZE):
                batch = persons[i:i+BATCH_SIZE]
                
                query = """
                UNWIND $batch as person
                MERGE (p:Entity {id: 'synology_person:' + person.id})
                ON CREATE SET
                    p:synology_person,
                    p.source = 'synology_photos',
                    p.name = person.name,
                    p.item_count = person.item_count,
                    p.created_at = datetime(),
                    p.updated_at = datetime()
                ON MATCH SET
                    p:synology_person,
                    p.source = 'synology_photos',
                    p.name = person.name,
                    p.item_count = person.item_count,
                    p.updated_at = datetime()
                """
                
                params = []
                for person in batch:
                    p = {
                        "id": str(person.get("id", "")),
                        "name": safe_get(person, "name") or safe_get(person, "person_name"),
                        "item_count": person.get("item_count", 0)
                    }
                    params.append(p)
                
                session.run(query, batch=params)
                self.stats["persons_created"] += len(batch)

    def create_in_folder_relationships(self, photos):
        """IN_FOLDER 관계 생성"""
        log("IN_FOLDER 관계 생성 중...")
        with self.driver.session() as session:
            for i in range(0, len(photos), BATCH_SIZE):
                batch = photos[i:i+BATCH_SIZE]
                
                query = """
                UNWIND $batch as photo
                MATCH (p:Entity:synology_photo {id: 'synology_photo:' + photo.id})
                MATCH (f:Entity:synology_folder {id: 'synology_folder:' + photo.folder_id})
                MERGE (p)-[r:IN_FOLDER]->(f)
                ON CREATE SET r.source = 'synology_photos', r.created_at = datetime()
                """
                
                params = [{"id": str(p.get("id", "")), "folder_id": str(p.get("folder_id", ""))} 
                         for p in batch if p.get("folder_id")]
                
                if params:
                    result = session.run(query, batch=params)
                    self.stats["in_folder_rels"] += len(params)

    def create_child_of_relationships(self, folders):
        """CHILD_OF 관계 생성"""
        log("CHILD_OF 관계 생성 중...")
        with self.driver.session() as session:
            query = """
            UNWIND $folders as folder
            MATCH (child:Entity:synology_folder {id: 'synology_folder:' + folder.id})
            MATCH (parent:Entity:synology_folder {id: 'synology_folder:' + folder.parent_id})
            WHERE folder.parent_id IS NOT NULL AND folder.parent_id <> ''
            MERGE (child)-[r:CHILD_OF]->(parent)
            ON CREATE SET r.source = 'synology_photos', r.created_at = datetime()
            """
            
            params = [{"id": str(f.get("id", "")), "parent_id": str(f.get("parent_id", ""))} 
                     for f in folders if f.get("parent_id")]
            
            if params:
                session.run(query, folders=params)
                self.stats["child_of_rels"] = len(params)

    def create_same_as_relationships(self, persons):
        """SAME_AS 관계 생성 (이름 기준)"""
        log("SAME_AS 관계 검색 중...")
        with self.driver.session() as session:
            for person in persons:
                name = person.get("name") or person.get("person_name", "")
                if not name:
                    continue
                
                # 같은 이름의 기존 person/contact 노드 찾기
                query = """
                MATCH (syno:Entity:synology_person {id: 'synology_person:' + $person_id})
                MATCH (other:Entity)
                WHERE (other:person OR other:contact)
                  AND other.name = $name
                  AND syno.id <> other.id
                MERGE (syno)-[r:SAME_AS]->(other)
                ON CREATE SET r.source = 'synology_photos', r.created_at = datetime()
                RETURN count(r) as rel_count
                """
                
                result = session.run(query, person_id=str(person.get("id", "")), name=name)
                record = result.single()
                if record and record["rel_count"] > 0:
                    self.stats["same_as_rels"] += record["rel_count"]

    def sync(self, data_file):
        """메인 동기화 함수"""
        log("=" * 60)
        log("Synology Photos → Neo4j 동기화 시작")
        log("=" * 60)
        
        # 데이터 로드
        log(f"데이터 로드 중: {data_file}")
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 연결 테스트
        if not self.test_connection():
            return 1
        
        # 데이터 추출
        personal_items = data.get("personal_items", [])
        team_items = data.get("team_items", [])
        personal_persons = data.get("personal_persons", [])
        team_persons = data.get("team_persons", [])
        personal_folders = data.get("personal_folders", [])
        team_folders = data.get("team_folders", [])
        
        all_photos = personal_items + team_items
        all_persons = personal_persons + team_persons
        all_folders = personal_folders + team_folders
        
        log(f"로드 완료:")
        log(f"  사진: {len(all_photos):,}개 (개인 {len(personal_items):,} + 팀 {len(team_items):,})")
        log(f"  인물: {len(all_persons):,}개")
        log(f"  폴�더: {len(all_folders):,}개")
        
        # 기존 데이터 정리
        self.clear_existing_data()
        
        # 1. 폴�더 생성
        if all_folders:
            log(f"폴�더 노드 생성 중... ({len(all_folders):,}개)")
            self.create_folders_batch(all_folders)
            log(f"✓ 폴�더 생성 완료: {self.stats['folders_created']:,}개")
        
        # 2. 인물 생성
        if all_persons:
            log(f"인물 노드 생성 중... ({len(all_persons):,}개)")
            self.create_persons_batch(all_persons)
            log(f"✓ 인물 생성 완료: {self.stats['persons_created']:,}개")
        
        # 3. 사진 생성
        if all_photos:
            log(f"사진 노드 생성 중... ({len(all_photos):,}개)")
            self.create_photos_batch(all_photos)
            log(f"✓ 사진 생성 완료: {self.stats['photos_created']:,}개")
        
        # 4. 관계 생성
        if all_folders:
            self.create_child_of_relationships(all_folders)
            log(f"✓ CHILD_OF 관계: {self.stats['child_of_rels']:,}개")
        
        if all_photos:
            self.create_in_folder_relationships(all_photos)
            log(f"✓ IN_FOLDER 관계: {self.stats['in_folder_rels']:,}개")
        
        if all_persons:
            self.create_same_as_relationships(all_persons)
            log(f"✓ SAME_AS 관계: {self.stats['same_as_rels']:,}개")
        
        # 최종 통계
        log("=" * 60)
        log("동기화 완료!")
        log("=" * 60)
        log(f"생성된 노드:")
        log(f"  - synology_photo: {self.stats['photos_created']:,}개")
        log(f"  - synology_folder: {self.stats['folders_created']:,}개")
        log(f"  - synology_person: {self.stats['persons_created']:,}개")
        log(f"생성된 관계:")
        log(f"  - IN_FOLDER: {self.stats['in_folder_rels']:,}개")
        log(f"  - CHILD_OF: {self.stats['child_of_rels']:,}개")
        log(f"  - SAME_AS: {self.stats['same_as_rels']:,}개")
        
        return 0


def main():
    if len(sys.argv) < 2:
        data_file = "~/Development/talkdrive-backup/data/photos_export.json"
    else:
        data_file = sys.argv[1]
    
    # ~ 확장
    data_file = data_file.replace("~", "/Users/hyoseop1231")
    
    sync = Neo4jSync(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    try:
        result = sync.sync(data_file)
    finally:
        sync.close()
    
    return result


if __name__ == "__main__":
    sys.exit(main())
