from __future__ import annotations

import json
import re
import time

from openai import OpenAI


LM_STUDIO_URL = "http://localhost:1234/v1"
SUFFICIENCY_MODEL = "qwen/qwen3-vl-8b"

client = OpenAI(
    base_url=LM_STUDIO_URL,
    api_key="lm-studio",
)


SUFFICIENCY_SYSTEM_PROMPT = """
Tu vérifies uniquement si un contexte documentaire contient les informations
nécessaires pour répondre à une question.

Tu ne réponds jamais à la question.
Tu n'évalues aucune réponse générée.
Tu n'utilises aucune connaissance externe.
Le contexte fourni est l'unique source de vérité.

Le système traite une seule question ou un seul besoin informationnel à la fois.

Procédure obligatoire :
1. Identifie le besoin informationnel exact exprimé par la question.
2. Détermine la nature de l'information demandée : identité, liste, méthode,
   condition, lieu, moment, valeur, cause, comparaison ou autre relation.
3. Vérifie si le contexte contient explicitement, ou permet de déduire
   directement, l'information nécessaire pour satisfaire ce besoin.
4. Un contexte qui parle du bon sujet mais ne fournit pas la nature
   d'information demandée est insuffisant.
5. Ne confonds pas :
   - existence et méthode d'obtention ;
   - possibilité et condition ;
   - utilisation et apprentissage ;
   - description et localisation ;
   - relation générale et valeur précise.
6. Vérifie toutes les contraintes explicites de la question : nombres, bornes,
   versions, générations, exclusions, classements et comparaisons.
7. Ne développe ni ne réinterprète les sigles, abréviations ou noms de version
   à partir de connaissances externes.

Retourne uniquement un objet JSON valide :

{
  "sufficient": true,
  "reason": "explication courte et factuelle"
}

ou

{
  "sufficient": false,
  "reason": "information précise manquante dans le contexte"
}
""".strip()


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Aucun objet JSON trouvé.")
        result = json.loads(match.group(0))
    if not isinstance(result, dict):
        raise ValueError("Le résultat doit être un objet JSON.")
    return result


def check_context_sufficiency(question: str, context: str) -> dict:
    start = time.perf_counter()

    if not context.strip():
        return {
            "sufficient": False,
            "reason": "Le contexte documentaire est vide.",
            "time": time.perf_counter() - start,
        }

    prompt = f"""
QUESTION
--------
{question}

CONTEXTE DOCUMENTAIRE
---------------------
{context}
""".strip()

    try:
        response = client.chat.completions.create(
            model=SUFFICIENCY_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": SUFFICIENCY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

        result = _extract_json(response.choices[0].message.content or "")
        sufficient = result.get("sufficient")
        reason = str(result.get("reason", "")).strip()

        if not isinstance(sufficient, bool):
            raise ValueError("'sufficient' doit être un booléen.")
        if not reason:
            raise ValueError("'reason' est vide.")

    except Exception as exc:
        sufficient = False
        reason = f"Échec du contrôle de suffisance : {exc}"

    return {
        "sufficient": sufficient,
        "reason": reason,
        "time": time.perf_counter() - start,
    }
