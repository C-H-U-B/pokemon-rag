from __future__ import annotations

import re
import time
from collections import defaultdict

import chromadb
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer
from tqdm import tqdm


# =============================================================================
# CONFIGURATION
# =============================================================================

CHROMA_PATH = "chroma_db"
COLLECTION_NAME = "pokemon_documents"

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

VECTOR_CANDIDATES = 100
BM25_CANDIDATES = 200
RRF_CANDIDATES = 30
RRF_K = 60
DEFAULT_N_RESULTS = 5

# Étape 3 : nombre maximal de candidats structurels ajoutés au pool RRF.
# Ils sont choisis uniquement dans le scope Pokémon déjà validé.
SECTION_CANDIDATES = 12
SECTION_MAX_PER_PATH = 2
MAX_SECTION_EXPANSION_CHUNKS = 8
SECTION_SELECTOR_CANDIDATES = 5


# =============================================================================
# TOKENISATION BM25
# =============================================================================

TOKEN_PATTERN = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿŒœÆæÉéÈèÊêËëÇç'-]+")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


# =============================================================================
# INITIALISATION
# =============================================================================

print("=" * 84)
print("INITIALISATION RAG POKÉMON — HYBRID + RERANKER")
print("=" * 84)

startup_start = time.perf_counter()

client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_collection(COLLECTION_NAME)

print(f"Collection Chroma : {COLLECTION_NAME}")
print(f"Chunks Chroma     : {collection.count():,}")

embedding_start = time.perf_counter()
embedding_model = SentenceTransformer(EMBEDDING_MODEL)
embedding_load_time = time.perf_counter() - embedding_start

print(f"Embedding model   : {EMBEDDING_MODEL}")
print(f"Embedding device  : {embedding_model.device}")
print(f"Chargement embed. : {embedding_load_time:.3f} s")

reranker_start = time.perf_counter()
reranker_model = CrossEncoder(RERANKER_MODEL)
reranker_load_time = time.perf_counter() - reranker_start

print(f"Reranker          : {RERANKER_MODEL}")
print(f"Reranker device   : {reranker_model.device}")
print(f"Chargement rerank : {reranker_load_time:.3f} s")

load_start = time.perf_counter()

# IMPORTANT : ne pas faire collection.get() sur toute la collection en une fois.
# Avec ~35k chunks, Chroma/SQLite peut dépasser sa limite de variables SQL.
# On charge donc le corpus par petits lots déterministes.
CORPUS_IDS = []
CORPUS_DOCUMENTS = []
CORPUS_METADATAS = []

GET_BATCH_SIZE = 500
offset = 0
total_chunks = collection.count()

with tqdm(total=total_chunks, desc="Chargement corpus", unit="chunk", dynamic_ncols=True) as pbar:
    while offset < total_chunks:
        batch = collection.get(
            include=["documents", "metadatas"],
            limit=min(GET_BATCH_SIZE, total_chunks - offset),
            offset=offset,
        )

        batch_ids = batch.get("ids") or []
        if not batch_ids:
            break

        CORPUS_IDS.extend(batch_ids)
        CORPUS_DOCUMENTS.extend(batch.get("documents") or [])
        CORPUS_METADATAS.extend(batch.get("metadatas") or [])

        loaded = len(batch_ids)
        offset += loaded
        pbar.update(loaded)

# Index déterministe : Pokémon canonique -> indices de ses chunks dans le corpus.
# Il permet au BM25 de travailler uniquement dans le document du Pokémon ciblé.
POKEMON_TO_INDICES: dict[str, list[int]] = defaultdict(list)
for idx, metadata in enumerate(CORPUS_METADATAS):
    pokemon = str((metadata or {}).get("pokemon", "")).strip()
    if pokemon:
        POKEMON_TO_INDICES[pokemon].append(idx)

# Index exact des sections fragmentées.
SECTION_TO_INDICES: dict[tuple[str, str], list[int]] = defaultdict(list)
for idx, metadata in enumerate(CORPUS_METADATAS):
    metadata = metadata or {}
    source_file = str(metadata.get("source_file", "")).strip()
    section_path = str(metadata.get("section_path") or metadata.get("section") or "").strip()
    if source_file and section_path:
        SECTION_TO_INDICES[(source_file, section_path)].append(idx)

