from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
from tqdm import tqdm


# =============================================================================
# CONFIGURATION
# =============================================================================

CLEANED_DIR = Path("pokemon/corpus/cleaned")
CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "pokemon_documents"

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Taille cible pour les gros blocs à l'intérieur d'une même section Markdown.
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120

EMBEDDING_BATCH_SIZE = 64
CHROMA_BATCH_SIZE = 1000

# On injecte le nom du Pokémon + le chemin de section dans le texte indexé.
# Cela aide Vector, BM25 et le CrossEncoder sans modifier le corpus source.
INJECT_CONTEXT_HEADER = True


# =============================================================================
# UTILITAIRES
# =============================================================================

def parse_filename(path: Path) -> tuple[int | None, str]:
    match = re.match(r"^(\d{4})_(.+)$", path.stem)
    if not match:
        return None, path.stem
    return int(match.group(1)), match.group(2)


def extract_title(text: str, fallback_slug: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title
    return fallback_slug.replace("_", " ").strip().title()


def extract_metadata_value(text: str, labels: list[str]) -> str:
    for label in labels:
        pattern = rf"(?im)^\s*(?:[-*]\s*)?\**{re.escape(label)}\**\s*:\s*(.+?)\s*$"
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def make_chunk_id(source_file: str, section_path: str, chunk_number: int) -> str:
    """ID stable et unique par fichier + section + chunk."""
    safe_source = re.sub(r"[^a-zA-Z0-9_.-]+", "_", source_file)
    section_hash = hashlib.sha1(section_path.encode("utf-8")).hexdigest()[:10]
    return f"pokemon::{safe_source}::section::{section_hash}::chunk::{chunk_number:05d}"


def batched(sequence, batch_size: int):
    for start in range(0, len(sequence), batch_size):
        yield start, sequence[start:start + batch_size]


def clean_heading_title(title: str) -> str:
    """Nettoyage léger d'un titre Markdown, sans essayer de réinterpréter le wiki."""
    title = re.sub(r"\s+#+\s*$", "", title).strip()
    return title


# =============================================================================
# CHUNKING STRUCTURÉ MARKDOWN
# =============================================================================

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def split_markdown_sections(text: str) -> list[dict]:
    """
    Découpe le document en blocs selon les titres Markdown.

    Chaque bloc garde le chemin hiérarchique actif, par exemple :
        Capacités apprises > Par montée en niveau > Neuvième génération

    Le H1 (# Capumain) sert de titre de document et n'est pas répété comme section.
    """
    sections: list[dict] = []
    heading_stack: dict[int, str] = {}
    current_lines: list[str] = []
    current_path: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        body = "\n".join(current_lines).strip()
        if body:
            sections.append({
                "section_path": current_path.copy(),
                "text": body,
            })
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = HEADING_RE.match(line.strip())

        if not match:
            current_lines.append(line)
            continue

        level = len(match.group(1))
        title = clean_heading_title(match.group(2))

        # H1 = titre du document : on ne le considère pas comme une section.
        if level == 1:
            flush()
            heading_stack.clear()
            current_path = []
            continue

        flush()

        # Un nouveau heading ferme les niveaux égaux ou plus profonds.
        for existing_level in list(heading_stack):
            if existing_level >= level:
                del heading_stack[existing_level]

        heading_stack[level] = title
        current_path = [
            heading_stack[lvl]
            for lvl in sorted(heading_stack)
        ]

    flush()
    return sections


def build_indexed_chunk(
    pokemon_name: str,
    section_path: list[str],
    body: str,
) -> str:
    """
    Ajoute un petit en-tête sémantique au chunk indexé.

    Important : cet en-tête fait partie du texte stocké dans Chroma et sera donc
    visible par Vector, BM25, le reranker et le LLM.
    """
    body = body.strip()
    if not INJECT_CONTEXT_HEADER:
        return body

    lines = [f"Pokémon : {pokemon_name}"]
    if section_path:
        lines.append(f"Section : {' > '.join(section_path)}")
    lines.append("")
    lines.append(body)
    return "\n".join(lines).strip()


def split_section_body(
    pokemon_name: str,
    section_path: list[str],
    body: str,
    splitter: RecursiveCharacterTextSplitter,
) -> list[str]:
    """
    Découpe uniquement À L'INTÉRIEUR d'une section.

    Ainsi une section courte (statistiques, talents, liste de capacités...) reste
    intacte. Une très grosse section est découpée, mais tous ses sous-chunks
    conservent le même chemin de section dans leur en-tête.
    """
    body = body.strip()
    if not body:
        return []

    # L'en-tête consomme une partie de la taille cible : on split le corps avec
    # une marge pour éviter des chunks beaucoup plus grands que CHUNK_SIZE.
    header = build_indexed_chunk(pokemon_name, section_path, "")
    available_size = max(350, CHUNK_SIZE - len(header) - 2)

    if len(body) <= available_size:
        return [build_indexed_chunk(pokemon_name, section_path, body)]

    local_splitter = RecursiveCharacterTextSplitter(
        chunk_size=available_size,
        chunk_overlap=min(CHUNK_OVERLAP, max(0, available_size // 4)),
        separators=splitter._separators,
        length_function=len,
    )

    return [
        build_indexed_chunk(pokemon_name, section_path, piece)
        for piece in local_splitter.split_text(body)
        if piece.strip()
    ]


def load_and_chunk_documents(files: list[Path]) -> tuple[list[str], list[dict], list[str], dict]:
    base_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )

    documents: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []

    stats = {
        "sections": 0,
        "files_with_no_sections": 0,
        "max_chunk_chars": 0,
        "min_chunk_chars": None,
        "total_chunk_chars": 0,
    }

    progress = tqdm(files, desc="Lecture + chunking structuré", unit="fichier", dynamic_ncols=True)

    for path in progress:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            tqdm.write(f"[WARNING] Fichier vide ignoré : {path.name}")
            continue

        national_number, slug = parse_filename(path)
        pokemon_name = extract_title(text, slug)
        revision_id = extract_metadata_value(text, ["Revision ID", "Révision ID", "revision_id"])
        source_url = extract_metadata_value(text, ["URL source", "Source URL", "source_url"])

        sections = split_markdown_sections(text)

        # Fail-safe : si le Markdown est étrange, on ne perd pas le document.
        if not sections:
            stats["files_with_no_sections"] += 1
            sections = [{"section_path": [], "text": text}]

        stats["sections"] += len(sections)
        file_chunk_number = 0

        for section in sections:
            section_path_list = section["section_path"]
            section_path = " > ".join(section_path_list) if section_path_list else "Document"
            section_level = len(section_path_list)
            section_name = section_path_list[-1] if section_path_list else "Document"
            top_section = section_path_list[0] if section_path_list else "Document"

            section_chunks = split_section_body(
                pokemon_name,
                section_path_list,
                section["text"],
                base_splitter,
            )

            for section_chunk_number, chunk in enumerate(section_chunks):
                metadata = {
                    "pokemon": pokemon_name,
                    "pokemon_slug": slug,
                    "source_file": path.name,
                    "chunk_number": file_chunk_number,
                    "section_chunk_number": section_chunk_number,
                    "section": section_path,
                    "section_path": section_path,
                    "section_name": section_name,
                    "section_root": top_section,
                    "section_depth": section_level,
                    "document_type": "pokemon",
                }

                # Hiérarchie explicite, sans profondeur codée en dur.
                for level_index, level_name in enumerate(section_path_list, start=1):
                    metadata[f"section_l{level_index}"] = level_name

                if national_number is not None:
                    metadata["national_number"] = national_number
                if revision_id:
                    metadata["revision_id"] = revision_id
                if source_url:
                    metadata["source_url"] = source_url

                documents.append(chunk)
                metadatas.append(metadata)
                ids.append(make_chunk_id(path.name, section_path, file_chunk_number))

                chunk_len = len(chunk)
                stats["max_chunk_chars"] = max(stats["max_chunk_chars"], chunk_len)
                if stats["min_chunk_chars"] is None:
                    stats["min_chunk_chars"] = chunk_len
                else:
                    stats["min_chunk_chars"] = min(stats["min_chunk_chars"], chunk_len)
                stats["total_chunk_chars"] += chunk_len

                file_chunk_number += 1

        progress.set_postfix(pokemon=pokemon_name[:18], chunks_total=len(documents))

    return documents, metadatas, ids, stats


# =============================================================================
# INGESTION
# =============================================================================

def main() -> None:
    total_start = time.perf_counter()

    print("=" * 88)
    print("INGESTION RAG POKÉMON V2 — CHUNKING MARKDOWN STRUCTURÉ")
    print("=" * 88)
    print(f"Corpus             : {CLEANED_DIR}")
    print(f"Chroma             : {CHROMA_PATH}")
    print(f"Collection         : {COLLECTION_NAME}")
    print(f"Embedding model    : {EMBEDDING_MODEL}")
    print(f"Chunk size cible   : {CHUNK_SIZE}")
    print(f"Chunk overlap      : {CHUNK_OVERLAP}")
    print(f"En-tête contextuel : {INJECT_CONTEXT_HEADER}")
    print()

    files = sorted(CLEANED_DIR.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"Aucun fichier .md trouvé dans {CLEANED_DIR.resolve()}")

    print(f"Fichiers trouvés : {len(files):,}\n")

    # 1. Lecture + chunking
    chunk_start = time.perf_counter()
    documents, metadatas, ids, chunk_stats = load_and_chunk_documents(files)
    chunk_time = time.perf_counter() - chunk_start

    if not documents:
        raise RuntimeError("Aucun chunk généré.")
    if len(documents) != len(metadatas) or len(documents) != len(ids):
        raise RuntimeError("Documents / métadonnées / IDs désynchronisés.")
    if len(ids) != len(set(ids)):
        raise RuntimeError("IDs Chroma dupliqués détectés.")

    avg_chunk_chars = chunk_stats["total_chunk_chars"] / len(documents)

    print()
    print(f"Sections détectées : {chunk_stats['sections']:,}")
    print(f"Chunks générés     : {len(documents):,}")
    print(f"Taille moyenne     : {avg_chunk_chars:,.1f} caractères")
    print(f"Taille min/max     : {chunk_stats['min_chunk_chars']:,} / {chunk_stats['max_chunk_chars']:,}")
    print(f"Chunking            : {chunk_time:.3f} s\n")

    # 2. Modèle d'embedding
    model_start = time.perf_counter()
    model = SentenceTransformer(EMBEDDING_MODEL)
    device = str(model.device)
    model_load_time = time.perf_counter() - model_start

    print(f"Device embedding   : {device}")
    print(f"Chargement modèle  : {model_load_time:.3f} s\n")

    # 3. Embeddings — barre de progression native SentenceTransformers
    embedding_start = time.perf_counter()
    embeddings = model.encode(
        documents,
        batch_size=EMBEDDING_BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    embedding_time = time.perf_counter() - embedding_start

    print()
    print(f"Embeddings          : {embedding_time:.3f} s")
    print(
        f"Vitesse embedding   : {len(documents) / embedding_time:,.1f} chunks/s"
        if embedding_time > 0 else "Vitesse embedding   : n/a"
    )
    print()

    # 4. Chroma
    chroma_start = time.perf_counter()
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"Ancienne collection '{COLLECTION_NAME}' supprimée.")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    progress = tqdm(total=len(documents), desc="Insertion Chroma", unit="chunk", dynamic_ncols=True)

    for start, batch_documents in batched(documents, CHROMA_BATCH_SIZE):
        end = start + len(batch_documents)
        collection.add(
            ids=ids[start:end],
            documents=batch_documents,
            metadatas=metadatas[start:end],
            embeddings=embeddings[start:end].tolist(),
        )
        progress.update(len(batch_documents))

    progress.close()
    chroma_time = time.perf_counter() - chroma_start
    total_time = time.perf_counter() - total_start

    # 5. Validation
    stored_count = collection.count()

    print()
    print("=" * 88)
    print("RAPPORT GLOBAL — INGESTION POKÉMON V2")
    print("=" * 88)
    print(f"Fichiers lus                 : {len(files):,}")
    print(f"Sections détectées           : {chunk_stats['sections']:,}")
    print(f"Fallback sans section        : {chunk_stats['files_with_no_sections']:,}")
    print(f"Chunks générés               : {len(documents):,}")
    print(f"Chunks dans Chroma           : {stored_count:,}")
    print(f"Taille moyenne des chunks    : {avg_chunk_chars:,.1f} caractères")
    print(f"Dimension embeddings         : {embeddings.shape[1]}")
    print(f"Device                       : {device}")
    print()
    print(f"Lecture + chunking            : {chunk_time:.3f} s")
    print(f"Chargement modèle             : {model_load_time:.3f} s")
    print(f"Calcul embeddings             : {embedding_time:.3f} s")
    print(f"Insertion Chroma              : {chroma_time:.3f} s")
    print(f"TEMPS TOTAL                   : {total_time:.3f} s")

    if stored_count != len(documents):
        raise RuntimeError(
            f"Ingestion incomplète : {stored_count:,} chunks dans Chroma "
            f"pour {len(documents):,} chunks générés."
        )

    print()
    print("✓ Ingestion V2 terminée et vérifiée.")
    print("✓ Les chunks conservent maintenant le chemin de section Markdown.")


if __name__ == "__main__":
    main()
