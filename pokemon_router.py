from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any

from openai import OpenAI



LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
ROUTER_MODEL = "qwen/qwen3-vl-8b"
DB_PATH = Path("pokemon/corpus/pokemon.db")

VALID_ROUTES = {"RAG", "STRUCTURED", "HYBRID"}
VALID_INTENTS = {"PROFILE", "STRUCTURED_QUERY", "DOCUMENT_SEARCH"}

llm_client = OpenAI(base_url=LM_STUDIO_BASE_URL, api_key="lm-studio")


ROUTER_SYSTEM_PROMPT = """
Tu es le routeur d'un système de questions-réponses sur Pokémon.

Tu dois UNIQUEMENT choisir les sources nécessaires.
Tu ne dois jamais répondre à la question Pokémon.

=== CONTRAINTE DE PORTÉE ===

Le système accepte UNE SEULE question ou UN SEUL besoin informationnel par requête.

single_question = true si la demande peut être satisfaite comme une seule recherche
cohérente, même si la réponse contient plusieurs éléments d'une même catégorie.
Exemples :
- "Quelles capacités Pikachu apprend-il par CT dans EV ?" -> true
- "Quelles capacités Roitiflam apprend-il après le niveau 40 ?" -> true
- "Quels sont les talents de Dracaufeu ?" -> true

single_question = false si l'utilisateur combine plusieurs besoins informationnels
indépendants qui nécessiteraient des recherches ou sections distinctes.
Exemples :
- "Comment Pikachu évolue-t-il et quelles CT apprend-il dans EV ?" -> false
- "Quels sont les talents de Dracaufeu et où peut-on le capturer ?" -> false
- "Donne les statistiques de Pikachu et explique son évolution." -> false

Ne te base pas uniquement sur la présence de "et" : juge si la requête contient
réellement plusieurs besoins informationnels indépendants.

=== SOURCE STRUCTURED ===

La source STRUCTURED est pokemon.db. Elle contient les données du tableur ET
les données PokéAPI intégrées.

Elle sait notamment répondre de manière déterministe à :
- nom, numéro, forme, types, statistiques, talents et particularités du tableur ;
- évolutions et conditions d'évolution ;
- capacités apprises par montée de niveau, avec niveau et groupe de versions ;
- capacités apprises par machine (CT/CS), avec groupe de versions ;
- méthodes d'apprentissage d'une capacité présentes dans PokéAPI
  (level-up, machine, egg, tutor, etc.).

Donc les questions suivantes utilisent STRUCTURED :
- "Comment Pikachu évolue-t-il ?"
- "Quelle capacité X apprend-il au niveau Y ?"
- "Quelles capacités X apprend-il après/avant le niveau Y ?"
- "Quelles capacités X apprend-il par CT dans EV ?"
- "Comment X peut-il apprendre la capacité Y ?"

IMPORTANT :
- STRUCTURED ne doit restituer que les informations réellement présentes dans
  pokemon.db.
- Une explication documentaire détaillée sur le fonctionnement, l'histoire,
  la biologie ou une condition absente de pokemon.db reste du ressort du RAG.

=== SOURCE RAG ===

Le corpus Poképédia contient les informations documentaires détaillées :
capacités apprises et niveaux, descriptions, explications, formes,
évolutions, biologie, détails textuels, etc.

=== ROUTES ===

STRUCTURED :
le tableur suffit à répondre de manière déterministe.

RAG :
la réponse dépend du corpus documentaire et le tableur n'apporte pas
d'information structurée utile indispensable.

HYBRID :
les données structurées ET les documents sont utiles.

=== INTENTS ===

PROFILE :
demande générale de présentation ou de particularités d'un Pokémon précis.
Exemples d'intention : parler d'un Pokémon, dire ce qui le rend particulier,
unique, spécial ou intéressant.
Un PROFILE utilise HYBRID.

STRUCTURED_QUERY :
filtre, comparaison, classement, comptage, minimum, maximum ou recherche
portant sur les colonnes réellement présentes dans STRUCTURED.

DOCUMENT_SEARCH :
recherche ou explication documentaire précise.
Elle peut utiliser RAG ou HYBRID.

Règles :
- Une question "pourquoi" ou demandant une explication détaillée est
  généralement DOCUMENT_SEARCH, pas PROFILE.
- Une question sur les capacités apprises, leurs niveaux, les CT/CS ou une
  méthode d'apprentissage disponible dans pokemon.db est STRUCTURED_QUERY + STRUCTURED.
- Une question sur une évolution ou ses conditions disponibles dans pokemon.db
  est STRUCTURED_QUERY + STRUCTURED.
- "Capacité signature" est également une donnée STRUCTURED.
- Si une question documentaire précise porte aussi sur une forme ou une
  particularité présente dans le tableur, HYBRID est possible.
- Si un nom de forme est explicitement écrit par l'utilisateur, conserve
  le nom COMPLET de cette forme. Ne le réduis jamais au Pokémon de base.
- N'invente aucune colonne ni aucune donnée.
- Si aucun Pokémon précis n'est identifié, pokemon = null.

=== BESOIN INFORMATIONNEL ===

Produis aussi `information_need` : une reformulation courte et précise de
l'information qu'il faut trouver pour répondre à la question.
Conserve les contraintes utiles (méthode, condition, jeu, génération, niveau,
comparaison ou intervalle), mais ne réponds pas à la question.

Exemples :
- "Comment Pikachu peut-il apprendre Électacle ?" ->
  "méthode ou condition permettant à Pikachu d'apprendre Électacle"
- "Comment Pikachu évolue-t-il ?" ->
  "méthode et conditions d'évolution de Pikachu"
- "Quelles capacités Roitiflam apprend-il après le niveau 40 ?" ->
  "capacités apprises par Roitiflam par montée en niveau après le niveau 40"
- "Quelles capacités Pikachu apprend-il par CT dans EV ?" ->
  "capacités apprises par Pikachu par CT dans EV"

Réponds UNIQUEMENT en JSON valide :
{
  "route": "RAG" | "STRUCTURED" | "HYBRID",
  "intent": "PROFILE" | "STRUCTURED_QUERY" | "DOCUMENT_SEARCH",
  "pokemon": string | null,
  "single_question": true | false,
  "information_need": string,
  "reason": string
}
""".strip()


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Aucun JSON trouvé.")
        value = json.loads(match.group(0))

    if not isinstance(value, dict):
        raise ValueError("Le résultat n'est pas un objet JSON.")
    return value


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("’", "'").replace("œ", "oe")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _canonical_pokemon_name(name: str) -> str | None:
    """Valide le nom uniquement à partir de pokemon.db."""
    target = normalize_text(name)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT name_fr, name_en
            FROM custom_pokedex
            WHERE name_fr IS NOT NULL OR name_en IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()

    exact = []
    for row in rows:
        for candidate in (row["name_fr"], row["name_en"]):
            if candidate and normalize_text(candidate) == target:
                exact.append(str(row["name_fr"] or row["name_en"]))
                break

    unique = list(dict.fromkeys(exact))
    if len(unique) == 1:
        return unique[0]

    return None


