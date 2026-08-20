"""Central config, loaded from .env. Every stage imports this, nothing else."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

    db_path: str = os.getenv("CALLRADAR_DB_PATH", "callradar.db")
    audio_dir: str = os.getenv("CALLRADAR_AUDIO_DIR", "data/audio")
    metadata_dir: str = os.getenv("CALLRADAR_METADATA_DIR", "data/metadata")
    work_dir: str = os.getenv("CALLRADAR_WORK_DIR", ".callradar_work")

    asr_model: str = os.getenv("CALLRADAR_ASR_MODEL", "base.en")
    asr_compute_type: str = os.getenv("CALLRADAR_ASR_COMPUTE_TYPE", "int8")
    asr_workers: int = int(os.getenv("CALLRADAR_ASR_WORKERS", "3"))

    dead_air_min_gap_s: float = float(os.getenv("CALLRADAR_DEAD_AIR_MIN_GAP_S", "2.0"))
    dead_air_rms_threshold: float = float(os.getenv("CALLRADAR_DEAD_AIR_RMS_THRESHOLD", "0.03"))

    quote_match_threshold: int = int(os.getenv("CALLRADAR_QUOTE_MATCH_THRESHOLD", "90"))
    timestamp_tolerance_s: float = float(os.getenv("CALLRADAR_TIMESTAMP_TOLERANCE_S", "0.5"))
    max_retries: int = int(os.getenv("CALLRADAR_MAX_RETRIES", "2"))

    as_of_date: str = os.getenv("CALLRADAR_AS_OF_DATE", "")  # blank -> corpus max


CONFIG = Config()
