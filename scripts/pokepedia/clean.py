import json
import re
import time
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

RAW_DIR = Path("pokemon/corpus/raw")
OUTPUT_DIR = Path("pokemon/corpus/cleaned")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# UTILITAIRES
# ============================================================

def normalize(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines)

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)

    return text.strip()


def find_balanced_template_end(text: str, start: int):
    """
    start pointe sur '{{'.

    Retourne l'index situé juste après le '}}' correspondant.
    Ne modifie jamais le texte.
    """

    depth = 0
    i = start

    while i < len(text) - 1:
        pair = text[i:i + 2]

        if pair == "{{":
            depth += 1
            i += 2
            continue

        if pair == "}}":
            depth -= 1
            i += 2

            if depth == 0:
                return i

            continue

        i += 1

    return None


def replace_named_templates(text, marker, parser):
    """
    Cherche uniquement les templates commençant par marker.

    IMPORTANT :
    les autres templates ne sont absolument pas touchés.
    """

    search_from = 0

    while True:
        start = text.find(marker, search_from)

        if start == -1:
            break

        end = find_balanced_template_end(text, start)

        if end is None:
            print(f"  ATTENTION : template non fermé : {marker}")
            search_from = start + len(marker)
            continue

        template = text[start + 2:end - 2]

        replacement = parser(template)

        # Fail-safe :
        # None = on ne touche pas au template.
        if replacement is None:
            search_from = end
            continue

        text = text[:start] + replacement + text[end:]

        search_from = start + len(replacement)

    return text


# ============================================================
# NETTOYAGE INLINE
# ============================================================