for indices in SECTION_TO_INDICES.values():
    indices.sort(
        key=lambda idx: int((CORPUS_METADATAS[idx] or {}).get("section_chunk_number", 0))
    )

print(f"Sections indexées  : {len(SECTION_TO_INDICES):,}")
print(f"Chargement corpus : {time.perf_counter() - load_start:.3f} s")

bm25_start = time.perf_counter()
tokenized_corpus = []

for document in tqdm(
    CORPUS_DOCUMENTS,
    desc="Construction BM25",
    unit="chunk",
    dynamic_ncols=True,
):
    tokenized_corpus.append(tokenize(document))

bm25 = BM25Okapi(tokenized_corpus)

print(f"Construction BM25 : {time.perf_counter() - bm25_start:.3f} s")
print(f"Startup total     : {time.perf_counter() - startup_start:.3f} s")
print("=" * 84)
print()


# =============================================================================
# VECTOR SEARCH
# =============================================================================

def vector_retrieve(
    question: str,
    n_candidates: int = VECTOR_CANDIDATES,
    pokemon: str | None = None,
) -> list[dict]:
    start = time.perf_counter()

    query_embedding = embedding_model.encode(
        question,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    query_kwargs = {
        "query_embeddings": [query_embedding.tolist()],
        "n_results": n_candidates,
        "include": ["documents", "metadatas", "distances"],
    }
    if pokemon:
        # Scope strict : Chroma ne peut retourner que les chunks de ce Pokémon.
        query_kwargs["where"] = {"pokemon": pokemon}
        query_kwargs["n_results"] = min(
            n_candidates,
            len(POKEMON_TO_INDICES.get(pokemon, [])),
        )

    if query_kwargs["n_results"] <= 0:
        return []

    result = collection.query(**query_kwargs)

    elapsed = time.perf_counter() - start

    chunks = []
    for rank, (chunk_id, document, metadata, distance) in enumerate(
        zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        ),
        start=1,
    ):
        chunks.append(
            {
                "id": chunk_id,
                "document": document,
                "metadata": metadata,
                "vector_distance": float(distance),
                "vector_rank": rank,
                "vector_time": elapsed,
            }
        )

    return chunks


# =============================================================================
# BM25 SEARCH
# =============================================================================

def bm25_retrieve(
    question: str,
    n_candidates: int = BM25_CANDIDATES,
    pokemon: str | None = None,
) -> list[dict]:
    start = time.perf_counter()

    query_tokens = tokenize(question)
    scores = bm25.get_scores(query_tokens)

    # Scope strict : on classe uniquement les indices appartenant au Pokémon.
    # Sans Pokémon validé, le comportement global reste inchangé.
    if pokemon:
        eligible_indices = np.asarray(
            POKEMON_TO_INDICES.get(pokemon, []),
            dtype=int,
        )
    else:
        eligible_indices = np.arange(len(scores), dtype=int)

    n = min(n_candidates, len(eligible_indices))
    if n == 0:
        return []

    eligible_scores = scores[eligible_indices]
    if n == len(eligible_indices):
        local_order = np.argsort(eligible_scores)[::-1]
    else:
        local_candidates = np.argpartition(eligible_scores, -n)[-n:]
        local_order = local_candidates[
            np.argsort(eligible_scores[local_candidates])[::-1]
        ]

    top_indices = eligible_indices[local_order]

    elapsed = time.perf_counter() - start

    chunks = []
    for rank, idx in enumerate(top_indices, start=1):
        chunks.append(
            {
                "id": CORPUS_IDS[idx],
                "document": CORPUS_DOCUMENTS[idx],
                "metadata": CORPUS_METADATAS[idx],
                "bm25_score": float(scores[idx]),
                "bm25_rank": rank,
                "bm25_time": elapsed,
            }
        )

    return chunks


# =============================================================================
# RRF
# =============================================================================