def _validate_router_output(
    raw: dict[str, Any],
    question: str,
) -> dict[str, Any]:
    route = str(raw.get("route", "")).strip().upper()
    intent = str(raw.get("intent", "")).strip().upper()
    reason = str(raw.get("reason", "")).strip()
    single_question = raw.get("single_question")
    information_need = str(raw.get("information_need", "")).strip()
    if not information_need:
        information_need = question.strip()

    if not isinstance(single_question, bool):
        raise ValueError("single_question doit être un booléen.")

    if route not in VALID_ROUTES:
        raise ValueError(f"Route invalide : {route!r}")
    if intent not in VALID_INTENTS:
        raise ValueError(f"Intent invalide : {intent!r}")

    raw_pokemon = raw.get("pokemon")
    pokemon = None
    pokemon_validated = False

    if isinstance(raw_pokemon, str) and raw_pokemon.strip():
        pokemon = _canonical_pokemon_name(raw_pokemon.strip())
        pokemon_validated = pokemon is not None

    # Invariant : PROFILE = HYBRID.
    if intent == "PROFILE":
        route = "HYBRID"

    # Si Qwen annonce PROFILE mais que son entité ne peut pas être validée,
    # on ne lance pas de lookup structuré arbitraire.
    if intent == "PROFILE" and not pokemon_validated:
        route = "RAG"
        intent = "DOCUMENT_SEARCH"

    return {
        "route": route,
        "intent": intent,
        "pokemon": pokemon,
        "pokemon_validated": pokemon_validated,
        "single_question": single_question,
        "information_need": information_need,
        "reason": reason,
    }


def route_question(question: str) -> dict[str, Any]:
    start = time.perf_counter()

    try:
        response = llm_client.chat.completions.create(
            model=ROUTER_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        )

        raw_text = response.choices[0].message.content or ""
        raw = _extract_json(raw_text)
        result = _validate_router_output(raw, question)

        result["router_error"] = None
        result["router_time"] = time.perf_counter() - start
        return result

    except Exception as exc:
        return {
            "route": "RAG",
            "intent": "DOCUMENT_SEARCH",
            "pokemon": None,
            "pokemon_validated": False,
            "single_question": True,
            "information_need": question.strip(),
            "reason": "Fallback déterministe après échec du routeur.",
            "router_error": f"{type(exc).__name__}: {exc}",
            "router_time": time.perf_counter() - start,
        }


if __name__ == "__main__":
    questions = [
        "Qu'est-ce que tu peux me dire sur Lovdisc ?",
        "Qu'est-ce qui rend Lovdisc unique ?",
        "Quel Pokémon a la meilleure Vitesse ?",
        "Pourquoi Darumacho de Galar peut-il devenir de type Glace/Feu ?",
        "Quelle capacité Capumain apprend-il au niveau 15 ?",
    ]

    suite_start = time.perf_counter()

    print("=" * 90)
    print("TEST MANUEL DU ROUTER POKÉMON V2")
    print("=" * 90)

    for i, question in enumerate(questions, 1):
        print(f"\n[{i}/{len(questions)}] {question}")
        result = route_question(question)

        print(f"Route              : {result['route']}")
        print(f"Intent             : {result['intent']}")
        print(f"Pokémon            : {result['pokemon']}")
        print(f"Pokémon validé     : {result['pokemon_validated']}")
        print(f"Raison             : {result['reason']}")
        print(f"Temps router       : {result['router_time']:.3f} s")

        if result["router_error"]:
            print(f"ERREUR             : {result['router_error']}")

    print("\n" + "=" * 90)
    print(f"TEMPS TOTAL : {time.perf_counter() - suite_start:.3f} s")
    print("=" * 90)