def clean_inline(text: str) -> str:

    # {{!}} = caractère |
    text = text.replace("{{!}}", "|")

    # Liens avec label
    # [[Poison (type)|Poison]] -> Poison
    text = re.sub(
        r"\[\[[^|\]]+\|([^\]]+)\]\]",
        r"\1",
        text,
    )

    # Liens simples
    # [[Bulbizarre]] -> Bulbizarre
    text = re.sub(
        r"\[\[([^\]]+)\]\]",
        r"\1",
        text,
    )

    # Gras / italique
    text = text.replace("'''''", "")
    text = text.replace("'''", "")
    text = text.replace("''", "")

    # HTML
    text = re.sub(
        r"<br\s*/?>",
        ", ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"<sup>(.*?)</sup>", r"\1", text)
    text = re.sub(r"<sub>(.*?)</sub>", r"\1", text)

    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


# ============================================================
# INFOBOX
# ============================================================

INFOBOX_FIELDS = {
    "nom": "Nom",
    "nom-japonais": "Nom japonais",
    "nom-déposé": "Nom déposé",
    "nom-anglais": "Nom anglais",
    "ndex": "Numéro national",
    "type1": "Type 1",
    "type2": "Type 2",
    "catégorie": "Catégorie",
    "taille": "Taille",
    "poids": "Poids",
    "talents": "Talents",
    "groupeoeuf1": "Groupe œuf 1",
    "groupeoeuf2": "Groupe œuf 2",
    "éclosion": "Éclosion",
    "effortval": "EV donné",
    "expval": "Expérience donnée",
    "expmax": "Expérience maximale",
    "fmratio": "Ratio femelle",
    "couleur": "Couleur",
    "captureval": "Taux de capture",
}


def parse_infobox(template: str):

    result = [
        "## Informations générales",
        "",
    ]

    found = 0

    for line in template.splitlines():
        line = line.strip()

        if not line.startswith("|"):
            continue

        line = line[1:]

        if "=" not in line:
            continue

        key, value = line.split("=", 1)

        key = key.strip()
        value = value.strip()

        if key not in INFOBOX_FIELDS or not value:
            continue

        if key == "talents":
            value = value.replace(
                "/[[talent caché]]",
                " (talent caché)",
            )

            value = value.replace("//", ", ")
            value = value.replace("{{!}}", "|")

            # Les liens MediaWiki imbriqués peuvent avoir été partiellement
            # aplatis dans certains paramètres d'infobox.
            # "Engrais (talent)|Engrais" -> "Engrais"
            value = re.sub(
                r"([^,]+?)\s*\([^()]+\)\|([^,]+)",
                lambda m: m.group(2).strip(),
                value,
            )

        value = clean_inline(value)

        result.append(
            f"- {INFOBOX_FIELDS[key]} : {value}"
        )

        found += 1

    if found == 0:
        return None

    return "\n".join(result)


# ============================================================
# MESURES
# ============================================================

def parse_mesures(template: str):

    taille = re.search(
        r"\|\s*taille\s*=\s*([^|\n}]+)",
        template,
    )

    poids = re.search(
        r"\|\s*poids\s*=\s*([^|\n}]+)",
        template,
    )

    result = []

    if taille:
        result.append(
            f"- Taille : {clean_inline(taille.group(1))} m"
        )

    if poids:
        result.append(
            f"- Poids : {clean_inline(poids.group(1))} kg"
        )

    if not result:
        return None

    return "\n".join(result)


# ============================================================
# STATISTIQUES
# ============================================================

STAT_FIELDS = {
    "PV": "PV",
    "attaque": "Attaque",
    "defense": "Défense",
    "atq-spc": "Attaque Spéciale",
    "def-spc": "Défense Spéciale",
    "vitesse": "Vitesse",
    "special": "Spécial",
}


def parse_statistics(template: str):

    result = [
        "### Statistiques",
        "",
    ]

    found = 0

    for key, label in STAT_FIELDS.items():

        pattern = (
            r"\|\s*"
            + re.escape(key)
            + r"\s*=\s*([^|\n}]+)"
        )

        match = re.search(
            pattern,
            template,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        value = clean_inline(match.group(1))

        result.append(
            f"- {label} : {value}"
        )

        found += 1

    if found == 0:
        return None

    return "\n".join(result)


# ============================================================
# APPRENTISSAGE
# ============================================================

def parse_apprentissage(template: str):
    """
    IMPORTANT :
    on ne demande aucun résultat au module Lua.

    On récupère uniquement les informations réellement écrites
    dans le template.
    """

    lines = template.splitlines()

    if not lines:
        return None

    result = []

    for line in lines[1:]:

        line = line.strip()

        if not line:
            continue

        line = line.lstrip("|").strip()

        # Paramètres techniques simples
        if re.match(
            r"^(type|type2|génération|jeux|méthodes|méthode)=",
            line,
            flags=re.IGNORECASE,
        ):
            continue

        # Les données d'apprentissage utilisent principalement /
        if "/" in line:
            result.append(
                "- " + clean_inline(line)
            )

    if not result:
        # Surtout ne pas supprimer si on n'a rien compris.
        return None

    return "\n".join(result)


# ============================================================
# ÉVOLUTIONS
# ============================================================

def parse_evolution_simple(template: str):

    content = clean_inline(template)

    match = re.search(
        r"TableauEvolutionSimple"
        r"\|([^|]+)"
        r"\|([^|}]+)",
        content,
    )

    if not match:
        return None

    condition = match.group(1).strip()
    pokemon = match.group(2).strip()

    return f"- {condition} → {pokemon}"


def parse_evolution_condition(template: str):

    content = clean_inline(template)

    match = re.search(
        r"TableauEvolutionConditionBranche/\d+"
        r"\|([^|}]+)",
        content,
    )

    if not match:
        return None

    return (
        "- Condition : "
        + match.group(1).strip()
    )


def parse_evolution_branch(template: str):

    content = clean_inline(template)

    match = re.search(
        r"TableauEvolutionBranche/\d+"
        r"\|([^|}]+)",
        content,
    )

    if not match:
        return None

    return (
        "- Évolution : "
        + match.group(1).strip()
    )


# ============================================================
# TEMPLATES DYNAMIQUES
# ============================================================

def remove_dynamic_template(template: str):
    """
    Template dont le résultat dépend d'un module Lua et dont
    les données ne sont PAS présentes dans le wikitexte.

    On peut le supprimer en sécurité puisqu'on cible son nom
    précisément.
    """

    return ""


# ============================================================
# PETITS TEMPLATES INLINE
# ============================================================

def replace_game_templates(text: str) -> str:
    """
    {{Jeu|EV}} -> EV
    """

    pattern = re.compile(
        r"\{\{Jeu\|([^{}|]+)(?:\|[^{}]*)?\}\}",
        flags=re.IGNORECASE,
    )

    return pattern.sub(
        lambda m: clean_inline(m.group(1)),
        text,
    )


def replace_simple_named_template(text, name):
    """
    {{ps|Professeur Chen}} -> Professeur Chen

    À utiliser uniquement sur les templates dont on connaît
    précisément la structure.
    """

    pattern = re.compile(
        r"\{\{"
        + re.escape(name)
        + r"\|([^{}|]+)(?:\|[^{}]*)?\}\}",
        flags=re.IGNORECASE,
    )

    return pattern.sub(
        lambda m: clean_inline(m.group(1)),
        text,
    )


# ============================================================
# TEMPLATES RÉSIDUELS — V3.2
# ============================================================

def parse_article_principal(template: str):
    """
    {{Article principal|...}} -> Article principal : ...

    Conserve uniquement une information explicitement présente.
    """
    parts = template.split("|", 1)

    if len(parts) != 2:
        return None

    value = clean_inline(parts[1])

    if not value:
        return None

    return f"Article principal : {value}"


def parse_liste_cartes(template: str):
    """
    Gère les variantes mono-ligne et multi-lignes :

    {{Liste des cartes d'un Pokémon|Bulbizarre|première=...}}

    Si aucun contenu utile n'est compris, le template est conservé
    grâce au fail-safe de replace_named_templates().
    """
    # Découpage simple acceptable ici car ce template résiduel est déjà
    # isolé par le parseur équilibré replace_named_templates().
    parts = [part.strip() for part in template.split("|")]

    if not parts:
        return None

    positional = []
    named = {}

    for part in parts[1:]:
        if not part:
            continue

        if "=" in part:
            key, value = part.split("=", 1)
            key = key.strip().lower()
            value = clean_inline(value.strip())

            if value:
                named[key] = value
        else:
            value = clean_inline(part)
            if value:
                positional.append(value)

    result = []

    pokemon = named.get("nom")
    if not pokemon and positional:
        pokemon = positional[0]

    if pokemon:
        result.append(f"- Pokémon : {pokemon}")

    premiere = named.get("première") or named.get("premiere")
    if premiere:
        result.append(f"- Première carte : {premiere}")

    if not result:
        return None

    return "\n".join(result)


def replace_pagename(text: str, page_name: str) -> str:
    """{{PAGENAME}} -> nom réel de la page."""
    return re.sub(
        r"\{\{\s*PAGENAME\s*\}\}",
        page_name,
        text,
        flags=re.IGNORECASE,
    )


def clean_pms_template(text: str) -> str:
    """
    Deux cas :
    {{PMS}} -> PMS
    {{PMS|texte}} -> texte

    On ne supprime donc jamais silencieusement la mention.
    """
    text = re.sub(
        r"\{\{\s*PMS\s*\}\}",
        "PMS",
        text,
        flags=re.IGNORECASE,
    )

    pattern = re.compile(
        r"\{\{\s*PMS\|([^{}|]+)(?:\|[^{}]*)?\}\}",
        flags=re.IGNORECASE,
    )

    return pattern.sub(
        lambda m: clean_inline(m.group(1)),
        text,
    )


def remove_lst_imagerie(text: str) -> str:
    """
    Supprime uniquement les transclusions #lst ciblant /Imagerie.
    """
    pattern = re.compile(
        r"\{\{#lst:[^{}|]+/Imagerie(?:\|[^{}]*)?\}\}",
        flags=re.IGNORECASE,
    )
    return pattern.sub("", text)


def remove_gallery_blocks(text: str) -> str:
    """
    Supprime les blocs <gallery>...</gallery> avec limites explicites.
    Contrairement à l'ancien problème <ref>, les deux balises sont
    directement vérifiables et ce contenu est purement visuel.
    """
    return re.sub(
        r"<gallery\b[^>]*>.*?</gallery\s*>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )


def remove_file_markup_lines(text: str) -> str:
    """
    Nettoie le bruit visuel restant sans regex multi-ligne agressive.

    - lignes de type thumb|left|...
    - lignes de type Fichier:...
    - occurrences inline simples Fichier:nom.ext

    On travaille ligne par ligne afin de ne jamais avaler une section.
    """
    output = []

    for line in text.splitlines():
        stripped = line.strip()

        # Après certains nettoyages MediaWiki, une image peut rester sous
        # la forme "thumb|..." OU "|thumb|...".
        if re.match(
            r"^\|?\s*thumb\s*\|",
            stripped,
            flags=re.IGNORECASE,
        ):
            continue

        if re.match(
            r"^(?:Fichier\s*:|Image\s*:)",
            stripped,
            flags=re.IGNORECASE,
        ):
            continue

        # Cas inline observé :
        # "... : Fichier:Sprite 0001 SMM.png"
        line = re.sub(
            r"\s*Fichier:[^|\n]+?\.(?:png|jpe?g|gif|svg|webp)\b",
            "",
            line,
            flags=re.IGNORECASE,
        )

        line = re.sub(
            r"\s*Image:[^|\n]+?\.(?:png|jpe?g|gif|svg|webp)\b",
            "",
            line,
            flags=re.IGNORECASE,
        )

        output.append(line)

    return "\n".join(output)


def remove_interwiki_lines(text: str) -> str:
    """
    Retire uniquement les liens interwiki occupant une ligne entière :
    de:..., en:..., es:..., etc.

    Une phrase normale contenant "en:" n'est donc jamais supprimée.
    """
    return re.sub(
        r"^\s*(?:de|en|es|it|ja|zh|ko|pt|ru|pl|nl|sv|fi|no|da|cs|hu):[^\n]*$",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )


def remove_empty_sections(text: str) -> str:
    """
    Supprime les titres Markdown qui n'ont aucun contenu avant le titre
    suivant de niveau égal ou supérieur.

    Plusieurs passes permettent de retirer un parent devenu vide après
    suppression de ses sous-sections vides.
    """
    for _ in range(4):
        lines = text.splitlines()
        keep = [True] * len(lines)
        changed = False

        for i, line in enumerate(lines):
            match = re.match(r"^(#{2,6})\s+\S", line)
            if not match:
                continue

            level = len(match.group(1))
            j = i + 1
            has_content = False

            while j < len(lines):
                next_heading = re.match(r"^(#{1,6})\s+\S", lines[j])

                if next_heading and len(next_heading.group(1)) <= level:
                    break

                if lines[j].strip() and not next_heading:
                    has_content = True
                    break

                # Un sous-titre seul ne suffit pas à rendre la section utile.
                j += 1

            if not has_content:
                # Ne supprime que si tout ce qui précède le prochain titre
                # égal/supérieur est vide ou composé de titres eux-mêmes vides.
                segment_has_text = False
                k = i + 1
                while k < j:
                    if lines[k].strip() and not re.match(r"^#{1,6}\s+", lines[k]):
                        segment_has_text = True
                        break
                    k += 1

                if not segment_has_text:
                    keep[i] = False
                    changed = True

        if not changed:
            break

        text = "\n".join(
            line for idx, line in enumerate(lines) if keep[idx]
        )

    return text


# ============================================================
# SUPPRESSION DE TEMPLATES PUREMENT VISUELS
# ============================================================

def remove_exact_visual_templates(text: str) -> str:
    """
    LISTE BLANCHE.

    On ne supprime que les templates explicitement considérés
    comme navigation/présentation.
    """

    prefixes = [
        "{{Ruban Pokémon",
        "{{Renvoi imagerie",
        "{{TableauEvolutionHaut",
        "{{TableauEvolutionBas",
        "{{Générations",
        "{{Pokémon de départ",
        "{{Bandeau Pokédex",
    ]

    for marker in prefixes:

        search_from = 0

        while True:

            start = text.find(marker, search_from)

            if start == -1:
                break

            end = find_balanced_template_end(
                text,
                start,
            )

            if end is None:
                search_from = start + len(marker)
                continue

            text = text[:start] + text[end:]

            search_from = start

    return text


# ============================================================
# BRUIT MEDIAWIKI
# ============================================================

def remove_noise(text: str) -> str:
    """
    Nettoyage conservateur du wikitexte.

    Principe :
    aucune opération de cette fonction ne doit pouvoir supprimer
    une grande portion de l'article à cause d'une structure mal fermée.
    """

    original_size = len(text)

    # --------------------------------------------------------
    # 1. Commentaires HTML
    # --------------------------------------------------------

    text = re.sub(
        r"<!--.*?-->",
        "",
        text,
        flags=re.DOTALL,
    )

    # --------------------------------------------------------
    # 2. Balises <ref>
    #
    # IMPORTANT :
    # on conserve le CONTENU des références.
    #
    # <ref>texte</ref>
    # devient :
    # texte
    #
    # Cela évite qu'un <ref> mal formé engloutisse 20 000
    # caractères.
    # --------------------------------------------------------

    text = re.sub(
        r"<ref\b[^>]*>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"</ref\s*>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Référence réellement autofermante :
    # <ref name="foo" />
    #
    # Elle ne contient aucune information textuelle.
    text = re.sub(
        r"<ref\b[^>]*/\s*>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # --------------------------------------------------------
    # 3. <references/>
    # --------------------------------------------------------

    text = re.sub(
        r"<references\s*/\s*>",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # --------------------------------------------------------
    # 4. Gallery
    #
    # On la conserve pour l'instant.
    # Les images ne nous intéressent pas pour le RAG, mais on
    # nettoiera cela plus tard avec une méthode sûre.
    # --------------------------------------------------------

    # RIEN ICI volontairement.

    # --------------------------------------------------------
    # 5. Section markers
    # --------------------------------------------------------

    text = re.sub(
        r'<section\s+(?:begin|end)="[^"]+"\s*/>',
        "",
        text,
        flags=re.IGNORECASE,
    )

    # --------------------------------------------------------
    # 6. Catégories
    # --------------------------------------------------------

    text = re.sub(
        r"^\s*\[\[Catégorie:[^\n]+\]\]\s*$",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )

    removed = original_size - len(text)

    print(
        f"  remove_noise : "
        f"{original_size:,} -> {len(text):,} "
        f"({removed:,} caractères supprimés)"
    )

    return text
# ============================================================
# TITRES
# ============================================================

def convert_headings(text: str) -> str:

    def replacement(match):

        equals = match.group(1)
        title = clean_inline(match.group(2))

        level = len(equals)

        return (
            "#" * min(level, 6)
            + " "
            + title
        )

    return re.sub(
        r"^(={2,6})\s*(.*?)\s*\1$",
        replacement,
        text,
        flags=re.MULTILINE,
    )


# ============================================================
# LISTES
# ============================================================

def convert_lists(text: str) -> str:

    output = []

    for line in text.splitlines():

        stripped = line.lstrip()

        if stripped.startswith("*"):

            count = (
                len(stripped)
                - len(stripped.lstrip("*"))
            )

            content = stripped[count:].strip()

            indent = "  " * (count - 1)

            output.append(
                f"{indent}- {content}"
            )

        else:
            output.append(line)

    return "\n".join(output)


# ============================================================
# NETTOYAGE INLINE GLOBAL
# ============================================================

def clean_remaining_inline_wiki(text: str) -> str:

    # Liens [[A|B]]
    text = re.sub(
        r"\[\[[^|\]]+\|([^\]]+)\]\]",
        r"\1",
        text,
    )

    # Liens [[A]]
    text = re.sub(
        r"\[\[([^\]]+)\]\]",
        r"\1",
        text,
    )

    # Gras / italique
    text = text.replace("'''''", "")
    text = text.replace("'''", "")
    text = text.replace("''", "")

    # HTML courant
    text = re.sub(
        r"<br\s*/?>",
        ", ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"<sup>(.*?)</sup>",
        r"\1",
        text,
    )

    text = re.sub(
        r"<sub>(.*?)</sub>",
        r"\1",
        text,
    )

    return text


# ============================================================
# TEMPLATE RESIDUAL REPORT
# ============================================================

def report_remaining_markup(text: str):
    """
    Rapport V3.3 : détecte du markup résiduel sans supprimer de contenu
    et sans bloquer l'écriture.
    """
    checks = {
        "templates {{...}}": r"\{\{",
        "liens wiki [[...]]": r"\[\[",
        "thumb": r"(?im)^\s*\|?\s*thumb\s*\|",
        "gallery": r"(?i)<gallery\b",
        "Fichier:": r"(?i)Fichier\s*:",
        "Image:": r"(?i)Image\s*:",
        "interwiki": r"(?im)^\s*(?:de|en|es|it|ja|zh|ko|pt|ru|pl|nl|sv|fi|no|da|cs|hu):",
    }

    found = []

    for label, pattern in checks.items():
        if re.search(pattern, text):
            found.append(label)

    print()
    print("Markup résiduel après nettoyage :")

    if not found:
        print("  Aucun résidu détecté")
    else:
        for label in found:
            print(f"  - {label}")


def report_remaining_templates(text: str):
    """
    Ne supprime RIEN.

    Sert uniquement à savoir quels templates il faudra gérer
    plus tard.
    """

    names = []

    for match in re.finditer(
        r"\{\{([^{}\n|]+)",
        text,
    ):
        name = match.group(1).strip()

        if name and name not in names:
            names.append(name)

    print()
    print("Templates restant après nettoyage :")

    if not names:
        print("  Aucun")
        return

    for name in names[:30]:
        print(f"  - {name}")

    if len(names) > 30:
        print(
            f"  ... +{len(names) - 30} autres"
        )


# ============================================================
# VALIDATION STRUCTURELLE
# ============================================================

IMPORTANT_SECTIONS = [
    "À propos du Pokémon",
    "Évolution",
    "Capacités apprises",
    "Sensibilités",
    "Stratégie",
    "Apparitions",
]


IMPORTANT_FACTS = [
    "Bulbizarre",
    "Plante",
    "Poison",
    "Herbizarre",
    "Florizarre",
    "Vampigraine",
    "Lance-Soleil",
]


def validate(raw: str, cleaned: str):

    print()
    print("=" * 70)
    print("VALIDATION")
    print("=" * 70)

    errors = []
    warnings = []

    # --------------------------------------------------------
    # Sections présentes dans le brut
    # --------------------------------------------------------

    for section in IMPORTANT_SECTIONS:

        raw_has = (
            section.lower()
            in raw.lower()
        )

        cleaned_has = (
            section.lower()
            in cleaned.lower()
        )

        if raw_has and cleaned_has:
            print(
                f"  OK       section : {section}"
            )

        elif raw_has and not cleaned_has:
            print(
                f"  ERREUR   section perdue : {section}"
            )

            errors.append(
                f"Section perdue : {section}"
            )

    # --------------------------------------------------------
    # Faits essentiels
    # --------------------------------------------------------

    for fact in IMPORTANT_FACTS:

        if fact.lower() in cleaned.lower():

            print(
                f"  OK       contenu : {fact}"
            )

        else:

            print(
                f"  ERREUR   contenu absent : {fact}"
            )

            errors.append(
                f"Contenu absent : {fact}"
            )

    # --------------------------------------------------------
    # Statistiques
    # --------------------------------------------------------

    stats = [
        "PV",
        "Attaque",
        "Défense",
        "Vitesse",
    ]

    for stat in stats:

        if stat.lower() not in cleaned.lower():

            warnings.append(
                f"Statistique potentiellement absente : {stat}"
            )

    # --------------------------------------------------------
    # Ratio
    # --------------------------------------------------------

    ratio = (
        len(cleaned)
        / max(len(raw), 1)
    )

    print()
    print(
        f"  Ratio de conservation : {ratio:.1%}"
    )

    # Cette limite est volontairement assez basse :
    # le MediaWiki brut contient beaucoup de markup.
    if ratio < 0.35:

        errors.append(
            "Ratio de conservation inférieur à 35 %"
        )

    elif ratio < 0.50:

        warnings.append(
            "Ratio de conservation inférieur à 50 %"
        )

    # --------------------------------------------------------
    # Résumé
    # --------------------------------------------------------

    print()

    for warning in warnings:
        print(
            f"  WARNING  {warning}"
        )

    for error in errors:
        print(
            f"  ERROR    {error}"
        )

    return errors, warnings


# ============================================================
# HEADER
# ============================================================

def build_header(article: dict) -> str:

    return f"""# {article["title"]}

> Source : {article["source"]}  
> Page ID : {article["page_id"]}  
> Revision ID : {article["revision_id"]}  
> Revision date : {article["revision_timestamp"]}  
> Source URL : {article["source_url"]}

---
"""


# ============================================================
# PIPELINE
# ============================================================

def clean_wikitext(raw: str, page_name: str):

    timings = {}
    content = raw

    debug_state("RAW", content)

    # 1
    start = time.perf_counter()
    content = remove_noise(content)
    timings["bruit"] = time.perf_counter() - start
    debug_state("remove_noise", content)

    # 2
    start = time.perf_counter()
    content = replace_named_templates(
        content,
        "{{#invoke:Infobox Pokémon|infobox",
        parse_infobox,
    )
    timings["infobox"] = time.perf_counter() - start
    debug_state("infobox", content)

    # 3
    start = time.perf_counter()
    content = replace_named_templates(
        content,
        "{{Mesures",
        parse_mesures,
    )
    timings["mesures"] = time.perf_counter() - start
    debug_state("mesures", content)

    # 4
    start = time.perf_counter()
    content = replace_named_templates(
        content,
        "{{Statistiques",
        parse_statistics,
    )
    timings["statistiques"] = time.perf_counter() - start
    debug_state("statistiques", content)

    # 5
    start = time.perf_counter()
    content = replace_named_templates(
        content,
        "{{#invoke:Apprentissage",
        parse_apprentissage,
    )
    timings["apprentissage"] = time.perf_counter() - start
    debug_state("apprentissage", content)

    # 6
    start = time.perf_counter()

    content = replace_named_templates(
        content,
        "{{TableauEvolutionSimple",
        parse_evolution_simple,
    )

    content = replace_named_templates(
        content,
        "{{TableauEvolutionConditionBranche/",
        parse_evolution_condition,
    )

    content = replace_named_templates(
        content,
        "{{TableauEvolutionBranche/",
        parse_evolution_branch,
    )

    timings["evolutions"] = time.perf_counter() - start
    debug_state("evolutions", content)

    # 7
    start = time.perf_counter()

    content = replace_named_templates(
        content,
        "{{#invoke:Localisations",
        remove_dynamic_template,
    )

    content = replace_named_templates(
        content,
        "{{#invoke:Sensibilités",
        remove_dynamic_template,
    )

    timings["dynamiques"] = time.perf_counter() - start
    debug_state("dynamiques", content)

    # 8
    start = time.perf_counter()

    content = replace_game_templates(content)
    content = replace_simple_named_template(content, "ps")
    content = replace_simple_named_template(content, "PCap")

    timings["templates_simples"] = time.perf_counter() - start
    debug_state("templates simples", content)

    # 8.1
    # Templates résiduels connus
    start = time.perf_counter()

    content = replace_named_templates(
        content,
        "{{Article principal",
        parse_article_principal,
    )

    content = replace_named_templates(
        content,
        "{{Liste des cartes d'un Pokémon",
        parse_liste_cartes,
    )

    content = replace_pagename(
        content,
        page_name,
    )

    content = clean_pms_template(content)
    content = remove_lst_imagerie(content)
    content = remove_gallery_blocks(content)
    content = remove_file_markup_lines(content)
    content = remove_interwiki_lines(content)

    timings["residuels"] = time.perf_counter() - start
    debug_state("templates residuels", content)

    # 9
    start = time.perf_counter()

    content = remove_exact_visual_templates(content)

    timings["visuels"] = time.perf_counter() - start
    debug_state("visuels", content)

    # 10
    start = time.perf_counter()

    content = convert_headings(content)
    content = remove_empty_sections(content)

    timings["titres"] = time.perf_counter() - start
    debug_state("titres", content)

    # 11
    start = time.perf_counter()

    content = convert_lists(content)

    timings["listes"] = time.perf_counter() - start
    debug_state("listes", content)

    # 12
    start = time.perf_counter()

    content = clean_remaining_inline_wiki(content)

    # V3.3 — nettoyage final de markup résiduel.
    # Ces opérations sont volontairement faites APRÈS le nettoyage inline,
    # car certaines syntaxes ne deviennent reconnaissables qu'à ce stade.
    content = remove_file_markup_lines(content)
    content = remove_interwiki_lines(content)

    # Liens MediaWiki vides laissés après suppression d'une image :
    # [[Fichier:...]] -> [[]] -> supprimé ici.
    content = re.sub(r"\[\[\s*\]\]", "", content)

    # Même protection pour un lien vide simple accidentel.
    content = re.sub(r"\[\s*\]", "", content)

    content = normalize(content)

    timings["inline"] = time.perf_counter() - start
    debug_state("inline final", content)

    return content, timings
def debug_state(step_name: str, text: str):
    probes = [
        "Capacités apprises",
        "Sensibilités",
        "Stratégie",
        "Apparitions",
        "Lance-Soleil",
        "Statistiques",
    ]

    print()
    print(
        f"[DEBUG] {step_name:<25} "
        f"{len(text):>7,} caractères"
    )

    for probe in probes:
        present = probe.lower() in text.lower()

        print(
            f"        {'OK' if present else 'PERDU':<5} "
            f"{probe}"
        )
# ============================================================
# MAIN
# ============================================================

def validate_cleaned_article(raw: str, cleaned: str, article: dict) -> dict:
    """Validation générique pour toutes les pages Pokémon."""
    errors = []
    warnings = []

    title = str(article.get("title", "")).strip()
    raw_size = len(raw)
    cleaned_size = len(cleaned)
    ratio = cleaned_size / raw_size if raw_size else 0.0

    if not title:
        errors.append("Titre absent.")
    elif title.casefold() not in cleaned.casefold():
        errors.append(f"Le titre « {title} » a disparu du document.")

    if not raw:
        errors.append("Wikitexte source vide.")

    if cleaned_size < 200:
        errors.append(f"Document nettoyé trop court : {cleaned_size:,} caractères.")

    if raw_size and ratio < 0.35:
        errors.append(f"Ratio de conservation trop faible : {ratio:.1%}.")
    elif raw_size and ratio < 0.50:
        warnings.append(f"Ratio de conservation faible : {ratio:.1%}.")

    if not re.search(r"(?m)^#\s+\S", cleaned):
        errors.append("Titre Markdown principal absent.")

    headings = re.findall(r"(?m)^#{2,6}\s+\S.*$", cleaned)
    if not headings:
        errors.append("Aucune section Markdown détectée.")

    for section in (
        "Informations générales",
        "À propos du Pokémon",
        "Capacités apprises",
        "Statistiques",
    ):
        if section.casefold() not in cleaned.casefold():
            warnings.append(f"Section générique non détectée : {section}")

    markup_checks = {
        "template {{...}}": r"\{\{",
        "lien wiki [[...]]": r"\[\[",
        "gallery": r"(?i)<gallery\b",
        "thumb": r"(?im)^\s*\|?\s*thumb\s*\|",
        "Fichier:": r"(?i)Fichier\s*:",
        "Image:": r"(?i)Image\s*:",
        "interwiki": r"(?im)^\s*(?:de|en|es|it|ja|zh|ko|pt|ru|pl|nl|sv|fi|no|da|cs|hu):",
    }

    residual = [name for name, pattern in markup_checks.items()
                if re.search(pattern, cleaned)]
    if residual:
        warnings.append("Markup résiduel : " + ", ".join(residual))

    if raw_size and ratio > 1.20:
        warnings.append(f"Document nettoyé plus long que la source : {ratio:.1%}.")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "ratio": ratio,
        "raw_size": raw_size,
        "cleaned_size": cleaned_size,
    }


def process_json_file(input_file: Path, index: int, total: int) -> dict:
    total_start = time.perf_counter()

    print()
    print("=" * 78)
    print(f"[{index}/{total}] {input_file.name}")
    print("=" * 78)

    try:
        start = time.perf_counter()
        with input_file.open("r", encoding="utf-8") as f:
            article = json.load(f)
        read_time = time.perf_counter() - start

        title = str(article.get("title", input_file.stem))
        raw = article.get("content")
        if not isinstance(raw, str):
            raise RuntimeError("Champ 'content' absent ou non textuel.")

        cleaned, timings = clean_wikitext(raw, title)

        header = (
            f"# {title}\n\n"
            f"> Source : {article.get('source', 'Poképédia')}  \n"
            f"> Page ID : {article.get('page_id', '')}  \n"
            f"> Revision ID : {article.get('revision_id', '')}  \n"
            f"> Revision date : {article.get('revision_timestamp', '')}  \n"
            f"> Source URL : {article.get('source_url', '')}\n\n"
            "---\n\n"
        )

        final_text = normalize(header + cleaned)
        validation = validate_cleaned_article(raw, final_text, article)

        output_file = OUTPUT_DIR / f"{input_file.stem}.md"
        write_time = 0.0

        if validation["valid"]:
            start = time.perf_counter()
            tmp = output_file.with_suffix(".md.tmp")
            tmp.write_text(final_text, encoding="utf-8")
            tmp.replace(output_file)
            write_time = time.perf_counter() - start
            status = "WARNING" if validation["warnings"] else "OK"
        else:
            status = "ERROR"

        elapsed = time.perf_counter() - total_start

        print(f"Titre              : {title}")
        print(f"Raw                : {len(raw):,} caractères")
        print(f"Clean              : {len(final_text):,} caractères")
        print(f"Ratio conservation : {validation['ratio']:.1%}")
        print(f"Statut             : {status}")

        for warning in validation["warnings"]:
            print(f"WARNING            : {warning}")
        for error in validation["errors"]:
            print(f"ERREUR             : {error}")

        print("Timings :")
        print(f"  lecture_json     : {read_time:.6f} s")
        for name, value in timings.items():
            print(f"  {name:<16} : {value:.6f} s")
        print(f"  écriture         : {write_time:.6f} s")
        print(f"  total_fichier    : {elapsed:.6f} s")

        return {
            "file": input_file.name,
            "title": title,
            "status": status,
            "raw_size": len(raw),
            "cleaned_size": len(final_text),
            "ratio": validation["ratio"],
            "elapsed": elapsed,
            "warnings": validation["warnings"],
            "errors": validation["errors"],
        }

    except Exception as exc:
        elapsed = time.perf_counter() - total_start
        error = f"{type(exc).__name__}: {exc}"
        print(f"ÉCHEC : {error}")
        return {
            "file": input_file.name,
            "title": input_file.stem,
            "status": "ERROR",
            "raw_size": 0,
            "cleaned_size": 0,
            "ratio": 0.0,
            "elapsed": elapsed,
            "warnings": [],
            "errors": [error],
        }


def print_batch_summary(results: list[dict], total_elapsed: float) -> None:
    print()
    print("=" * 100)
    print("RAPPORT GLOBAL — CLEANER POKÉPÉDIA V4")
    print("=" * 100)
    print(f"{'FICHIER':<25} {'TITRE':<15} {'STATUT':<9} {'RAW':>9} {'CLEAN':>9} {'RATIO':>8} {'TEMPS':>9}")
    print("-" * 100)

    for r in results:
        title = r["title"] if len(r["title"]) <= 14 else r["title"][:13] + "…"
        print(
            f"{r['file']:<25} {title:<15} {r['status']:<9} "
            f"{r['raw_size']:>9,} {r['cleaned_size']:>9,} "
            f"{r['ratio']:>7.1%} {r['elapsed']:>8.4f}s"
        )

    print("-" * 100)
    print(f"OK            : {sum(r['status'] == 'OK' for r in results)}")
    print(f"Warnings      : {sum(r['status'] == 'WARNING' for r in results)}")
    print(f"Échecs        : {sum(r['status'] == 'ERROR' for r in results)}")
    print(f"Total         : {len(results)}")
    print(f"Temps global  : {total_elapsed:.6f} s")

    if results:
        print(f"Temps moyen   : {sum(r['elapsed'] for r in results) / len(results):.6f} s / Pokémon")

    warned = [r for r in results if r["warnings"]]
    if warned:
        print("\nWARNINGS PAR PAGE :")
        for r in warned:
            print(f"\n- {r['title']} ({r['file']})")
            for w in r["warnings"]:
                print(f"    • {w}")

    failed = [r for r in results if r["errors"]]
    if failed:
        print("\nERREURS PAR PAGE :")
        for r in failed:
            print(f"\n- {r['title']} ({r['file']})")
            for e in r["errors"]:
                print(f"    • {e}")


def main():
    global_start = time.perf_counter()

    print("=" * 78)
    print("NETTOYAGE POKÉPÉDIA — PARSER PYTHON V4 — BATCH")
    print("=" * 78)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    input_files = sorted(RAW_DIR.glob("*.json"))

    print(f"Dossier source : {RAW_DIR}")
    print(f"Dossier sortie : {OUTPUT_DIR}")
    print(f"JSON trouvés   : {len(input_files)}")

    if not input_files:
        print("Aucun JSON trouvé.")
        raise SystemExit(1)

    results = [
        process_json_file(path, i, len(input_files))
        for i, path in enumerate(input_files, start=1)
    ]

    total_elapsed = time.perf_counter() - global_start
    print_batch_summary(results, total_elapsed)

    if any(r["status"] == "ERROR" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
