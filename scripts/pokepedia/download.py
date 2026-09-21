from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

import requests


API_URL = "https://www.pokepedia.fr/api.php"
from pokemon_rag.config import POKEPEDIA_RAW_DIR

OUTPUT_DIR = POKEPEDIA_RAW_DIR

REQUEST_DELAY = 1.0
TIMEOUT = 30
USER_AGENT = (
    "SecureLLMGateway-RAG-Benchmark/0.3 "
    "(educational local RAG experiment)"
)

# Numéros nationaux actuellement attendus.
# Le script découvre les noms depuis les catégories Poképédia, puis récupère
# le numéro national dans l'infobox de chaque page.
MIN_NATIONAL_NUMBER = 1
MAX_NATIONAL_NUMBER = 1025

CATEGORY_CANDIDATES = [
    "Catégorie:Pokémon",
    "Catégorie:Pokémon par espèce",
]

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("♀", "_f").replace("♂", "_m")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "pokemon"


def api_get(params: dict) -> tuple[dict, float]:
    start = time.perf_counter()
    response = session.get(API_URL, params=params, timeout=TIMEOUT)
    elapsed = time.perf_counter() - start
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        raise RuntimeError(f"Erreur API MediaWiki : {data['error']}")

    return data, elapsed


def discover_category_members(category: str) -> tuple[list[str], float]:
    titles = []
    cmcontinue = None
    total_http = 0.0

    while True:
        params = {
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "list": "categorymembers",
            "cmtitle": category,
            "cmnamespace": 0,
            "cmlimit": "max",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        data, http_time = api_get(params)
        total_http += http_time

        titles.extend(
            item["title"]
            for item in data.get("query", {}).get("categorymembers", [])
        )

        continuation = data.get("continue", {})
        cmcontinue = continuation.get("cmcontinue")
        if not cmcontinue:
            break

        time.sleep(REQUEST_DELAY)

    # Stable + deduplicated
    return list(dict.fromkeys(titles)), total_http


def discover_candidate_titles() -> tuple[list[str], str, float]:
    errors = []

    for category in CATEGORY_CANDIDATES:
        try:
            titles, http_time = discover_category_members(category)
            if titles:
                return titles, category, http_time
        except Exception as exc:
            errors.append(f"{category}: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "Impossible de découvrir les pages Pokémon via les catégories testées.\n"
        + "\n".join(errors)
    )


def extract_national_number(wikitext: str) -> int | None:
    # Poképédia peut écrire numero, numéro, ndex, etc. On privilégie les
    # paramètres d'infobox et on reste volontairement conservateur.
    patterns = [
        r"(?im)^\s*\|\s*num[eé]ro\s*=\s*0*(\d{1,4})\s*$",
        r"(?im)^\s*\|\s*num[eé]ro\s+n(?:ational)?\s*=\s*0*(\d{1,4})\s*$",
        r"(?im)^\s*\|\s*ndex\s*=\s*0*(\d{1,4})\s*$",
        r"(?im)^\s*\|\s*n[°º]\s*national\s*=\s*0*(\d{1,4})\s*$",
    ]

    for pattern in patterns:
        match = re.search(pattern, wikitext)
        if match:
            number = int(match.group(1))
            if MIN_NATIONAL_NUMBER <= number <= MAX_NATIONAL_NUMBER:
                return number

    return None


def fetch_page(title: str) -> tuple[dict, float]:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "prop": "revisions",
        "rvprop": "ids|timestamp|content",
        "rvslots": "main",
        "titles": title,
    }

    data, http_time = api_get(params)
    pages = data.get("query", {}).get("pages", [])

    if not pages:
        raise RuntimeError("Aucune page retournée.")

    page = pages[0]
    if page.get("missing"):
        raise RuntimeError("Page inexistante.")

    revisions = page.get("revisions", [])
    if not revisions:
        raise RuntimeError("Aucune révision disponible.")

    revision = revisions[0]
    content = revision.get("slots", {}).get("main", {}).get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Contenu wikitexte vide.")

    canonical_title = page.get("title", title)
    national_number = extract_national_number(content)

    article = {
        "title": canonical_title,
        "national_number": national_number,
        "page_id": page.get("pageid"),
        "revision_id": revision.get("revid"),
        "revision_timestamp": revision.get("timestamp"),
        "source": "Poképédia",
        "source_url": f"https://www.pokepedia.fr/{quote(canonical_title.replace(' ', '_'))}",
        "content": content,
    }

    return article, http_time


def existing_valid_file(path: Path, expected_number: int | None = None) -> dict | None:
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        required = ("title", "revision_id", "content")
        if not all(data.get(key) for key in required):
            return None
        if expected_number is not None and data.get("national_number") not in (None, expected_number):
            return None
        return data
    except Exception:
        return None