def reciprocal_rank_fusion(
    vector_results: list[dict],
    bm25_results: list[dict],
    n_results: int = RRF_CANDIDATES,
) -> list[dict]:
    start = time.perf_counter()

    fused: dict[str, dict] = {}
    scores = defaultdict(float)

    for result in vector_results:
        chunk_id = result["id"]
        scores[chunk_id] += 1.0 / (RRF_K + result["vector_rank"])

        fused.setdefault(
            chunk_id,
            {
                "id": chunk_id,
                "document": result["document"],
                "metadata": result["metadata"],
            },
        )

        fused[chunk_id]["vector_rank"] = result["vector_rank"]
        fused[chunk_id]["vector_distance"] = result["vector_distance"]

    for result in bm25_results:
        chunk_id = result["id"]
        scores[chunk_id] += 1.0 / (RRF_K + result["bm25_rank"])

        fused.setdefault(
            chunk_id,
            {
                "id": chunk_id,
                "document": result["document"],
                "metadata": result["metadata"],
            },
        )

        fused[chunk_id]["bm25_rank"] = result["bm25_rank"]
        fused[chunk_id]["bm25_score"] = result["bm25_score"]

    ranked_ids = sorted(scores, key=scores.get, reverse=True)

    results = []
    for rank, chunk_id in enumerate(ranked_ids[:n_results], start=1):
        item = fused[chunk_id]
        item["rrf_score"] = scores[chunk_id]
        item["rrf_rank"] = rank
        results.append(item)

    elapsed = time.perf_counter() - start

    for item in results:
        item["rrf_time"] = elapsed

    return results


# =============================================================================
# SECTION-AWARE CANDIDATE SELECTION + CROSS-ENCODER RERANKING
# =============================================================================

SECTION_TOKEN_PATTERN = re.compile(
    r"[0-9A-Za-zÀ-ÖØ-öø-ÿŒœÆæÉéÈèÊêËëÇç'-]+"
)

# Mots très généraux qui n'aident presque pas à identifier une branche Markdown.
# Ce n'est pas une table de catégories Pokémon : seulement des stopwords français.
SECTION_STOPWORDS = {
    "a", "à", "au", "aux", "avec", "ce", "ces", "cette", "dans", "de", "des",
    "du", "elle", "en", "et", "il", "la", "le", "les", "leur", "leurs", "lui",
    "par", "pour", "que", "quel", "quelle", "quelles", "quels", "qui", "sa",
    "ses", "son", "sur", "un", "une",
}


def normalize_section_tokens(text: str) -> list[str]:
    """Tokenisation légère pour comparer une question à un chemin de section."""
    return [
        token.lower()
        for token in SECTION_TOKEN_PATTERN.findall(text or "")
        if token.lower() not in SECTION_STOPWORDS
    ]


def metadata_section_path(metadata: dict | None) -> str:
    """
    Retourne le chemin hiérarchique complet stocké par l'ingestion.

    `section_path` existe déjà dans la collection V2. Le fallback sur `section`
    permet de rester compatible avec d'anciens chunks.
    """
    metadata = metadata or {}
    return str(
        metadata.get("section_path")
        or metadata.get("section")
        or ""
    ).strip()


