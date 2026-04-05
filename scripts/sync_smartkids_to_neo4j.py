#!/usr/bin/env python3
"""
SmartKids WordPress → Neo4j 동기화 스크립트

WordPress에서 4컷 만화, 스토리, 앨범/사진 데이터를 조회하여
Neo4j 지식그래프에 동기화합니다.

Usage:
    python3 sync_smartkids_to_neo4j.py [--dry-run] [--reset]
"""

import os
import sys
import json
import re
import argparse
import base64
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

# Try to import neo4j
sys.path.insert(0, '/Users/hyoseop1231/.local/lib/python3.13/site-packages')
sys.path.insert(0, '/Users/hyoseop1231/Library/Python/3.13/lib/python/site-packages')

try:
    from neo4j import GraphDatabase
except ImportError:
    print("❌ neo4j 모듈이 필요합니다. 설치: pip3 install neo4j")
    sys.exit(1)


# Configuration
WP_BASE_URL = "http://10.0.0.20/wordpress"
WP_USER = "hyoseop1231"
WP_PASS = "aezu MTX4 WVDQ Rosh 9j3l dEeV"

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "CHANGE_ME_PASSWORD"

# KidsNote Child IDs
CHILD_AYOUNG_ID = "2795010"  # 김아영
CHILD_HYEONSEO_ID = "4879900"  # 김현서
CHILD_NAME_MAPPING = {
    "아영": CHILD_AYOUNG_ID,
    "현서": CHILD_HYEONSEO_ID,
    "김아영": CHILD_AYOUNG_ID,
    "김현서": CHILD_HYEONSEO_ID,
}


class WordPressClient:
    """WordPress REST API Client (using urllib)"""
    
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.api_url = f"{self.base_url}/wp-json/wp/v2"
        # Create basic auth header
        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.auth_header = f"Basic {credentials}"
    
    def _get(self, endpoint: str, params: dict = None) -> List[Dict]:
        """GET request with pagination handling"""
        all_results = []
        page = 1
        per_page = 100
        
        while True:
            req_params = {"per_page": per_page, "page": page}
            if params:
                req_params.update(params)
            
            query_string = urlencode(req_params)
            url = f"{self.api_url}/{endpoint}?{query_string}"
            
            req = Request(url)
            req.add_header("Authorization", self.auth_header)
            req.add_header("Accept", "application/json")
            
            try:
                with urlopen(req, timeout=30) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    if not data:
                        break
                    all_results.extend(data)
                    
                    # Check total pages from header if available
                    total_pages = int(response.headers.get('X-WP-TotalPages', 1))
                    if page >= total_pages:
                        # Try one more page to be sure
                        if len(data) < per_page:
                            break
                    page += 1
            except HTTPError as e:
                if e.code == 400:  # No more pages
                    break
                raise
        
        return all_results
    
    def get_posts(self) -> List[Dict]:
        """모든 포스트 조회"""
        return self._get("posts", {"status": "publish"})
    
    def get_media(self) -> List[Dict]:
        """모든 미디어(첨부파일) 조회"""
        return self._get("media", {"per_page": 100})
    
    def get_categories(self) -> List[Dict]:
        """모든 카테고리 조회"""
        return self._get("categories")


