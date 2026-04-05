#!/usr/bin/env python3
"""
Synology Photos 메타데이터 Export 스크립트 (NAS에서 실행)
- 개인 공간: SYNO.Foto.Browse.Item
- 팀 공간: SYNO.FotoTeam.Browse.Item (150,817장)
- 인물: SYNO.FotoTeam.Browse.Person
- 폴�더: SYNO.FotoTeam.Browse.Folder
"""

import json
import sys
import time
import urllib.request
import urllib.parse
import ssl
from datetime import datetime

# 설정
DSM_HOST = "127.0.0.1"
DSM_PORT = 9914
USERNAME = "hyoseop1231"
PASSWORD = "#Wjftpalska9914k"
BATCH_SIZE = 500
OUTPUT_FILE = "photos_export.json"

# SSL 검증 무시 (자체 서명 인증서)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


def log(msg):
    """타임스탬프와 함께 로그 출력"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def login():
    """DSM에 로그인하고 SID 반환"""
    url = f"https://{DSM_HOST}:{DSM_PORT}/webapi/entry.cgi"
    data = {
        "api": "SYNO.API.Auth",
        "version": "6",
        "method": "login",
        "account": USERNAME,
        "passwd": PASSWORD
    }
    
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    with urllib.request.urlopen(req, context=ssl_context, timeout=30) as resp:
        result = json.loads(resp.read().decode())
        if result.get("success"):
            sid = result["data"]["sid"]
            log(f"✓ 로그인 성공 (SID: {sid[:10]}...)")
            return sid
        else:
            raise Exception(f"로그인 실패: {result}")


def fetch_items(sid, api, offset=0, limit=500):
    """사진 아이템 목록 조회"""
    url = f"https://{DSM_HOST}:{DSM_PORT}/webapi/entry.cgi"
    data = {
        "api": api,
        "version": "6",
        "method": "list",
        "offset": offset,
        "limit": limit,
        "sort_by": "takentime",
        "sort_direction": "desc",
        "_sid": sid
    }
    
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    with urllib.request.urlopen(req, context=ssl_context, timeout=60) as resp:
        return json.loads(resp.read().decode())


def fetch_persons(sid, api, offset=0, limit=500):
    """인물 목록 조회"""
    url = f"https://{DSM_HOST}:{DSM_PORT}/webapi/entry.cgi"
    data = {
        "api": api,
        "version": "3",
        "method": "list",
        "offset": offset,
        "limit": limit,
        "_sid": sid
    }
    
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    with urllib.request.urlopen(req, context=ssl_context, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_folders(sid, api, offset=0, limit=500):
    """폴�더 목록 조회"""
    url = f"https://{DSM_HOST}:{DSM_PORT}/webapi/entry.cgi"
    data = {
        "api": api,
        "version": "2",
        "method": "list",
        "offset": offset,
        "limit": limit,
        "_sid": sid
    }
    
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    with urllib.request.urlopen(req, context=ssl_context, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_all_items(sid, api_name, api_path):
    """페이징으로 모든 아이템 수집"""
    all_items = []
    offset = 0
    total = None
    
    log(f"📸 {api_name} 수집 시작...")
    
    while True:
        try:
            result = fetch_items(sid, api_path, offset, BATCH_SIZE)
            
            if not result.get("success"):
                log(f"⚠️ API 오류: {result.get('error', 'unknown')}")
                break
            
            data = result.get("data", {})
            items = data.get("list", [])
            
            if total is None:
                total = data.get("total", 0)
                log(f"  총 {total:,}개 아이템 예상")
            
            all_items.extend(items)
            
            fetched = len(items)
            log(f"  offset={offset:,}, fetched={fetched:,}, total_collected={len(all_items):,}")
            
            if fetched < BATCH_SIZE or (total and len(all_items) >= total):
                break
            
            offset += BATCH_SIZE
            time.sleep(0.1)  # 서버 부하 방지
            
        except Exception as e:
            log(f"⚠️ 오류 발생 (offset={offset}): {e}")
            time.sleep(1)
            continue
    
    log(f"✓ {api_name}: {len(all_items):,}개 수집 완료")
    return all_items


def fetch_all_persons(sid, api_name, api_path):
    """페이징으로 모든 인물 수집"""
    all_persons = []
    offset = 0
    total = None
    
    log(f"👤 {api_name} 수집 시작...")
    
    while True:
        try:
            result = fetch_persons(sid, api_path, offset, BATCH_SIZE)
            
            if not result.get("success"):
                log(f"⚠️ API 오류: {result.get('error', 'unknown')}")
                break
            
            data = result.get("data", {})
            persons = data.get("list", [])
            
            if total is None:
                total = data.get("total", 0)
                log(f"  총 {total:,}개 인물 예상")
            
            all_persons.extend(persons)
            
            fetched = len(persons)
            log(f"  offset={offset:,}, fetched={fetched:,}, total_collected={len(all_persons):,}")
            
            if fetched < BATCH_SIZE or (total and len(all_persons) >= total):
                break
            
            offset += BATCH_SIZE
            time.sleep(0.1)
            
        except Exception as e:
            log(f"⚠️ 오류 발생 (offset={offset}): {e}")
            time.sleep(1)
            continue
    
    log(f"✓ {api_name}: {len(all_persons):,}개 수집 완료")
    return all_persons


def fetch_all_folders(sid, api_name, api_path):
    """페이징으로 모든 폴�더 수집"""
    all_folders = []
    offset = 0
    total = None
    
    log(f"📁 {api_name} 수집 시작...")
    
    while True:
        try:
            result = fetch_folders(sid, api_path, offset, BATCH_SIZE)
            
            if not result.get("success"):
                log(f"⚠️ API 오류: {result.get('error', 'unknown')}")
                break
            
            data = result.get("data", {})
            folders = data.get("list", [])
            
            if total is None:
                total = data.get("total", 0)
                log(f"  총 {total:,}개 폴�더 예상")
            
            all_folders.extend(folders)
            
            fetched = len(folders)
            log(f"  offset={offset:,}, fetched={fetched:,}, total_collected={len(all_folders):,}")
            
            if fetched < BATCH_SIZE or (total and len(all_folders) >= total):
                break
            
            offset += BATCH_SIZE
            time.sleep(0.1)
            
        except Exception as e:
            log(f"⚠️ 오류 발생 (offset={offset}): {e}")
            time.sleep(1)
            continue
    
    log(f"✓ {api_name}: {len(all_folders):,}개 수집 완료")
    return all_folders


def main():
    log("=" * 60)
    log("Synology Photos 메타데이터 Export 시작")
    log("=" * 60)
    
    try:
        # 로그인
        sid = login()
        
        # 1. 개인 공간 아이템 (499장)
        personal_items = fetch_all_items(sid, "개인 공간", "SYNO.Foto.Browse.Item")
        
        # 2. 팀 공간 아이템 (150,817장)
        team_items = fetch_all_items(sid, "팀 공간", "SYNO.FotoTeam.Browse.Item")
        
        # 3. 개인 공간 인물
        personal_persons = fetch_all_persons(sid, "개인 인물", "SYNO.Foto.Browse.Person")
        
        # 4. 팀 공간 인물
        team_persons = fetch_all_persons(sid, "팀 인물", "SYNO.FotoTeam.Browse.Person")
        
        # 5. 개인 공간 폴�더
        personal_folders = fetch_all_folders(sid, "개인 폴�더", "SYNO.Foto.Browse.Folder")
        
        # 6. 팀 공간 폴�더
        team_folders = fetch_all_folders(sid, "팀 폴�더", "SYNO.FotoTeam.Browse.Folder")
        
        # 결과 저장
        export_data = {
            "exported_at": datetime.now().isoformat(),
            "personal_items": personal_items,
            "team_items": team_items,
            "personal_persons": personal_persons,
            "team_persons": team_persons,
            "personal_folders": personal_folders,
            "team_folders": team_folders,
            "stats": {
                "personal_item_count": len(personal_items),
                "team_item_count": len(team_items),
                "personal_person_count": len(personal_persons),
                "team_person_count": len(team_persons),
                "personal_folder_count": len(personal_folders),
                "team_folder_count": len(team_folders)
            }
        }
        
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        log("=" * 60)
        log("Export 완료!")
        log(f"  파일: {OUTPUT_FILE}")
        log(f"  개인 아이템: {len(personal_items):,}개")
        log(f"  팀 아이템: {len(team_items):,}개")
        log(f"  개인 인물: {len(personal_persons):,}개")
        log(f"  팀 인물: {len(team_persons):,}개")
        log(f"  개인 폴�더: {len(personal_folders):,}개")
        log(f"  팀 폴�더: {len(team_folders):,}개")
        log("=" * 60)
        
        return 0
        
    except Exception as e:
        log(f"❌ 오류: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
