"""Nhan dien nguoi dung kiosk (camera truoc kiosk) — dong goi de ghep vao app khac.

- `HumanDetector`: dung truc tiep trong Python (cung moi truong voi package nay).
- `human_detection.server`: server HTTP de app o moi truong/ngon ngu khac goi vao.
- `human_detection.client`: client HTTP chi dung thu vien chuan, chep di dung duoc.
"""
from kiosk_vision.config import AppConfig, load_config

from .engine import DEFAULT_CONFIG, PROJECT_ROOT, HumanDetector

__version__ = "0.1.0"
__all__ = ["DEFAULT_CONFIG", "PROJECT_ROOT", "AppConfig", "HumanDetector", "load_config"]
