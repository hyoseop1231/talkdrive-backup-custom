#!/usr/bin/env python3
"""
KidsNote JSON → Neo4j 동기화 스크립트
"""
import json
import os
from neo4j import GraphDatabase
from typing import Any

# 설정
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "CHANGE_ME_PASSWORD"
JSON_PATH = "/Users/hyoseop1231/Development/talkdrive-backup/data/kidsnote_export.json"
BATCH_SIZE = 100

def clean_value(v: Any) -> Any:
    """모든 값을 primitive로 변환 (Neo4j property 저장용)"""
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v

def clean_props(props: dict) -> dict:
    """모든 property 값을 primitive로 변환"""
    return {k: clean_value(v) for k, v in props.items()}

def sync_kidsnote():
    # JSON 로드
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"📦 Export timestamp: {data['export_timestamp']}")
    print(f"👶 Children: {len(data['children'])}")
    print(f"📝 Reports: {len(data['reports'])}")
    print(f"📸 Albums: {len(data['albums'])}")
    print(f"👩‍🏫 Teachers: {len(data['teachers'])}")
    print(f"🏢 Centers: {len(data['centers'])}")
    
    # Neo4j 연결
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    node_counts = {}
    rel_counts = {}
    
    with driver.session() as session:
        # --- 1. Centers (어린이집) ---
        print("\n🏢 Centers 동기화...")
        center_ids = set()
        for center in data['centers']:
            props = clean_props({
                'id': f"kidsnote_center:{center['id']}",
                'kidsnote_id': center['id'],
                'name': center.get('name', ''),
                'address': center.get('address', ''),
                'phone': center.get('phone', ''),
                'type': 'kidsnote_center'
            })
            
            session.run("""
                MERGE (n:Entity {id: $id})
                SET n:kidsnote_center
                SET n += $props
                SET n.source = 'kidsnote',
                    n.updated_at = datetime(),
                    n.created_at = coalesce(n.created_at, datetime())
            """, id=props['id'], props=props)
            center_ids.add(center['id'])
        
        node_counts['centers'] = len(center_ids)
        print(f"  ✓ {len(center_ids)} centers")
        
        # --- 2. Teachers (교사) ---
        print("\n👩‍🏫 Teachers 동기화...")
        teacher_map = {}  # id -> node_id
        teacher_center_map = {}  # teacher_id -> center_id (from reports/albums)
        
        for teacher in data['teachers']:
            node_id = f"kidsnote_teacher:{teacher['id']}"
            props = clean_props({
                'id': node_id,
                'kidsnote_id': teacher['id'],
                'name': teacher.get('name', ''),
                'role': teacher.get('role', ''),
                'center': teacher.get('center', ''),
                'type': 'kidsnote_teacher'
            })
            
            session.run("""
                MERGE (n:Entity {id: $id})
                SET n:kidsnote_teacher
                SET n += $props
                SET n.source = 'kidsnote',
                    n.updated_at = datetime(),
                    n.created_at = coalesce(n.created_at, datetime())
            """, id=node_id, props=props)
            teacher_map[teacher['id']] = node_id
        
        node_counts['teachers'] = len(teacher_map)
        print(f"  ✓ {len(teacher_map)} teachers")
        
        # Teacher center 추론 (from reports and albums)
        for report in data['reports']:
            if report.get('author_id') and report.get('center_id') and report['center_id'] != 'None':
                teacher_center_map[report['author_id']] = report['center_id']
        
        for album in data['albums']:
            if album.get('author_id') and album.get('center_id') and album['center_id'] != 'None':
                teacher_center_map[album['author_id']] = album['center_id']
        
        # Teacher -> Center 관계
        rel_count = 0
        for teacher_id, center_id in teacher_center_map.items():
            if teacher_id in teacher_map and center_id:
                session.run("""
                    MATCH (t:Entity {id: $teacher_id})
                    MATCH (c:Entity {id: $center_id})
                    MERGE (t)-[:WORKS_AT]->(c)
                """, teacher_id=teacher_map[teacher_id], 
                     center_id=f"kidsnote_center:{center_id}")
                rel_count += 1
        rel_counts['teacher_works_at'] = rel_count
        print(f"  ✓ {rel_count} WORKS_AT relations")
        
        # --- 3. Children (아이들) ---
        print("\n👶 Children 동기화...")
        child_map = {}  # id -> node_id
        child_center_map = {}  # child_id -> center_id (from albums)
        
        for child in data['children']:
            node_id = f"kidsnote_child:{child['id']}"
            props = clean_props({
                'id': node_id,
                'kidsnote_id': child['id'],
                'name': child.get('name', ''),
                'child_id': child['id'],
                'dob': child.get('birth', ''),
                'gender': child.get('gender', ''),
                'center_name': child.get('center_name', ''),
                'type': 'kidsnote_child'
            })
            
            session.run("""
                MERGE (n:Entity {id: $id})
                SET n:kidsnote_child
                SET n += $props
                SET n.source = 'kidsnote',
                    n.updated_at = datetime(),
                    n.created_at = coalesce(n.created_at, datetime())
            """, id=node_id, props=props)
            child_map[str(child['id'])] = node_id
        
        node_counts['children'] = len(child_map)
        print(f"  ✓ {len(child_map)} children")
        
        # Child center 추론 (from albums)
        for album in data['albums']:
            if album.get('child_id') and album.get('center_id') and album['center_id'] != 'None':
                child_center_map[str(album['child_id'])] = album['center_id']
        
        # Child -> Center 관계
        rel_count = 0
        for child_id, center_id in child_center_map.items():
            if child_id in child_map and center_id:
                session.run("""
                    MATCH (ch:Entity {id: $child_id})
                    MATCH (c:Entity {id: $center_id})
                    MERGE (ch)-[:ATTENDS]->(c)
                """, child_id=child_map[child_id], 
                     center_id=f"kidsnote_center:{center_id}")
                rel_count += 1
        rel_counts['child_attends'] = rel_count
        print(f"  ✓ {rel_count} ATTENDS relations")
        
        # --- 4. Reports (알림장) ---
        print("\n📝 Reports 동기화...")
        report_count = 0
        about_count = 0
        written_by_count = 0
        
        for i, report in enumerate(data['reports']):
            node_id = f"kidsnote_report:{report['id']}"
            props = clean_props({
                'id': node_id,
                'kidsnote_id': report['id'],
                'report_id': report['id'],
                'title': report.get('title', ''),
                'content': report.get('text', ''),
                'date': report.get('date', ''),
                'author': report.get('author_name', ''),
                'child_id': str(report.get('child_id', '')),
                'photos': report.get('photos', []),
                'type': 'kidsnote_report'
            })
            
            session.run("""
                MERGE (n:Entity {id: $id})
                SET n:kidsnote_report
                SET n += $props
                SET n.source = 'kidsnote',
                    n.updated_at = datetime(),
                    n.created_at = coalesce(n.created_at, datetime())
            """, id=node_id, props=props)
            report_count += 1
            
            # Report -> Child 관계
            child_id = str(report.get('child_id', ''))
            if child_id and child_id in child_map:
                session.run("""
                    MATCH (r:Entity {id: $report_id})
                    MATCH (ch:Entity {id: $child_id})
                    MERGE (r)-[:ABOUT]->(ch)
                """, report_id=node_id, child_id=child_map[child_id])
                about_count += 1
            
            # Report -> Teacher 관계
            author_id = str(report.get('author_id', ''))
            if author_id and author_id in teacher_map:
                session.run("""
                    MATCH (r:Entity {id: $report_id})
                    MATCH (t:Entity {id: $teacher_id})
                    MERGE (r)-[:WRITTEN_BY]->(t)
                """, report_id=node_id, teacher_id=teacher_map[author_id])
                written_by_count += 1
            
            if (i + 1) % BATCH_SIZE == 0:
                print(f"  ... {i + 1}/{len(data['reports'])}")
        
        node_counts['reports'] = report_count
        rel_counts['report_about'] = about_count
        rel_counts['report_written_by'] = written_by_count
        print(f"  ✓ {report_count} reports")
        print(f"  ✓ {about_count} ABOUT relations (report→child)")
        print(f"  ✓ {written_by_count} WRITTEN_BY relations (report→teacher)")
        
        # --- 5. Albums (앨범) ---
        print("\n📸 Albums 동기화...")
        album_count = 0
        album_about_count = 0
        
        for album in data['albums']:
            node_id = f"kidsnote_album:{album['id']}"
            props = clean_props({
                'id': node_id,
                'kidsnote_id': album['id'],
                'album_id': album['id'],
                'title': album.get('title', ''),
                'date': album.get('date', ''),
                'photo_count': album.get('image_count', 0),
                'child_id': str(album.get('child_id', '')),
                'photos': album.get('photos', []),
                'type': 'kidsnote_album'
            })
            
            session.run("""
                MERGE (n:Entity {id: $id})
                SET n:kidsnote_album
                SET n += $props
                SET n.source = 'kidsnote',
                    n.updated_at = datetime(),
                    n.created_at = coalesce(n.created_at, datetime())
            """, id=node_id, props=props)
            album_count += 1
            
            # Album -> Child 관계
            child_id = str(album.get('child_id', ''))
            if child_id and child_id in child_map:
                session.run("""
                    MATCH (a:Entity {id: $album_id})
                    MATCH (ch:Entity {id: $child_id})
                    MERGE (a)-[:ABOUT]->(ch)
                """, album_id=node_id, child_id=child_map[child_id])
                album_about_count += 1
        
        node_counts['albums'] = album_count
        rel_counts['album_about'] = album_about_count
        print(f"  ✓ {album_count} albums")
        print(f"  ✓ {album_about_count} ABOUT relations (album→child)")
        
        # --- 6. Parent (SAME_AS 연결) ---
        print("\n👤 Parent SAME_AS 연결...")
        parent = data['parent']
        parent_node_id = f"kidsnote_parent:{parent['id']}"
        
        # Parent 노드 생성
        props = clean_props({
            'id': parent_node_id,
            'kidsnote_id': parent['id'],
            'name': parent.get('name', ''),
            'username': parent.get('username', ''),
            'email': parent.get('email', ''),
            'type': 'kidsnote_parent'
        })
        
        session.run("""
            MERGE (n:Entity {id: $id})
            SET n:kidsnote_parent
            SET n += $props
            SET n.source = 'kidsnote',
                n.updated_at = datetime(),
                n.created_at = coalesce(n.created_at, datetime())
        """, id=parent_node_id, props=props)
        
        # SAME_AS 연결 (박볼미)
        # kidsnote_parent:2836523 ↔ person:pbm0221@naver.com
        existing_person_id = "person:pbm0221@naver.com"
        result = session.run("""
            MATCH (p:Entity {id: $parent_id})
            MATCH (e:Entity {id: $existing_id})
            MERGE (p)-[:SAME_AS]->(e)
            MERGE (e)-[:SAME_AS]->(p)
            RETURN count(*) as cnt
        """, parent_id=parent_node_id, existing_id=existing_person_id)
        
        record = result.single()
        if record:
            print(f"  ✓ SAME_AS: {parent_node_id} ↔ {existing_person_id}")
            rel_counts['same_as'] = 1
        else:
            print(f"  ⚠ SAME_AS 연결 실패 - 기존 노드 없음: {existing_person_id}")
        
        # Parent -> Child 관계
        parent_of_count = 0
        for child in data['children']:
            session.run("""
                MATCH (p:Entity {id: $parent_id})
                MATCH (c:Entity {id: $child_id})
                MERGE (p)-[:PARENT_OF]->(c)
            """, parent_id=parent_node_id, child_id=child_map[str(child['id'])])
            parent_of_count += 1
        
        rel_counts['parent_of'] = parent_of_count
        print(f"  ✓ PARENT_OF: {parent_of_count} children")
        node_counts['parents'] = 1
        
    driver.close()
    
    # 결과 요약
    print("\n" + "="*50)
    print("✅ 동기화 완료!")
    print("="*50)
    print("\n📊 노드 생성:")
    total_nodes = sum(node_counts.values())
    for label, count in node_counts.items():
        print(f"  • {label}: {count}")
    print(f"  총 노드: {total_nodes}")
    
    print("\n🔗 관계 생성:")
    total_rels = sum(rel_counts.values())
    for rel_type, count in rel_counts.items():
        print(f"  • {rel_type}: {count}")
    print(f"  총 관계: {total_rels}")

if __name__ == "__main__":
    sync_kidsnote()
