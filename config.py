"""Project settings. Values can be overridden with environment variables or a .env file."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
PROMPTS_DIR = BASE_DIR / "prompts"
TEMPLATES_DIR = BASE_DIR / "templates"

# Star-schema database the BRD is mapped onto.
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "ecommerce.db"))

# KPI catalog, chart rules and dashboard defaults.
DASHBOARD_CONFIG_PATH = TEMPLATES_DIR / "dashboard_config.json"

# LLM. The key can also be entered in the app sidebar (kept in memory only).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))

# BRD text beyond this many characters is cut before it is sent to the LLM.
MAX_BRD_CHARS = int(os.getenv("MAX_BRD_CHARS", "60000"))

# Rows returned per preview query.
PREVIEW_ROW_LIMIT = int(os.getenv("PREVIEW_ROW_LIMIT", "500"))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