def section_structural_candidates(
    question: str,
    pokemon: str | None,
    n_candidates: int = SECTION_CANDIDATES,
) -> list[dict]:
    """
    Ajoute des seeds grâce à la structure Markdown, sans appel LLM/CrossEncoder.

    Important :
    - uniquement quand un Pokémon unique a déjà été validé ;
    - uniquement dans les chunks de ce Pokémon ;
    - aucun nom de section Pokémon n'est codé en dur ;
    - au plus SECTION_MAX_PER_PATH chunks par chemin exact, afin qu'une grosse
      section fragmentée ne monopolise pas le pool avant l'étape 4.
    """
    if not pokemon:
        return []

    scoped_indices = POKEMON_TO_INDICES.get(pokemon, [])
    if not scoped_indices:
        return []

    question_tokens = set(normalize_section_tokens(question))
    if not question_tokens:
        return []

    # Fréquence des tokens parmi les chemins de section distincts du Pokémon.
    unique_paths = {
        metadata_section_path(CORPUS_METADATAS[idx])
        for idx in scoped_indices
        if metadata_section_path(CORPUS_METADATAS[idx])
    }
    if not unique_paths:
        return []

    token_df = defaultdict(int)
    path_tokens_cache: dict[str, set[str]] = {}
    for path in unique_paths:
        tokens = set(normalize_section_tokens(path))
        path_tokens_cache[path] = tokens
        for token in tokens:
            token_df[token] += 1

    n_paths = len(unique_paths)

    def score_path(path: str) -> float:
        tokens = path_tokens_cache.get(path, set())
        matched = question_tokens & tokens
        if not matched:
            return 0.0

        # Les mots rares dans l'arborescence du Pokémon valent davantage.
        rarity_score = sum(
            np.log((n_paths + 1) / (token_df[token] + 1)) + 1.0
            for token in matched
        )

        # Petit bonus de couverture : évite qu'un chemin contenant un seul mot
        # générique gagne face à un chemin qui correspond à plusieurs termes.
        coverage = len(matched) / max(1, len(question_tokens))
        return float(rarity_score * (1.0 + coverage))

    scored = []
    for idx in scoped_indices:
        metadata = CORPUS_METADATAS[idx] or {}
        path = metadata_section_path(metadata)
        score = score_path(path)
        if score <= 0:
            continue
        scored.append((score, idx, path))

    scored.sort(
        key=lambda item: (
            -item[0],
            int((CORPUS_METADATAS[item[1]] or {}).get("chunk_number", 0)),
        )
    )

    results = []
    per_path = defaultdict(int)

    for score, idx, path in scored:
        if per_path[path] >= SECTION_MAX_PER_PATH:
            continue

        results.append({
            "id": CORPUS_IDS[idx],
            "document": CORPUS_DOCUMENTS[idx],
            "metadata": CORPUS_METADATAS[idx],
            "section_path": path,
            "section_structural_score": score,
        })
        per_path[path] += 1

        if len(results) >= n_candidates:
            break

    return results


def merge_candidates(
    rrf_results: list[dict],
    section_results: list[dict],
) -> list[dict]:
    """Union déterministe du Top RRF et des seeds structurels, sans doublons."""
    merged: dict[str, dict] = {}

    for candidate in rrf_results:
        merged[candidate["id"]] = dict(candidate)

    for candidate in section_results:
        chunk_id = candidate["id"]
        if chunk_id in merged:
            merged[chunk_id]["section_path"] = candidate.get("section_path")
            merged[chunk_id]["section_structural_score"] = candidate.get(
                "section_structural_score"
            )
        else:
            merged[chunk_id] = dict(candidate)

    return list(merged.values())


def section_key(candidate: dict) -> tuple[str, str] | None:
    metadata = candidate.get("metadata") or {}
    source_file = str(metadata.get("source_file", "")).strip()
    path = metadata_section_path(metadata)
    if not source_file or not path:
        return None
    return source_file, path


def expand_exact_section(seed: dict, max_chunks: int = MAX_SECTION_EXPANSION_CHUNKS) -> list[dict]:
    """Reconstruit la section exacte du seed, de façon bornée."""
    key = section_key(seed)
    if key is None:
        return [dict(seed)]

    indices = SECTION_TO_INDICES.get(key, [])
    if not indices:
        return [dict(seed)]

    selected = indices
    if len(indices) > max_chunks:
        seed_id = seed.get("id")
        seed_pos = next(
            (i for i, idx in enumerate(indices) if CORPUS_IDS[idx] == seed_id), 0
        )
        half = max_chunks // 2
        start = max(0, seed_pos - half)
        end = min(len(indices), start + max_chunks)
        start = max(0, end - max_chunks)
        selected = indices[start:end]

    expanded = []
    for idx in selected:
        item = {
            "id": CORPUS_IDS[idx],
            "document": CORPUS_DOCUMENTS[idx],
            "metadata": CORPUS_METADATAS[idx],
            "section": metadata_section_path(CORPUS_METADATAS[idx]),
            "expanded_from": seed.get("id"),
            "is_section_expansion": CORPUS_IDS[idx] != seed.get("id"),
        }
        if CORPUS_IDS[idx] == seed.get("id"):
            for name, value in seed.items():
                if name not in {"document", "metadata"}:
                    item[name] = value
        expanded.append(item)

    return expanded


