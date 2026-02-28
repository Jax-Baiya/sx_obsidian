"""
Scheduler & Background Worker for SX Obsidian

Handles parsing Markdown notes, uploading media to Cloudflare R2,
and managing the job queue for publishing.
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .settings import Settings
from .repositories import get_repository

logger = logging.getLogger(__name__)

class Scheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.repo = get_repository(settings)
        
        # Configure R2 client
        self.s3_client = None
        if settings.SX_R2_ACCOUNT_ID and settings.SX_R2_ACCESS_KEY_ID and settings.SX_R2_SECRET_ACCESS_KEY:
            self.s3_client = boto3.client(
                "s3",
                endpoint_url=f"https://{settings.SX_R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
                aws_access_key_id=settings.SX_R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.SX_R2_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4"),
                region_name="auto"
            )

    def _get_note_path(self, source_id: str, video_id: str) -> Path | None:
        """Find the markdown note for a given video."""
        # For MVP, assume notes are in the active vault directory
        # The true resolution would use sx config or path logic
        vault_path = Path(self.settings.SX_VAULT_PATH or ".")
        possible_note = vault_path / "Videos" / f"{video_id}.md"
        if possible_note.exists():
            return possible_note
            
        # Try finding anywhere in vault
        for md_file in vault_path.rglob("*.md"):
            if md_file.stem == video_id:
                return md_file
        return None

    def _extract_media_paths(self, markdown_text: str) -> list[str]:
        """Extract media references from markdown (e.g., [[media.mp4]] or ![cover](/path/to/media.mp4))."""
        # Very simplified extraction for prototype
        paths = []
        import re
        # Match [[filename.mp4]]
        matches = re.findall(r"\[\[(.*?\.mp4)\]\]", markdown_text, re.IGNORECASE)
        paths.extend(matches)
        
        # Match ![alt](path.mp4)
        matches2 = re.findall(r"\!\[.*?\]\((.*?\.mp4)\)", markdown_text, re.IGNORECASE)
        paths.extend(matches2)
        return list(set(paths))

    def _upload_to_r2(self, local_path: Path, object_name: str) -> str | None:
        """Upload a file to R2 and return its URL."""
        if not self.s3_client or not self.settings.SX_R2_BUCKET_NAME:
            logger.warning("R2 client not configured. Skipping upload.")
            return None
            
        try:
            content_type = "video/mp4" if local_path.suffix.lower() == ".mp4" else "image/jpeg"
            self.s3_client.upload_file(
                str(local_path), 
                self.settings.SX_R2_BUCKET_NAME, 
                object_name,
                ExtraArgs={"ContentType": content_type}
            )
            
            # Construct public URL assuming custom domain or standard R2 bucket URL
            public_domain = getattr(self.settings, "SX_R2_PUBLIC_DOMAIN", None)
            if public_domain:
                return f"https://{public_domain}/{object_name}"
            return f"https://{self.settings.SX_R2_BUCKET_NAME}.r2.cloudflarestorage.com/{object_name}"
        except ClientError as e:
            logger.error(f"Failed to upload to R2: {e}")
            return None

    def enqueue_scheduling_job(self, source_id: str, video_id: str) -> dict[str, Any]:
        """
        Process a note conceptually transitioning to 'status: scheduling'.
        Generates artifact, uploads to R2, and queues a job.
        """
        note_path = self._get_note_path(source_id, video_id)
        if not note_path:
            return {"ok": False, "error": f"Note not found for {video_id}"}
            
        content = note_path.read_text(encoding="utf-8")
        
        # 1. Parse Frontmatter (simplified)
        import yaml
        frontmatter = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    pass
                    
        # 2. Upload Media to R2
        r2_url = None
        media_paths = self._extract_media_paths(content)
        # For simplicity in MVP, take the first valid media path
        vault_path = Path(self.settings.SX_VAULT_PATH or ".")
        for m_path in media_paths:
            # Try to resolve relative to note or vault
            full_path = note_path.parent / m_path
            if not full_path.exists():
                full_path = vault_path / m_path
                if not full_path.exists():
                    continue
            
            r2_url = self._upload_to_r2(full_path, f"{source_id}/{video_id}/{full_path.name}")
            if r2_url:
                # Update frontmatter in file (writeback)
                frontmatter["r2_media_url"] = r2_url
                # Simplified writeback logic:
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    new_fm = yaml.dump(frontmatter, sort_keys=False)
                    new_content = f"---\n{new_fm}---\n{parts[2].strip()}"
                    note_path.write_text(new_content, encoding="utf-8")
                break
                
        # 3. Create Artifact
        platform = frontmatter.get("platform", "tiktok")
        publish_time = frontmatter.get("publish_time")
        artifact = {
            "video_id": video_id,
            "title": frontmatter.get("title", ""),
            "caption": frontmatter.get("caption", ""),
            "tags": frontmatter.get("tags", []),
            "r2_media_url": r2_url,
            "platform": platform,
            "scheduled_time": publish_time
        }
        
        now = datetime.utcnow().isoformat() + "Z"
        
        # 4. Save to DB (SQLite / Supabase Mirror)
        conn = self.repo.connection_for_source(source_id) if hasattr(self.repo, "connection_for_source") else connect(self.settings.SX_DB_PATH)
        job_id = f"job_{video_id}_{int(time.time())}"
        
        try:
            # Insert Artifact
            conn.execute(
                """
                INSERT INTO scheduling_artifacts 
                (source_id, video_id, platform, artifact_json, r2_media_url, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'draft_review', ?, ?)
                ON CONFLICT(source_id, video_id, platform) DO UPDATE SET
                    artifact_json=excluded.artifact_json,
                    r2_media_url=excluded.r2_media_url,
                    updated_at=excluded.updated_at
                """,
                (source_id, video_id, platform, json.dumps(artifact), r2_url, now, now)
            )
            
            # Queue Job
            action = "publish_scheduled" if publish_time else "publish_draft"
            conn.execute(
                """
                INSERT INTO job_queue
                (id, source_id, video_id, platform, action, status, scheduled_time, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (job_id, source_id, video_id, platform, action, publish_time, now, now)
            )
            conn.commit()
            
        finally:
            if hasattr(conn, "close"):
                conn.close()
                
        return {"ok": True, "job_id": job_id, "artifact": artifact}

    def start_worker(self, poll_interval: int = 60):
        """Start a background worker to poll for pending jobs."""
        def _poll():
            logger.info("Starting SchedulerX background worker...")
            while True:
                try:
                    self._process_pending_jobs()
                except Exception as e:
                    logger.error(f"Worker polling error: {e}")
                time.sleep(poll_interval)
                
        thread = threading.Thread(target=_poll, daemon=True)
        thread.start()
        return thread
        
    def _process_pending_jobs(self):
        """Check the job queue for jobs that are ready to execute."""
        # MVP: Only supports SQLite local or single profile loop for now
        # Fetch pending jobs that have execution time in past or none
        # Update status to processing -> publish -> update to completed
        pass
