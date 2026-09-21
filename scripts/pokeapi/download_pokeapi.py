from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path

from tqdm import tqdm


from pokemon_rag.config import POKEAPI_RAW_DIR

RAW_DIR = POKEAPI_RAW_DIR
BASE_URL = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv"

# Premier lot : gameplay structuré absent du tableur.
CSV_FILES = [
    "languages.csv",
    "pokemon.csv",
    "pokemon_species.csv",
    "pokemon_species_names.csv",
    "pokemon_forms.csv",
    "pokemon_form_names.csv",
    "moves.csv",
    "move_names.csv",
    "pokemon_move_methods.csv",
    "version_groups.csv",
    "versions.csv",
    "pokemon_moves.csv",
    "evolution_triggers.csv",
    "pokemon_evolution.csv",
    "items.csv",
    "item_names.csv",
    "machines.csv",
    "genders.csv",
    "locations.csv",
    "location_names.csv",
    "types.csv",
    "type_names.csv",
    "regions.csv",
    "region_names.csv",
]

TIMEOUT_SECONDS = 60
CHUNK_BYTES = 1024 * 1024


def download_file(filename: str) -> tuple[bool, int]:
    """Télécharge un CSV officiel PokéAPI. Un fichier déjà présent est conservé."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    destination = RAW_DIR / filename

    if destination.exists() and destination.stat().st_size > 0:
        return False, destination.stat().st_size

    url = f"{BASE_URL}/{filename}"
    temporary = destination.with_suffix(destination.suffix + ".part")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "pokemon-local-rag/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            total = int(response.headers.get("Content-Length", 0))
            with temporary.open("wb") as handle, tqdm(
                total=total if total > 0 else None,
                unit="B",
                unit_scale=True,
                desc=filename,
                dynamic_ncols=True,
                leave=False,
            ) as progress:
                while True:
                    block = response.read(CHUNK_BYTES)
                    if not block:
                        break
                    handle.write(block)
                    progress.update(len(block))

        temporary.replace(destination)
        return True, destination.stat().st_size

    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def main() -> None:
    start = time.perf_counter()

    print("=" * 88)
    print("TÉLÉCHARGEMENT DES DONNÉES OFFICIELLES POKÉAPI")
    print("=" * 88)
    print(f"Destination : {RAW_DIR}")
    print(f"Fichiers    : {len(CSV_FILES)}")
    print()

    downloaded = 0
    cached = 0
    total_bytes = 0
    failures: list[str] = []

    progress = tqdm(CSV_FILES, desc="CSV PokéAPI", unit="fichier", dynamic_ncols=True)

    for filename in progress:
        progress.set_postfix(file=filename[:28])
        try:
            was_downloaded, size = download_file(filename)
            total_bytes += size
            if was_downloaded:
                downloaded += 1
                tqdm.write(f"[OK] {filename} téléchargé ({size / 1024:.1f} KiB)")
            else:
                cached += 1
                tqdm.write(f"[CACHE] {filename} déjà présent")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failures.append(filename)
            tqdm.write(f"[ERREUR] {filename}: {exc}")

    elapsed = time.perf_counter() - start

    print()
    print("=" * 88)
    print("RAPPORT")
    print("=" * 88)
    print(f"Téléchargés : {downloaded}")
    print(f"Déjà en cache: {cached}")
    print(f"Volume local : {total_bytes / (1024 * 1024):.2f} MiB")
    print(f"Temps total  : {elapsed:.2f} s")

    if failures:
        raise RuntimeError(
            "Téléchargement incomplet. Fichiers en échec : " + ", ".join(failures)
        )

    print("✓ Tous les CSV nécessaires sont disponibles.")


if __name__ == "__main__":
    main()