def select_best_section(
    question: str,
    results: list[dict],
    max_candidates: int = SECTION_SELECTOR_CANDIDATES,
    information_need: str | None = None,
) -> tuple[dict | None, list[dict]]:
    """
    Diagnostic de sélection de section sans LLM.

    Deux scores CrossEncoder sont mesurés séparément :
    - content_score : score déjà produit sur le contenu du chunk ;
    - path_score    : question comparée uniquement au chemin de section.

    Pour cette étape, on ne fusionne PAS encore ces scores. Le but est de
    mesurer si le chemin de section apporte réellement un signal utile avant
    de choisir une formule de combinaison.
    """
    grouped: dict[tuple[str, str], dict] = {}

    for result in results:
        key = section_key(result)
        if key is None:
            continue

        current = grouped.get(key)
        if current is None or result.get("reranker_rank", 10**9) < current.get(
            "reranker_rank", 10**9
        ):
            grouped[key] = result

    candidates = sorted(
        grouped.values(),
        key=lambda item: item.get("reranker_rank", 10**9),
    )[:max_candidates]

    if not candidates:
        return None, []

    paths = [
        metadata_section_path(candidate.get("metadata"))
        for candidate in candidates
    ]

    focus = (information_need or question).strip()
    # Diagnostic : le besoin informationnel est comparé à une représentation
    # de la section qui contient à la fois son chemin et le contenu du seed.
    # Aucun appel LLM supplémentaire : on réutilise le CrossEncoder déjà chargé.
    section_representations = [
        f"Section : {path}\n\n{candidate.get('document', '')}"
        for candidate, path in zip(candidates, paths)
    ]

    focus_scores = reranker_model.predict(
        [(focus, representation) for representation in section_representations],
        show_progress_bar=False,
        convert_to_numpy=True,
    )

    diagnostics = []
    for candidate, path, focus_score in zip(candidates, paths, focus_scores):
        diagnostics.append({
            "section_path": path,
            "seed_id": candidate.get("id"),
            "information_need": focus,
            "content_score": float(candidate.get("reranker_score") or 0.0),
            "focus_score": float(focus_score),
            "structural_score": float(
                candidate.get("section_structural_score") or 0.0
            ),
            "original_reranker_rank": candidate.get("reranker_rank"),
        })

    # IMPORTANT : pour ce test diagnostique, on conserve le meilleur résultat
    # contenu comme seed. On ne change donc pas encore le comportement métier.
    # Le prochain log permettra de décider d'une combinaison fondée sur les
    # scores réellement observés.
    return candidates[0], diagnostics



def expand_best_section(
    question: str,
    results: list[dict],
    information_need: str | None = None,
) -> tuple[list[dict], dict]:
    """
    Sélectionne d'abord la meilleure section logique parmi le Top-K, puis étend
    uniquement cette section exacte.
    """
    seed, selector_diagnostics = select_best_section(question, results, information_need=information_need)

    if seed is None:
        return list(results), {
            "expanded": False,
            "seed_id": None,
            "section_path": None,
            "section_chunks": 0,
            "selector_candidates": selector_diagnostics,
        }

    expanded = expand_exact_section(seed)
    return expanded, {
        "expanded": len(expanded) > 1,
        "seed_id": seed.get("id"),
        "section_path": metadata_section_path(seed.get("metadata")),
        "section_chunks": len(expanded),
        "selector_candidates": selector_diagnostics,
    }



def rerank_candidates(
    question: str,
    candidates: list[dict],
    n_results: int = DEFAULT_N_RESULTS,
) -> tuple[list[dict], float]:
    """
    Reranking final sur le contenu des chunks.

    La structure sert désormais à garantir la présence de bons seeds dans le
    pool de candidats. Le CrossEncoder n'a plus à "deviner" la pertinence d'un
    chemin de section via un second score artificiellement pondéré.
    """
    start = time.perf_counter()

    if not candidates:
        return [], time.perf_counter() - start

    pairs = [(question, candidate["document"]) for candidate in candidates]
    scores = reranker_model.predict(
        pairs,
        show_progress_bar=False,
        convert_to_numpy=True,
    )

    ranked = sorted(
        zip(candidates, scores),
        key=lambda item: float(item[1]),
        reverse=True,
    )

    results = []
    for rank, (candidate, score) in enumerate(ranked[:n_results], start=1):
        item = dict(candidate)
        item["section"] = metadata_section_path(item.get("metadata"))
        item["reranker_score"] = float(score)
        item["reranker_rank"] = rank
        results.append(item)

    elapsed = time.perf_counter() - start

    for item in results:
        item["reranker_time"] = elapsed

    return results, elapsed


