from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"

DB_PATH = DATA_DIR / "pokemon.db"
CHROMA_PATH = PROJECT_ROOT / "chroma_db"