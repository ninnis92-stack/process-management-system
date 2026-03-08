from __future__ import annotations

import os
import logging

from flask import current_app
from redis import Redis
from rq import Queue

from app import create_app
from app.extensions import db
from app.models import Attachment
from .providers import extract_text_from_image

logger = logging.getLogger(__name__)

OCR_QUEUE = "ocr"


def enqueue_attachment_ocr(attachment_id: int) -> None:
    redis_url = current_app.config.get("REDIS_URL")
    if not redis_url:
        logger.warning("Skipping OCR queue since REDIS_URL is not configured")
        return
    conn = Redis.from_url(redis_url)
    queue = Queue(OCR_QUEUE, connection=conn)
    queue.enqueue("app.services.ocr.tasks.process_attachment_ocr", attachment_id)


def process_attachment_ocr(attachment_id: int) -> None:
    app = create_app()
    with app.app_context():
        attachment = Attachment.query.get(attachment_id)
        if not attachment:
            logger.warning("OCR job could not find attachment %s", attachment_id)
            return
        storage_path = os.path.join(
            app.static_folder or "static", attachment.stored_filename
        )
        if not os.path.exists(storage_path):
            logger.warning("OCR job missing file for attachment %s", attachment_id)
            return
        result = extract_text_from_image(storage_path)
        if result.get("ok") and result.get("text"):
            attachment.ocr_text = result.get("text")
            db.session.commit()
            logger.info(
                "OCR extracted text for attachment %s via %s",
                attachment_id,
                result.get("provider"),
            )
        else:
            logger.info(
                "OCR failed for attachment %s (%s)",
                attachment_id,
                result.get("error"),
            )