# =============================================================================
# INTERFACE PRINCIPALE
# =============================================================================

def retrieve(
    question: str,
    n_results: int = DEFAULT_N_RESULTS,
    rerank: bool = True,
    pokemon: str | None = None,
    information_need: str | None = None,
) -> list[dict]:
    """
    Retrieval Pokémon.

    rerank=False :
        Vector Top-100 + BM25 Top-200 -> RRF -> Top-K

    rerank=True :
        Vector Top-100 + BM25 Top-200 -> RRF Top-30
        + seeds structurels du Pokémon ciblé
        -> CrossEncoder contenu -> Top-K
    """
    total_start = time.perf_counter()

    vector_start = time.perf_counter()
    vector_results = vector_retrieve(question, pokemon=pokemon)
    vector_time = time.perf_counter() - vector_start

    bm25_start = time.perf_counter()
    bm25_results = bm25_retrieve(question, pokemon=pokemon)
    bm25_time = time.perf_counter() - bm25_start

    rrf_start = time.perf_counter()
    rrf_results = reciprocal_rank_fusion(
        vector_results,
        bm25_results,
        n_results=RRF_CANDIDATES if rerank else n_results,
    )
    rrf_time = time.perf_counter() - rrf_start

    section_results = section_structural_candidates(
        question,
        pokemon=pokemon,
    )
    rerank_pool = merge_candidates(rrf_results, section_results)

    reranker_time = 0.0

    if rerank:
        results, reranker_time = rerank_candidates(
            question,
            rerank_pool,
            n_results=n_results,
        )
    else:
        results = rrf_results[:n_results]

    # Top-K = diagnostic ; context_results = section logique reconstruite.
    context_results, expansion_info = expand_best_section(question, results, information_need=information_need)

    total_time = time.perf_counter() - total_start

    for result in results:
        result["timings"] = {
            "vector": vector_time,
            "bm25": bm25_time,
            "rrf": rrf_time,
            "reranker": reranker_time,
            "total": total_time,
        }
        result["rerank_enabled"] = rerank
        result["retrieval_scope"] = pokemon or "GLOBAL"
        result["section_candidates_added"] = len(section_results)
        result["rerank_pool_size"] = len(rerank_pool)
        result["section_expansion"] = expansion_info

    if results:
        results[0]["context_results"] = context_results

    return results



def retrieve_retry_context(
    question: str,
    grounding_reason: str,
    pokemon: str | None = None,
    excluded_section_path: str | None = None,
) -> list[dict]:
    """
    Retry documentaire pour une question unique.

    Le retry cherche UNE meilleure section, puis reconstruit uniquement cette
    section logique avec expand_exact_section(). Si un Pokémon a été validé,
    le scope reste strictement limité à ce Pokémon.
    """
    retry_query = question.strip()
    if grounding_reason:
        retry_query += (
            "\nIndice sur l'information manquante, à utiliser uniquement pour "
            "la recherche documentaire : " + grounding_reason.strip()
        )

    candidates = retrieve(
        retry_query,
        n_results=max(DEFAULT_N_RESULTS, 8),
        rerank=True,
        pokemon=pokemon,
    )
    if not candidates:
        return []

    excluded = (excluded_section_path or "").strip()

    # On préfère une section différente de celle qui a déjà été jugée
    # insuffisante. Cela évite de refaire exactement le même contexte.
    for candidate in candidates:
        metadata = candidate.get("metadata") or {}
        section_path = str(
            metadata.get("section_path") or metadata.get("section") or ""
        ).strip()

        if excluded and section_path == excluded:
            continue

        expanded = expand_exact_section(candidate)
        if expanded:
            return expanded

    # Si aucune autre section n'est disponible, on reste fail-closed :
    # renvoyer [] vaut mieux que prétendre avoir enrichi le contexte.
    return []