class Neo4jSync:
    """Neo4j 데이터베이스 동기화"""
    
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
    
    def close(self):
        self.driver.close()
    
    def clear_all_smartkids_data(self):
        """기존 SmartKids 데이터 모두 삭제 (리셋용)"""
        with self.driver.session() as session:
            # Delete all smartkids nodes and relationships
            session.run("""
                MATCH (n:Entity)
                WHERE n.type STARTS WITH 'smartkids_' OR n.type = 'wordpress_post'
                DETACH DELETE n
            """)
            print("🗑️  기존 SmartKids/WordPress 데이터 삭제 완료")
    
    def _clean_text(self, text: str) -> str:
        """HTML 태그 제거 및 텍스트 정제"""
        if not text:
            return ""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Normalize whitespace
        text = ' '.join(text.split())
        return text.strip()
    
    def _extract_comic_image(self, content: str) -> Optional[str]:
        """4컷 만화 이미지 URL 추출"""
        if not content:
            return None
        # Find image src in content
        match = re.search(r'src=["\'](https?://[^"\']+\.(?:png|jpg|jpeg|gif))["\']', content, re.IGNORECASE)
        if match:
            return match.group(1)
        return None
    
    def _detect_child_from_content(self, title: str, content: str) -> Optional[str]:
        """포스트 내용에서 아이 이름 감지"""
        text = f"{title} {self._clean_text(content)}"
        
        # Check for child names
        for name, child_id in CHILD_NAME_MAPPING.items():
            if name in text:
                return child_id
        
        return None  # Unknown child
    
    def _is_comic_post(self, title: str, content: str) -> bool:
        """4컷 만화 포스트인지 판별"""
        title_lower = title.lower()
        content_lower = content.lower() if content else ""
        
        # Image in content
        has_image = '<img' in content_lower or self._extract_comic_image(content) is not None
        
        # Title patterns (daily diary format: YYYY-MM-DD ...)
        is_diary_format = re.match(r'\d{4}-\d{2}-\d{2}', title) is not None
        
        return has_image and is_diary_format
    
    def sync_wordpress_post(self, session, post: Dict, categories_map: Dict):
        """WordPress 포스트 노드 생성/업데이트"""
        post_id = post['id']
        title = self._clean_text(post['title']['rendered'])
        content = post['content']['rendered']
        clean_content = self._clean_text(content)
        date = post['date']
        url = post['link']
        
        # Get category name
        category_names = []
        for cat_id in post.get('categories', []):
            if cat_id in categories_map:
                category_names.append(categories_map[cat_id])
        category = ', '.join(category_names) if category_names else '미분류'
        
        # Extract featured image
        featured_image = self._extract_comic_image(content)
        
        # Create wordpress_post node
        session.run("""
            MERGE (wp:Entity {id: $wp_id})
            SET wp:wordpress_post
            SET wp.type = 'wordpress_post',
                wp.wp_post_id = $post_id,
                wp.title = $title,
                wp.content = $content,
                wp.date = $date,
                wp.url = $url,
                wp.featured_image = $featured_image,
                wp.category = $category,
                wp.source = 'smartkids',
                wp.synced_at = datetime(),
                wp.updated_at = datetime(),
                wp.created_at = coalesce(wp.created_at, datetime())
        """, {
            'wp_id': f'wordpress_post:{post_id}',
            'post_id': post_id,
            'title': title,
            'content': clean_content[:5000],  # Limit content length
            'date': date,
            'url': url,
            'featured_image': featured_image or '',
            'category': category
        })
        
        return featured_image
    
    def sync_comic(self, session, post: Dict, wp_node_id: str, categories_map: Dict) -> str:
        """4컷 만화 노드 생성/업데이트"""
        post_id = post['id']
        title = self._clean_text(post['title']['rendered'])
        content = post['content']['rendered']
        clean_content = self._clean_text(content)
        date = post['date']
        url = post['link']
        
        # Get category
        category_names = []
        for cat_id in post.get('categories', []):
            if cat_id in categories_map:
                category_names.append(categories_map[cat_id])
        category = ', '.join(category_names) if category_names else '미분류'
        
        # Extract featured image
        featured_image = self._extract_comic_image(content)
        
        comic_id = f'smartkids_comic:{post_id}'
        
        session.run("""
            MERGE (c:Entity {id: $comic_id})
            SET c:smartkids_comic
            SET c.type = 'smartkids_comic',
                c.wp_post_id = $post_id,
                c.title = $title,
                c.content = $content,
                c.date = $date,
                c.url = $url,
                c.featured_image = $featured_image,
                c.category = $category,
                c.source = 'smartkids',
                c.synced_at = datetime(),
                c.updated_at = datetime(),
                c.created_at = coalesce(c.created_at, datetime())
        """, {
            'comic_id': comic_id,
            'post_id': post_id,
            'title': title,
            'content': clean_content[:5000],
            'date': date,
            'url': url,
            'featured_image': featured_image or '',
            'category': category
        })
        
        # Link to wordpress_post
        session.run("""
            MATCH (c:Entity {id: $comic_id})
            MATCH (wp:Entity {id: $wp_id})
            MERGE (c)-[:PUBLISHED_AS]->(wp)
        """, {'comic_id': comic_id, 'wp_id': wp_node_id})
        
        # Link to child
        child_id = self._detect_child_from_content(title, content)
        if child_id:
            child_node_id = f'kidsnote_child:{child_id}'
            # Ensure child node exists (may already exist from KidsNote sync)
            session.run("""
                MERGE (child:Entity {id: $child_id})
                SET child.type = 'kidsnote_child',
                    child.child_id = $child_raw_id,
                    child.updated_at = datetime(),
                    child.created_at = coalesce(child.created_at, datetime())
            """, {
                'child_id': child_node_id,
                'child_raw_id': child_id
            })
            # Create ABOUT relationship
            session.run("""
                MATCH (child:Entity {id: $child_id})
                MATCH (c:Entity {id: $comic_id})
                MERGE (child)-[:ABOUT]->(c)
            """, {'child_id': child_node_id, 'comic_id': comic_id})
        
        return comic_id
    
    def sync_story(self, session, post: Dict, wp_node_id: str, categories_map: Dict) -> str:
        """일일 스토리 노드 생성/업데이트 (텍스트 중심 포스트)"""
        post_id = post['id']
        title = self._clean_text(post['title']['rendered'])
        content = post['content']['rendered']
        clean_content = self._clean_text(content)
        date = post['date']
        url = post['link']
        
        # Get category
        category_names = []
        for cat_id in post.get('categories', []):
            if cat_id in categories_map:
                category_names.append(categories_map[cat_id])
        category = ', '.join(category_names) if category_names else '미분류'
        
        story_id = f'smartkids_story:{post_id}'
        
        session.run("""
            MERGE (s:Entity {id: $story_id})
            SET s:smartkids_story
            SET s.type = 'smartkids_story',
                s.wp_post_id = $post_id,
                s.title = $title,
                s.content = $content,
                s.date = $date,
                s.url = $url,
                s.category = $category,
                s.source = 'smartkids',
                s.synced_at = datetime(),
                s.updated_at = datetime(),
                s.created_at = coalesce(s.created_at, datetime())
        """, {
            'story_id': story_id,
            'post_id': post_id,
            'title': title,
            'content': clean_content[:5000],
            'date': date,
            'url': url,
            'category': category
        })
        
        # Link to wordpress_post
        session.run("""
            MATCH (s:Entity {id: $story_id})
            MATCH (wp:Entity {id: $wp_id})
            MERGE (s)-[:PUBLISHED_AS]->(wp)
        """, {'story_id': story_id, 'wp_id': wp_node_id})
        
        # Link to child
        child_id = self._detect_child_from_content(title, content)
        if child_id:
            child_node_id = f'kidsnote_child:{child_id}'
            session.run("""
                MERGE (child:Entity {id: $child_id})
                SET child.type = 'kidsnote_child',
                    child.child_id = $child_raw_id,
                    child.updated_at = datetime(),
                    child.created_at = coalesce(child.created_at, datetime())
            """, {
                'child_id': child_node_id,
                'child_raw_id': child_id
            })
            session.run("""
                MATCH (child:Entity {id: $child_id})
                MATCH (s:Entity {id: $story_id})
                MERGE (child)-[:ABOUT]->(s)
            """, {'child_id': child_node_id, 'story_id': story_id})
        
        return story_id
    
    def sync_photo_from_media(self, session, media: Dict) -> Optional[str]:
        """미디어에서 사진 노드 생성"""
        media_id = media['id']
        filename = media.get('title', {}).get('rendered', '')
        url = media.get('source_url', '')
        alt_text = media.get('alt_text', '')
        date = media.get('date', '')
        
        # Skip non-images
        if media.get('media_type') != 'image':
            return None
        
        photo_id = f'smartkids_photo:{media_id}'
        
        session.run("""
            MERGE (p:Entity {id: $photo_id})
            SET p:smartkids_photo
            SET p.type = 'smartkids_photo',
                p.image_id = $image_id,
                p.filename = $filename,
                p.url = $url,
                p.alt_text = $alt_text,
                p.date = $date,
                p.source = 'smartkids',
                p.synced_at = datetime(),
                p.updated_at = datetime(),
                p.created_at = coalesce(p.created_at, datetime())
        """, {
            'photo_id': photo_id,
            'image_id': media_id,
            'filename': filename,
            'url': url,
            'alt_text': alt_text,
            'date': date
        })
        
        return photo_id
    
    def link_photo_to_comic(self, session, photo_id: str, comic_id: str):
        """사진을 만화와 연결"""
        session.run("""
            MATCH (c:Entity {id: $comic_id})
            MATCH (p:Entity {id: $photo_id})
            MERGE (c)-[:HAS_PHOTO]->(p)
        """, {'comic_id': comic_id, 'photo_id': photo_id})
    
    def get_stats(self) -> Dict[str, int]:
        """동기화 통계 조회"""
        with self.driver.session() as session:
            # Count nodes by type
            result = session.run("""
                MATCH (n:Entity)
                WHERE n.type STARTS WITH 'smartkids_' OR n.type = 'wordpress_post' OR n.type = 'kidsnote_child'
                RETURN n.type as type, count(n) as count
            """)
            node_counts = {record['type']: record['count'] for record in result}
            
            # Count relationships
            result = session.run("""
                MATCH ()-[r:ABOUT|HAS_PHOTO|CONTAINS|PUBLISHED_AS]->()
                RETURN count(r) as rel_count
            """)
            rel_count = result.single()['rel_count']
            
            return {
                'nodes': node_counts,
                'relationships': rel_count
            }


