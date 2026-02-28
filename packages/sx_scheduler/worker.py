import time
import os
from typing import Any
from sx_scheduler.db import acquire_job, mark_job_failed, mark_job_published
from sx_scheduler.pinterest import PinterestPublisher
from sx_scheduler.r2_stager import R2Stager
from datetime import datetime

class PublisherWorker:
    def __init__(self, conn: Any, source_id: str):
        self.conn = conn
        self.source_id = source_id
        self.pinterest = PinterestPublisher()
        self.stager = R2Stager()
        self.worker_name = f"worker-{os.getpid()}"
        
    def run_once(self) -> dict | None:
        # Acquire job
        job = acquire_job(self.conn, self.source_id, lock_ttl_minutes=15, worker_name=self.worker_name)
        if not job:
            return None
            
        print(f"[{self.source_id}] Worker {self.worker_name} acquired job {job['id']} for note {job['note_id']}")
        self.conn.commit() # commit the lock so other workers don't grab it
        
        try:
            self._process_job(job)
            self.conn.commit()
            return job
        except Exception as e:
            # Revert or commit fail status
            self.conn.rollback() # rollback whatever we did in _process_job that failed
            mark_job_failed(self.conn, job["id"], str(e))
            self.conn.commit()
            print(f"[{self.source_id}] Job {job['id']} failed: {e}")
            return job

    def _process_job(self, job: dict):
        job_id = str(job["id"])
        note_id = str(job["note_id"])
        
        # 1. Fetch metadata from user_meta and note_path
        # Real impl would parse Note YAML. We will fetch from user_meta table for ease.
        meta_row = self.conn.execute("SELECT * FROM user_meta WHERE source_id=? AND video_id=?", (self.source_id, note_id)).fetchone()
        video_row = self.conn.execute("SELECT video_path, caption FROM videos WHERE source_id=? AND id=?", (self.source_id, note_id)).fetchone()
        
        if not meta_row or not video_row:
            raise RuntimeError(f"Metadata or video missing for {note_id}")
            
        video_path = video_row["video_path"]
        if not video_path:
            raise RuntimeError(f"Video path is empty for note {note_id}")
            
        # Optional custom board/title from YAML could be saved in `notes` or `user_meta`
        board_id = "default-board-id" # Need board ID logic, assume default
        title = meta_row["tags"] or "Pinterest Pin"
        desc = video_row["caption"] or "Awesome video"
        
        # 2. Stage media
        staged_url = self.stager.stage_media(video_path, self.source_id)
        
        # 3. Publish to Pinterest
        result = self.pinterest.publish_pin(
            board_id=board_id,
            title=title,
            description=desc,
            media_url=staged_url
        )
        
        # 4. Mark published in jobs table
        mark_job_published(self.conn, job_id, result["pin_id"], result["url"])
        
        # 5. Write-back to note metadata table (which Obsidian plugin syncs)
        now_str = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        log_entry = f"[{now_str}] Published to Pinterest via worker {self.worker_name}"
        
        # Append to workflow log
        current_log = meta_row["workflow_log"] or ""
        new_log = f"{current_log}\n{log_entry}".strip()
        
        self.conn.execute(
            """
            UPDATE user_meta 
            SET statuses = 'published', post_url = ?, published_time = ?, workflow_log = ?, updated_at = ?
            WHERE source_id = ? AND video_id = ?
            """,
            (result["url"], now_str, new_log, now_str, self.source_id, note_id)
        )

    def loop(self, poll_interval_seconds: int = 15):
        print(f"Starting worker loop for {self.source_id}. Polling every {poll_interval_seconds}s...")
        try:
            while True:
                job = self.run_once()
                if not job:
                    time.append(poll_interval_seconds)
        except KeyboardInterrupt:
            print("Worker shutting down.")
