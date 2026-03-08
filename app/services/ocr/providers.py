from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from flask import current_app

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None

logger = logging.getLogger(__name__)


class OCRResult(Dict[str, object]):
    pass


class OCRProvider(ABC):
    key = "base"

    def __init__(self, config: Dict | None = None):
        self.config = config or {}

    @abstractmethod
    def extract(self, image_path: str) -> OCRResult:
        raise NotImplementedError()


class TesseractProvider(OCRProvider):
    key = "tesseract"

    def extract(self, image_path: str) -> OCRResult:
        if not pytesseract or not Image:
            return {"ok": False, "error": "tesseract not installed"}
        if not os.path.exists(image_path):
            return {"ok": False, "error": "file_missing"}
        try:
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img)
            return {"ok": True, "provider": self.key, "text": text.strip()}
        except Exception as exc:
            logger.debug("tesseract extraction failed", exc_info=exc)
            return {"ok": False, "error": str(exc)}


class GoogleVisionProvider(OCRProvider):
    key = "google_vision"

    def extract(self, image_path: str) -> OCRResult:
        # placeholder for real integration
        project = self.config.get("project_id")
        credentials = self.config.get("credentials")
        if not project or not credentials:
            return {"ok": False, "error": "google_vision_missing_configuration"}
        logger.debug("google vision provider invoked for %s", image_path)
        return {"ok": False, "error": "google vision not implemented"}


class AWSTextractProvider(OCRProvider):
    key = "aws_textract"

    def extract(self, image_path: str) -> OCRResult:
        region = self.config.get("region")
        access_key = self.config.get("access_key")
        secret = self.config.get("secret_key")
        if not region or not access_key or not secret:
            return {"ok": False, "error": "aws_textract_missing_configuration"}
        logger.debug("aws textract provider invoked for %s", image_path)
        return {"ok": False, "error": "aws textract not implemented"}


class OCRManager:
    def __init__(self):
        self.providers = self._load_providers()

    def _load_providers(self) -> List[OCRProvider]:
        order = current_app.config.get("OCR_PROVIDER_ORDER") or []
        providers: List[OCRProvider] = []
        mapping = {
            TesseractProvider.key: TesseractProvider,
            GoogleVisionProvider.key: GoogleVisionProvider,
            AWSTextractProvider.key: AWSTextractProvider,
        }
        for key in order:
            key = (key or "").strip()
            provider_cls = mapping.get(key)
            if not provider_cls:
                continue
            config = current_app.config.get(f"OCR_{key.upper()}_CONFIG") or {}
            providers.append(provider_cls(config))
        if not providers:
            providers.append(TesseractProvider({}))
        return providers

    def extract_text(self, image_path: str) -> OCRResult:
        for provider in self.providers:
            result = provider.extract(image_path)
            if result.get("ok"):
                return result
        return {"ok": False, "error": "no_provider_succeeded"}


def extract_text_from_image(image_path: str) -> OCRResult:
    manager = OCRManager()
    return manager.extract_text(image_path)