# =============================================================================
# AFFICHAGE / TEST MANUEL
# =============================================================================

def print_results(question: str, results: list[dict]) -> None:
    print()
    print("=" * 84)
    print(f"QUESTION : {question}")
    print("=" * 84)

    if not results:
        print("Aucun résultat.")
        return

    rerank_enabled = results[0].get("rerank_enabled", False)
    print(f"Reranker : {'ON' if rerank_enabled else 'OFF'}")
    print(f"Scope    : {results[0].get('retrieval_scope', 'GLOBAL')}")
    print(
        f"Pool     : {results[0].get('rerank_pool_size', '?')} candidats "
        f"(+{results[0].get('section_candidates_added', 0)} structurels avant déduplication)"
    )
    expansion = results[0].get("section_expansion") or {}
    if expansion.get("section_path"):
        print(
            f"Expansion: {expansion['section_chunks']} chunk(s) | "
            f"{expansion['section_path']}"
        )
        selector_candidates = expansion.get("selector_candidates") or []
        if selector_candidates:
            print("Sélection section :")
            for item in selector_candidates:
                print(
                    f"  contenu={item['content_score']:.4f} | "
                    f"chemin={item['path_score']:.4f} | "
                    f"{item['section_path']} "
                    f"(rang initial {item.get('original_reranker_rank', '?')})"
                )

    for rank, result in enumerate(results, start=1):
        metadata = result["metadata"]

        pokemon = metadata.get("pokemon", "?")
        national_number = metadata.get("national_number", "?")
        source_file = metadata.get("source_file", "?")
        chunk_number = metadata.get("chunk_number", "?")

        print()
        print(f"[{rank}] #{national_number} — {pokemon}")
        print(f"    Fichier       : {source_file}")
        print(f"    Chunk         : {chunk_number}")
        print(
            f"    RRF           : rang {result.get('rrf_rank', '?')} "
            f"| score {result.get('rrf_score', 0):.6f}"
        )

        if "reranker_score" in result:
            print(
                f"    Reranker      : rang {result['reranker_rank']} "
                f"| score combiné {result['reranker_score']:.6f}"
            )
            if result.get("section"):
                print(f"    Section       : {result['section']}")
            if result.get("section_structural_score") is not None:
                print(
                    f"    Score structure: "
                    f"{result['section_structural_score']:.6f}"
                )

        if "vector_rank" in result:
            print(
                f"    Vector        : rang {result['vector_rank']} "
                f"| distance {result['vector_distance']:.6f}"
            )
        else:
            print("    Vector        : hors Top candidats")

        if "bm25_rank" in result:
            print(
                f"    BM25          : rang {result['bm25_rank']} "
                f"| score {result['bm25_score']:.6f}"
            )
        else:
            print("    BM25          : hors Top candidats")

        preview = re.sub(r"\s+", " ", result["document"]).strip()
        if len(preview) > 300:
            preview = preview[:297] + "..."

        print(f"    Extrait       : {preview}")

    timings = results[0]["timings"]

    print()
    print("-" * 84)
    print("TIMINGS")
    print(f"Vector   : {timings['vector'] * 1000:.2f} ms")
    print(f"BM25     : {timings['bm25'] * 1000:.2f} ms")
    print(f"RRF      : {timings['rrf'] * 1000:.2f} ms")
    print(f"Reranker : {timings['reranker'] * 1000:.2f} ms")
    print(f"TOTAL    : {timings['total'] * 1000:.2f} ms")
    print("-" * 84)


def main() -> None:
    print("RAG Pokémon prêt.")
    print("Commandes : /rerank on | /rerank off | quit")

    rerank_enabled = True

    while True:
        try:
            question = input("\nQuestion > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not question:
            continue

        command = question.lower()

        if command in {"quit", "exit", "q"}:
            break

        if command == "/rerank on":
            rerank_enabled = True
            print("Reranker activé.")
            continue

        if command == "/rerank off":
            rerank_enabled = False
            print("Reranker désactivé.")
            continue

        results = retrieve(
            question,
            n_results=DEFAULT_N_RESULTS,
            rerank=rerank_enabled,
        )
        print_results(question, results)


if __name__ == "__main__":
    main()
