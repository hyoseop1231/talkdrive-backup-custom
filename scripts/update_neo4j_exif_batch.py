#!/usr/bin/env python3
"""
Synology Photos EXIF 메타데이터를 Neo4j에 업데이트 (배치 처리)
"""

import json
import os
import sys
from datetime import datetime
from neo4j import GraphDatabase

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def escape_string(s):
    """Cypher 문자열 이스케이프"""
    if not s:
        return ""
    s = str(s)
    s = s.replace('\\', '\\\\')
    s = s.replace('"', '\\"')
    s = s.replace('\n', ' ').replace('\r', '')
    return s

def main():
    log("=" * 60)
    log("Neo4j EXIF 메타데이터 업데이트 시작 (배치 처리)")
    log("=" * 60)
    
    # Neo4j 연결
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    auth = ("neo4j", "CHANGE_ME_PASSWORD")
    
    try:
        driver = GraphDatabase.driver(uri, auth=auth)
        with driver.session() as session:
            # 연결 확인
            result = session.run("MATCH (n) RETURN count(n) LIMIT 1")
            count = result.single()[0]
            log(f"✓ Neo4j 연결 성공: 전체 노드 수 {count:,}")
            
            # 기존 synology_photo 노드 수 확인
            result = session.run("MATCH (p:synology_photo) RETURN count(p)")
            photo_count = result.single()[0]
            log(f"기존 synology_photo 노드 수: {photo_count:,}")
        driver.close()
    except Exception as e:
        log(f"❌ Neo4j 연결 실패: {e}")
        return 1
    
    # JSON 데이터 로드
    log("JSON 데이터 로드 중...")
    with open('/Users/hyoseop1231/Development/talkdrive-backup/data/photos_export.json', 'r') as f:
        data = json.load(f)
    
    all_items = data['personal_items'] + data['team_items']
    total = len(all_items)
    log(f"총 {total:,}개 사진 처리 예정")
    
    # 배치 처리
    BATCH_SIZE = 500
    total_updated = 0
    total_skipped = 0
    
    driver = GraphDatabase.driver(uri, auth=auth)
    
    with driver.session() as session:
        for batch_start in range(0, total, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total)
            batch = all_items[batch_start:batch_end]
            
            # 배치 데이터 준비
            updates = []
            for item in batch:
                photo_id = item['id']
                additional = item.get('additional', {})
                
                update_data = {'id': photo_id}
                has_data = False
                
                # GPS
                gps = additional.get('gps', {})
                if gps:
                    lat = gps.get('latitude')
                    lon = gps.get('longitude')
                    if lat is not None:
                        update_data['latitude'] = lat
                        has_data = True
                    if lon is not None:
                        update_data['longitude'] = lon
                        has_data = True
                
                # Resolution
                resolution = additional.get('resolution', {})
                if resolution:
                    width = resolution.get('width')
                    height = resolution.get('height')
                    if width:
                        update_data['resolution_width'] = width
                        has_data = True
                    if height:
                        update_data['resolution_height'] = height
                        has_data = True
                
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
                        update_data['camera_model'] = camera
                        has_data = True
                    if aperture:
                        update_data['aperture'] = aperture
                        has_data = True
                    if exposure:
                        update_data['exposure_time'] = exposure
                        has_data = True
                    if focal:
                        update_data['focal_length'] = focal
                        has_data = True
                    if iso:
                        update_data['iso'] = iso
                        has_data = True
                    if lens:
                        update_data['lens'] = lens
                        has_data = True
                
                # Address
                address = additional.get('address', {})
                if address:
                    country = address.get('country') or address.get('country_id')
                    city = address.get('city') or address.get('city_id')
                    route = address.get('route') or address.get('route_id')
                    
                    if country:
                        update_data['address_country'] = country
                        has_data = True
                    if city:
                        update_data['address_city'] = city
                        has_data = True
                    if route:
                        update_data['address_route'] = route
                        has_data = True
                
                if has_data:
                    updates.append(update_data)
                else:
                    total_skipped += 1
            
            if not updates:
                continue
            
            # 배치 업데이트 쿼리
            query = """
            UNWIND $updates AS update
            MATCH (p:synology_photo {id: update.id})
            SET p.latitude = update.latitude,
                p.longitude = update.longitude,
                p.resolution_width = update.resolution_width,
                p.resolution_height = update.resolution_height,
                p.camera_model = update.camera_model,
                p.aperture = update.aperture,
                p.exposure_time = update.exposure_time,
                p.focal_length = update.focal_length,
                p.iso = update.iso,
                p.lens = update.lens,
                p.address_country = update.address_country,
                p.address_city = update.address_city,
                p.address_route = update.address_route,
                p.exif_updated = datetime()
            RETURN count(p) AS updated_count
            """
            
            try:
                result = session.run(query, updates=updates)
                updated_count = result.single()[0]
                total_updated += updated_count
            except Exception as e:
                log(f"⚠️ 배치 오류 ({batch_start}-{batch_end}): {e}")
            
            # 진행 상황 출력
            if (batch_end // BATCH_SIZE) % 10 == 0:
                log(f"  진행: {batch_end:,}/{total:,} (업데이트: {total_updated:,}, 스킵: {total_skipped:,})")
    
    driver.close()
    
    log("=" * 60)
    log("업데이트 완료!")
    log(f"  총 처리: {total:,}")
    log(f"  업데이트: {total_updated:,}")
    log(f"  스킵 (메타데이터 없음): {total_skipped:,}")
    log("=" * 60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