def atomic_save(article: dict, output_file: Path) -> None:
    tmp = output_file.with_suffix(output_file.suffix + ".tmp")
    tmp.write_text(
        json.dumps(article, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(output_file)


def build_existing_index() -> dict[str, Path]:
    index = {}
    for path in OUTPUT_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            title = str(data.get("title", "")).casefold()
            if title and data.get("content"):
                index[title] = path
        except Exception:
            pass
    return index


def main() -> None:
    global_start = time.perf_counter()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 84)
    print("TÉLÉCHARGEMENT POKÉPÉDIA — CORPUS COMPLET")
    print("=" * 84)
    print(f"Dossier        : {OUTPUT_DIR}")
    print(f"Pause requêtes : {REQUEST_DELAY:.1f} s")
    print(f"Plage nationale: {MIN_NATIONAL_NUMBER}–{MAX_NATIONAL_NUMBER}")
    print()

    discovery_start = time.perf_counter()
    titles, category, discovery_http = discover_candidate_titles()
    discovery_total = time.perf_counter() - discovery_start

    print(f"Catégorie utilisée : {category}")
    print(f"Pages candidates   : {len(titles)}")
    print(f"Découverte HTTP    : {discovery_http:.3f} s")
    print(f"Découverte totale  : {discovery_total:.3f} s")
    print()

    existing_index = build_existing_index()

    downloaded = 0
    skipped = 0
    ignored = 0
    errors = []
    http_times = []
    found_numbers = {}

    for i, title in enumerate(titles, start=1):
        item_start = time.perf_counter()
        print(f"[{i}/{len(titles)}] {title}")

        existing_path = existing_index.get(title.casefold())
        if existing_path:
            existing = existing_valid_file(existing_path)
            if existing:
                number = existing.get("national_number")
                if isinstance(number, int):
                    found_numbers[number] = existing["title"]
                skipped += 1
                print(f"  SKIP : {existing_path.name}")
                print(f"  Total: {time.perf_counter() - item_start:.3f} s")
                continue

        try:
            article, http_time = fetch_page(title)
            http_times.append(http_time)

            number = article["national_number"]
            if number is None:
                ignored += 1
                print("  IGNORÉ : numéro national non détecté / page non-espèce")
            else:
                output_file = OUTPUT_DIR / f"{number:04d}_{slugify(article['title'])}.json"

                found_numbers[number] = article["title"]

                atomic_save(article, output_file)
                found_numbers[number] = article["title"]
                downloaded += 1

                print(f"  N° national : {number:04d}")
                print(f"  Page ID     : {article['page_id']}")
                print(f"  Revision ID : {article['revision_id']}")
                print(f"  Taille      : {len(article['content']):,} caractères")
                print(f"  HTTP/API    : {http_time:.3f} s")
                print(f"  Sauvegarde  : {output_file.name}")

        except Exception as exc:
            error = f"{title}: {type(exc).__name__}: {exc}"
            errors.append(error)
            print(f"  ERREUR : {error}")

        print(f"  Total       : {time.perf_counter() - item_start:.3f} s")

        if i < len(titles):
            time.sleep(REQUEST_DELAY)

    # Re-scan final corpus so resumed runs are checked too.
    final_numbers = {}
    malformed = []
    for path in sorted(OUTPUT_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            number = data.get("national_number")
            if isinstance(number, int) and MIN_NATIONAL_NUMBER <= number <= MAX_NATIONAL_NUMBER:
                final_numbers[number] = data.get("title", path.stem)
        except Exception as exc:
            malformed.append(f"{path.name}: {type(exc).__name__}: {exc}")

    missing = [
        n for n in range(MIN_NATIONAL_NUMBER, MAX_NATIONAL_NUMBER + 1)
        if n not in final_numbers
    ]

    elapsed = time.perf_counter() - global_start

    print()
    print("=" * 84)
    print("RAPPORT GLOBAL — DOWNLOADER POKÉPÉDIA")
    print("=" * 84)
    print(f"Téléchargés cette exécution : {downloaded}")
    print(f"Déjà présents / skip        : {skipped}")
    print(f"Pages candidates ignorées   : {ignored}")
    print(f"Erreurs réseau/API           : {len(errors)}")
    print(f"JSON Pokémon finaux          : {len(final_numbers)}")
    print(f"Numéros manquants            : {len(missing)}")
    print(f"Temps global                 : {elapsed:.3f} s")

    if http_times:
        print(f"HTTP/API moyen               : {sum(http_times) / len(http_times):.3f} s")

    if missing:
        preview = ", ".join(f"{n:04d}" for n in missing[:100])
        suffix = " ..." if len(missing) > 100 else ""
        print(f"\nNUMÉROS MANQUANTS :\n{preview}{suffix}")

    if errors:
        print("\nERREURS :")
        for error in errors:
            print(f"- {error}")

    if malformed:
        print("\nJSON MALFORMÉS :")
        for error in malformed:
            print(f"- {error}")

    # Fail-closed: a corpus incomplet must not look like a successful full run.
    if errors or malformed or missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
