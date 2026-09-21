from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
CHROMA_PATH = PROJECT_ROOT / "chroma_db"

DB_PATH = DATA_DIR / "pokemon.db"
SPREADSHEET_PATH = DATA_DIR / "pokedex_particularites.xlsx"

POKEAPI_DIR = DATA_DIR / "pokeapi"
POKEAPI_RAW_DIR = POKEAPI_DIR / "raw"
POKEAPI_DB_PATH = POKEAPI_DIR / "pokeapi.db"

POKEPEDIA_DIR = DATA_DIR / "pokepedia"
POKEPEDIA_RAW_DIR = POKEPEDIA_DIR / "raw"
POKEPEDIA_CLEANED_DIR = POKEPEDIA_DIR / "cleaned"