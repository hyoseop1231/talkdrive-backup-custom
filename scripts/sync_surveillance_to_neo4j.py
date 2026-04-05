#!/usr/bin/env python3
"""
Synology Surveillance Station → Neo4j 동기화 스크립트

- surveillance_camera 노드 (4대)
- surveillance_recording 노드 (5,641건)
- RECORDED_BY 관계
- LOCATED_IN 관계 (방 위치)
"""

import json
import os
from datetime import datetime
from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "CHANGE_ME_PASSWORD")
BATCH_SIZE = 200

def load_data(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def unix_to_iso(unix_ts):
    """Unix timestamp to ISO 8601 string"""
    if not unix_ts:
        return None
    try:
        dt = datetime.utcfromtimestamp(int(unix_ts))
        return dt.isoformat() + "Z"
    except:
        return str(unix_ts)

class SurveillanceSync:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
    
    def close(self):
        self.driver.close()
    
    def sync_cameras(self, cameras):
        """침라 노드 생성"""
        query = """
        MERGE (c:Entity {id: $id})
        SET c:surveillance_camera
        SET c.name = $name,
            c.model = $model,
            c.host = $host,
            c.enabled = $enabled,
            c.status = $status,
            c.location = $location,
            c.source = 'surveillance_station',
            c.created_at = coalesce(c.created_at, datetime()),
            c.updated_at = datetime()
        RETURN c.id as id
        """
        
        with self.driver.session() as session:
            for cam in cameras:
                node_id = f"surveillance_camera:{cam['id']}"
                result = session.run(query, {
                    "id": node_id,
                    "name": cam.get("name"),
                    "model": cam.get("model"),
                    "host": cam.get("host"),
                    "enabled": cam.get("enabled", True),
                    "status": cam.get("status"),
                    "location": cam.get("location")
                })
                record = result.single()
                if record:
                    print(f"  Synced camera: {cam['name']} ({cam['id']})")
    
    def sync_locations(self, cameras):
        """방 위치 노드 생성 및 연결"""
        # Get unique locations
        locations = set()
        for cam in cameras:
            if cam.get("location"):
                locations.add(cam["location"])
        
        # Create location nodes
        location_query = """
        MERGE (l:Entity {type: "location", name: $name})
        SET l.source = 'surveillance_station',
            l.created_at = coalesce(l.created_at, datetime()),
            l.updated_at = datetime()
        RETURN l.name as name
        """
        
        # Link cameras to locations
        link_query = """
        MATCH (c:Entity:surveillance_camera {id: $cam_id})
        MATCH (l:Entity {type: "location", name: $location})
        MERGE (c)-[:LOCATED_IN]->(l)
        """
        
        with self.driver.session() as session:
            for loc in locations:
                session.run(location_query, {"name": loc})
                print(f"  Created location: {loc}")
            
            for cam in cameras:
                if cam.get("location"):
                    cam_id = f"surveillance_camera:{cam['id']}"
                    session.run(link_query, {
                        "cam_id": cam_id,
                        "location": cam["location"]
                    })
    
    def sync_recordings(self, recordings, batch_size=BATCH_SIZE):
        """녹화 이벤트 노드 생성 (batch 처리)"""
        query = """
        UNWIND $batch as rec
        MERGE (r:Entity {id: rec.node_id})
        SET r:surveillance_recording
        SET r.camera_id = rec.camera_id,
            r.camera_name = rec.camera_name,
            r.start_time = rec.start_time,
            r.start_time_iso = rec.start_time_iso,
            r.stop_time = rec.stop_time,
            r.duration_seconds = rec.duration,
            r.event_size = rec.event_size,
            r.event_size_bytes = rec.event_size_bytes,
            r.event_type = rec.event_type,
            r.path = rec.path,
            r.recording = rec.recording,
            r.source = 'surveillance_station',
            r.created_at = coalesce(r.created_at, datetime()),
            r.updated_at = datetime()
        WITH r, rec
        MATCH (c:Entity:surveillance_camera {id: rec.cam_node_id})
        MERGE (r)-[:RECORDED_BY]->(c)
        RETURN count(r) as count
        """
        
        total = len(recordings)
        processed = 0
        
        with self.driver.session() as session:
            for i in range(0, total, batch_size):
                batch = recordings[i:i+batch_size]
                
                # Prepare batch data
                batch_data = []
                for rec in batch:
                    batch_data.append({
                        "node_id": f"surveillance_recording:{rec['id']}",
                        "cam_node_id": f"surveillance_camera:{rec['camera_id']}",
                        "camera_id": rec.get("camera_id"),
                        "camera_name": rec.get("camera_name"),
                        "start_time": rec.get("start_time"),
                        "start_time_iso": unix_to_iso(rec.get("start_time")),
                        "stop_time": rec.get("stop_time"),
                        "duration": rec.get("duration", 0),
                        "event_size": rec.get("event_size"),
                        "event_size_bytes": rec.get("event_size_bytes"),
                        "event_type": str(rec.get("event_type", "normal")),
                        "path": rec.get("path"),
                        "recording": rec.get("recording", False)
                    })
                
                result = session.run(query, {"batch": batch_data})
                count = result.single()["count"]
                processed += len(batch)
                
                print(f"  Batch {i//batch_size + 1}: {processed}/{total} recordings synced")
    
    def get_stats(self):
        """동기화 결과 통계"""
        queries = {
            "cameras": "MATCH (c:surveillance_camera) RETURN count(c) as count",
            "recordings": "MATCH (r:surveillance_recording) RETURN count(r) as count",
            "recorded_by": "MATCH ()-[r:RECORDED_BY]->() RETURN count(r) as count",
            "located_in": "MATCH ()-[r:LOCATED_IN]->() RETURN count(r) as count",
            "locations": "MATCH (l:Entity {type: 'location'}) RETURN count(l) as count"
        }
        
        stats = {}
        with self.driver.session() as session:
            for name, query in queries.items():
                result = session.run(query)
                stats[name] = result.single()["count"]
        
        return stats

def main():
    filepath = os.path.expanduser("~/Development/talkdrive-backup/data/surveillance_export.json")
    
    print("Loading data...")
    data = load_data(filepath)
    cameras = data["cameras"]
    recordings = data["recordings"]
    
    print(f"Loaded {len(cameras)} cameras, {len(recordings)} recordings")
    
    print("\nConnecting to Neo4j...")
    sync = SurveillanceSync(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    
    try:
        print("\n1. Syncing cameras...")
        sync.sync_cameras(cameras)
        
        print("\n2. Syncing locations...")
        sync.sync_locations(cameras)
        
        print("\n3. Syncing recordings...")
        sync.sync_recordings(recordings, BATCH_SIZE)
        
        print("\n4. Getting statistics...")
        stats = sync.get_stats()
        
        print("\n" + "="*50)
        print("SYNC COMPLETE")
        print("="*50)
        print(f"Cameras:       {stats['cameras']}")
        print(f"Recordings:    {stats['recordings']}")
        print(f"Locations:     {stats['locations']}")
        print(f"Recorded By:   {stats['recorded_by']} relations")
        print(f"Located In:    {stats['located_in']} relations")
        print("="*50)
        
    finally:
        sync.close()

if __name__ == "__main__":
    main()
