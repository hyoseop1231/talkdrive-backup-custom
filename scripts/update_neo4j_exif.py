#!/usr/bin/env python3
"""
Synology Photos EXIF 메타데이터를 Neo4j에 업데이트
"""

import json
import subprocess
import sys
import re
from datetime import datetime

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def escape_string(s):
    """Cypher 문자열 이스케이프"""
    if not s:
        return ""
    # 백슬래시 먼저 처리
    s = s.replace('\\', '\\\\')
    # 따옴표 처리
    s = s.replace('"', '\\"')
    # 줄바꿈 제거
    s = s.replace('\n', ' ').replace('\r', '')
    return s

def run_cypher(query):
    """cypher-shell을 통해 Neo4j 쿼리 실행"""
    # 쿼리를 파일로 저장
    query_file = '/tmp/neo4j_query.cypher'
    with open(query_file, 'w') as f:
        f.write(query)
    
    cmd = [
        'ssh', 'user@example-host',
        f'docker exec -i neo4j cypher-shell -u neo4j -p CHANGE_ME_PASSWORD --non-interactive --format plain < /tmp/neo4j_query.cypher'
    ]
    try:
        result = subprocess.run(' '.join(cmd), shell=True, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return result.stdout
        else:
            err = result.stderr[:200] if result.stderr else "Unknown error"
            log(f"⚠️ 쿼리 오류: {err}")
            return None
    except Exception as e:
        log(f"⚠️ 실행 오류: {e}")
        return None

def main():
    log("=" * 60)
    log("Neo4j EXIF 메타데이터 업데이트 시작")
    log("=" * 60)
    
    # JSON 데이터 로드
    with open('/Users/hyoseop1231/Development/talkdrive-backup/data/photos_export.json', 'r') as f:
        data = json.load(f)
    
    all_items = data['personal_items'] + data['team_items']
    total = len(all_items)
    log(f"총 {total:,}개 사진 처리 예정")
    
    # Neo4j 연결 확인
    log("Neo4j 연결 확인 중...")
    result = run_cypher("MATCH (n) RETURN count(n) LIMIT 1")
    if result:
        log(f"✓ Neo4j 연결 성공: {result.strip()}")
    else:
        log("❌ Neo4j 연결 실패")
        return 1
    
    # 기존 synology_photo 노드 수 확인
    result = run_cypher("MATCH (p:synology_photo) RETURN count(p)")
    if result:
        log(f"기존 synology_photo 노드 수: {result.strip()}")
    
    # 업데이트 진행
    updated = 0
    skipped = 0
    errors = 0
    
    for i, item in enumerate(all_items):
        photo_id = item['id']
        additional = item.get('additional', {})
        
        # 업데이트할 필드 준비
        fields = []
        
        # GPS
        gps = additional.get('gps', {})
        if gps:
            lat = gps.get('latitude')
            lon = gps.get('longitude')
            if lat is not None:
                fields.append(f"p.latitude = {lat}")
            if lon is not None:
                fields.append(f"p.longitude = {lon}")
        
        # Resolution
        resolution = additional.get('resolution', {})
        if resolution:
            width = resolution.get('width')
            height = resolution.get('height')
            if width:
                fields.append(f"p.resolution_width = {width}")
            if height:
                fields.append(f"p.resolution_height = {height}")
        
        # EXIF
        exif = additional.get('exif', {})
        if exif:
            camera = exif.get('camera')
            aperture = exif.get('aperture')
            exposure = exif.get('exposure_time')
            focal = exif.get('focal_length')
            iso = exif.get('iso')
            lens = exif.get('lens')
            
            if camera:
                fields.append(f'p.camera_model = "{escape_string(camera)}"')
            if aperture:
                fields.append(f'p.aperture = "{escape_string(aperture)}"')
            if exposure:
                fields.append(f'p.exposure_time = "{escape_string(exposure)}"')
            if focal:
                fields.append(f'p.focal_length = "{escape_string(focal)}"')
            if iso:
                fields.append(f'p.iso = "{escape_string(iso)}"')
            if lens:
                fields.append(f'p.lens = "{escape_string(lens)}"')
        
        # Address
        address = additional.get('address', {})
        if address:
            country = address.get('country') or address.get('country_id')
            city = address.get('city') or address.get('city_id')
            route = address.get('route') or address.get('route_id')
            
            if country:
                fields.append(f'p.address_country = "{escape_string(country)}"')
            if city:
                fields.append(f'p.address_city = "{escape_string(city)}"')
            if route:
                fields.append(f'p.address_route = "{escape_string(route)}"')
        
        # 업데이트할 필드가 없으면 스킵
        if not fields:
            skipped += 1
            continue
        
        # Cypher 쿼리 생성
        set_clause = ', '.join(fields)
        query = f"MATCH (p:synology_photo {{id: {photo_id}}}) SET {set_clause}, p.exif_updated = datetime() RETURN count(p)"
        
        # 쿼리 실행
        result = run_cypher(query)
        if result and ('1' in result or 'count' in result.lower()):
            updated += 1
        else:
            errors += 1
            if errors <= 5:  # 처음 5개 오류만 출력
                log(f"⚠️ 업데이트 실패 - ID: {photo_id}")
        
        # 진행 상황 출력 (매 1000건)
        if (i + 1) % 1000 == 0:
            log(f"  진행: {i+1:,}/{total:,} (업데이트: {updated:,}, 스킵: {skipped:,}, 오류: {errors:,})")
    
    log("=" * 60)
    log("업데이트 완료!")
    log(f"  총 처리: {total:,}")
    log(f"  업데이트: {updated:,}")
    log(f"  스킵 (메타데이터 없음): {skipped:,}")
    log(f"  오류: {errors:,}")
    log("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
