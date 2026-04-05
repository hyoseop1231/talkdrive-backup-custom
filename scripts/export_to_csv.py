#!/usr/bin/env python3
"""
Synology Photos EXIF 데이터를 CSV로 변환 (Neo4j LOAD CSV용)
"""

import json
import csv
from datetime import datetime

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

log("JSON → CSV 변환 시작")

# JSON 로드
with open('/Users/hyoseop1231/Development/talkdrive-backup/data/photos_export.json', 'r') as f:
    data = json.load(f)

all_items = data['personal_items'] + data['team_items']
log(f"총 {len(all_items):,}개 사진")

# CSV 헤더
headers = [
    'id', 'latitude', 'longitude', 'resolution_width', 'resolution_height',
    'camera_model', 'aperture', 'exposure_time', 'focal_length', 'iso', 'lens',
    'address_country', 'address_city', 'address_route'
]

# CSV 작성
csv_path = '/Users/hyoseop1231/Development/talkdrive-backup/data/photos_exif.csv'
with open(csv_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=headers)
    writer.writeheader()
    
    count = 0
    for item in all_items:
        photo_id = item['id']
        additional = item.get('additional', {})
        
        row = {'id': photo_id}
        
        # GPS
        gps = additional.get('gps', {})
        if gps:
            row['latitude'] = gps.get('latitude', '')
            row['longitude'] = gps.get('longitude', '')
        
        # Resolution
        resolution = additional.get('resolution', {})
        if resolution:
            row['resolution_width'] = resolution.get('width', '')
            row['resolution_height'] = resolution.get('height', '')
        
        # EXIF
        exif = additional.get('exif', {})
        if exif:
            row['camera_model'] = exif.get('camera', '')
            row['aperture'] = exif.get('aperture', '')
            row['exposure_time'] = exif.get('exposure_time', '')
            row['focal_length'] = exif.get('focal_length', '')
            row['iso'] = exif.get('iso', '')
            row['lens'] = exif.get('lens', '')
        
        # Address
        address = additional.get('address', {})
        if address:
            row['address_country'] = address.get('country') or address.get('country_id', '')
            row['address_city'] = address.get('city') or address.get('city_id', '')
            row['address_route'] = address.get('route') or address.get('route_id', '')
        
        writer.writerow(row)
        count += 1
        
        if count % 10000 == 0:
            log(f"  진행: {count:,}/{len(all_items):,}")

log(f"✓ CSV 저장 완료: {csv_path}")
log(f"총 {count:,}개 레코드")