def main():
    parser = argparse.ArgumentParser(description='SmartKids WordPress → Neo4j Sync')
    parser.add_argument('--dry-run', action='store_true', help='실제 동기화 없이 데이터만 조회')
    parser.add_argument('--reset', action='store_true', help='기존 데이터 삭제 후 재동기화')
    args = parser.parse_args()
    
    print("🚀 SmartKids WordPress → Neo4j 동기화 시작")
    print("=" * 50)
    
    # Initialize clients
    wp = WordPressClient(WP_BASE_URL, WP_USER, WP_PASS)
    neo4j = Neo4jSync(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    
    try:
        # Test connections
        print("📡 WordPress 연결 테스트...")
        posts = wp.get_posts()
        print(f"   ✓ 포스트 {len(posts)}개 조회됨")
        
        media = wp.get_media()
        print(f"   ✓ 미디어 {len(media)}개 조회됨")
        
        categories = wp.get_categories()
        categories_map = {cat['id']: cat['name'] for cat in categories}
        print(f"   ✓ 카테고리 {len(categories)}개 조회됨")
        
        if args.dry_run:
            print("\n🔍 DRY RUN 모드 - 데이터 조회만 수행")
            print(f"\n포스트 목록:")
            for post in posts[:10]:
                title = post['title']['rendered']
                is_comic = '<img' in post['content']['rendered'].lower()
                type_str = "📚 만화" if is_comic else "📝 스토리"
                print(f"   {type_str} | {title}")
            if len(posts) > 10:
                print(f"   ... 외 {len(posts) - 10}개")
            return
        
        # Reset if requested
        if args.reset:
            print("\n🗑️  기존 데이터 삭제 중...")
            neo4j.clear_all_smartkids_data()
        
        # Sync data
        print("\n📥 Neo4j 동기화 중...")
        
        comic_count = 0
        story_count = 0
        wp_count = 0
        photo_count = 0
        
        with neo4j.driver.session() as session:
            # Create indexes for performance
            session.run("""
                CREATE INDEX smartkids_comic_id IF NOT EXISTS
                FOR (n:smartkids_comic) ON (n.id)
            """)
            session.run("""
                CREATE INDEX smartkids_photo_id IF NOT EXISTS
                FOR (n:smartkids_photo) ON (n.id)
            """)
            
            # First, sync all WordPress posts and classify them
            for post in posts:
                title = post['title']['rendered']
                content = post['content']['rendered']
                
                # Create wordpress_post node
                featured_image = neo4j.sync_wordpress_post(session, post, categories_map)
                wp_node_id = f'wordpress_post:{post["id"]}'
                wp_count += 1
                
                # Classify as comic or story
                if neo4j._is_comic_post(title, content):
                    neo4j.sync_comic(session, post, wp_node_id, categories_map)
                    comic_count += 1
                    print(f"   📚 만화 동기화: {title[:40]}...")
                else:
                    neo4j.sync_story(session, post, wp_node_id, categories_map)
                    story_count += 1
                    print(f"   📝 스토리 동기화: {title[:40]}...")
            
            # Sync media/photos
            post_media_map = {}  # post_id -> list of media_ids
            for m in media:
                photo_id = neo4j.sync_photo_from_media(session, m)
                if photo_id:
                    photo_count += 1
                    # Link to parent post if exists
                    parent_post = m.get('post')
                    if parent_post:
                        if parent_post not in post_media_map:
                            post_media_map[parent_post] = []
                        post_media_map[parent_post].append(photo_id)
            
            # Link photos to comics
            for post_id, photo_ids in post_media_map.items():
                comic_id = f'smartkids_comic:{post_id}'
                for photo_id in photo_ids:
                    neo4j.link_photo_to_comic(session, photo_id, comic_id)
            
            if photo_count > 0:
                print(f"\n   📸 사진 {photo_count}개 동기화 및 연결 완료")
        
        # Print stats
        print("\n" + "=" * 50)
        print("✅ 동기화 완료!")
        print("-" * 50)
        
        stats = neo4j.get_stats()
        print("\n📊 Neo4j 데이터 현황:")
        print(f"   노드:")
        for node_type, count in sorted(stats['nodes'].items()):
            print(f"      • {node_type}: {count}개")
        print(f"   관계: {stats['relationships']}개")
        
        print(f"\n📈 이번 실행 동기화:")
        print(f"   • WordPress 포스트: {wp_count}개")
        print(f"   • 4컷 만화: {comic_count}개")
        print(f"   • 일일 스토리: {story_count}개")
        print(f"   • 사진: {photo_count}개")
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        neo4j.close()


if __name__ == "__main__":
    main()
