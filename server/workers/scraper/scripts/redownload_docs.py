#!/usr/bin/env python3
"""Re-download documents that are missing local files."""

import asyncio
import asyncpg
import hashlib
import httpx
import os
import re
from pathlib import Path


def sanitize_source_name(source_name: str) -> str:
    """Convert source name to filesystem-safe directory name."""
    safe_name = re.sub(r'[^\w\s-]', '', source_name).strip()
    safe_name = re.sub(r'[-\s]+', '-', safe_name).lower()
    return safe_name


def generate_filename(url: str, title: str) -> str:
    """Generate a unique filename from URL and title."""
    # Create hash from URL for uniqueness
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    
    # Sanitize title
    safe_title = re.sub(r'[^\w\s-]', '', title).strip()
    safe_title = re.sub(r'[-\s]+', '-', safe_title)[:50]
    
    return f"{safe_title}_{url_hash}.pdf"


async def download_missing():
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    
    # Use the same storage directory as the main downloader
    storage_dir = Path(os.environ.get('DOCUMENT_STORAGE_DIR', '/data/documents'))
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    async with pool.acquire() as conn:
        docs = await conn.fetch('''
            SELECT d.id, d.title, d.source_url, s.name as source_name
            FROM documents d 
            JOIN sources s ON d.source_id = s.id
            WHERE d.local_path IS NULL AND d.source_url IS NOT NULL
        ''')
        
        print(f'Attempting to download {len(docs)} documents...')
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            for doc in docs:
                doc_id, title, url, source_name = doc
                print(f'\nProcessing: {title}')
                print(f'  URL: {url}')
                
                # Skip non-document URLs
                if url.endswith('DocumentCenter') or 'AgendaCenter/PreviousVersions' in url:
                    print(f'  SKIP: Not a downloadable document URL')
                    continue
                
                try:
                    # Get the file
                    response = await client.get(url)
                    print(f'  GET status: {response.status_code}')
                    
                    if response.status_code == 200:
                        content_type = response.headers.get('content-type', '')
                        print(f'  Content-Type: {content_type}')
                        
                        # Organize by source like the main downloader
                        source_dir_name = sanitize_source_name(source_name)
                        source_dir = storage_dir / source_dir_name
                        source_dir.mkdir(parents=True, exist_ok=True)
                        
                        # Generate filename
                        filename = generate_filename(url, title)
                        filepath = source_dir / filename
                        
                        filepath.write_bytes(response.content)
                        print(f'  SAVED: {filepath} ({len(response.content)} bytes)')
                        
                        # Store relative path (from storage_dir)
                        relative_path = f"{source_dir_name}/{filename}"
                        
                        # Update database with relative path
                        await conn.execute(
                            'UPDATE documents SET local_path = $1 WHERE id = $2',
                            relative_path, doc_id
                        )
                        print(f'  DB updated with path: {relative_path}')
                    else:
                        print(f'  FAILED: Status {response.status_code}')
                        
                except Exception as e:
                    print(f'  ERROR: {e}')
    
    await pool.close()
    print('\nDone!')


if __name__ == '__main__':
    asyncio.run(download_missing())

