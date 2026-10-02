from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


REGION_FORMS = {
    "alola": "alola",
    "galar": "galar",
    "hisui": "hisui",
    "paldea": "paldea",
}

# Libellés de présentation ; les identifiants restent inchangés pour SQL/MCP.
VERSION_GROUP_NAMES_FR = {
    "red-blue":"Pokémon Rouge et Bleu", "yellow":"Pokémon Jaune",
    "gold-silver":"Pokémon Or et Argent", "crystal":"Pokémon Cristal",
    "ruby-sapphire":"Pokémon Rubis et Saphir", "emerald":"Pokémon Émeraude",
    "firered-leafgreen":"Pokémon Rouge Feu et Vert Feuille",
    "diamond-pearl":"Pokémon Diamant et Perle", "platinum":"Pokémon Platine",
    "heartgold-soulsilver":"Pokémon Or HeartGold et Argent SoulSilver",
    "black-white":"Pokémon Noir et Blanc", "black-2-white-2":"Pokémon Noir 2 et Blanc 2",
    "x-y":"Pokémon X et Y", "omega-ruby-alpha-sapphire":"Pokémon Rubis Oméga et Saphir Alpha",
    "sun-moon":"Pokémon Soleil et Lune", "ultra-sun-ultra-moon":"Pokémon Ultra-Soleil et Ultra-Lune",
    "lets-go-pikachu-lets-go-eevee":"Pokémon Let's Go Pikachu et Évoli",
    "sword-shield":"Pokémon Épée et Bouclier", "brilliant-diamond-shining-pearl":"Pokémon Diamant Étincelant et Perle Scintillante",
    "legends-arceus":"Légendes Pokémon : Arceus", "scarlet-violet":"Pokémon Écarlate et Violet",
    "champions":"Pokémon Champions",
}

BASE_STAT_NAMES = {
    "hp": "PV", "attack": "Attaque", "defense": "Défense",
    "special-attack": "Attaque Spéciale", "special-defense": "Défense Spéciale",
    "speed": "Vitesse", "base-stat-total": "Total des statistiques",
}

_TYPE_NAMES = {
    "normal":"Normal", "fire":"Feu", "water":"Eau", "electric":"Électrik",
    "grass":"Plante", "ice":"Glace", "fighting":"Combat", "poison":"Poison",
    "ground":"Sol", "flying":"Vol", "psychic":"Psy", "bug":"Insecte",
    "rock":"Roche", "ghost":"Spectre", "dragon":"Dragon", "dark":"Ténèbres",
    "steel":"Acier", "fairy":"Fée",
}

VERSION_ALIASES = {
    "rouge": "red-blue",
    "bleu": "red-blue",
    "rouge-et-bleu": "red-blue",
    "red": "red-blue",
    "blue": "red-blue",
    "red-and-blue": "red-blue",
    "diamant": "diamond-pearl",
    "perle": "diamond-pearl",
    "diamant-et-perle": "diamond-pearl",
    "diamond": "diamond-pearl",
    "pearl": "diamond-pearl",
    "diamond-and-pearl": "diamond-pearl",
    "soleil": "sun-moon",
    "lune": "sun-moon",
    "soleil-et-lune": "sun-moon",
    "sun": "sun-moon",
    "moon": "sun-moon",
    "sun-and-moon": "sun-moon",
    "epee": "sword-shield",
    "bouclier": "sword-shield",
    "epee-et-bouclier": "sword-shield",
    "sword": "sword-shield",
    "shield": "sword-shield",
    "sword-and-shield": "sword-shield",
    "ecarlate": "scarlet-violet",
    "violet": "scarlet-violet",
    "ecarlate-et-violet": "scarlet-violet",
    "scarlet": "scarlet-violet",
    "scarlet-and-violet": "scarlet-violet",
    "ev": "scarlet-violet",
}
# Les titres complets ont priorité sur les mots qu'ils contiennent.
VERSION_ALIASES.update({identifier: identifier for identifier in VERSION_GROUP_NAMES_FR})
# « champions » seul est un mot courant (champions d'arène) : seul le titre complet désigne le jeu.
del VERSION_ALIASES["champions"]
VERSION_ALIASES["pokemon-champions"] = "champions"
VERSION_ALIASES.update({
    "jaune":"yellow", "or-et-argent":"gold-silver", "cristal":"crystal",
    "rubis-et-saphir":"ruby-sapphire", "emeraude":"emerald", "platine":"platinum",
    "rouge-feu":"firered-leafgreen", "vert-feuille":"firered-leafgreen",
    "or-heartgold":"heartgold-soulsilver", "argent-soulsilver":"heartgold-soulsilver",
    "noir-et-blanc":"black-white", "noir-2":"black-2-white-2", "blanc-2":"black-2-white-2",
    "x-et-y":"x-y", "rubis-omega":"omega-ruby-alpha-sapphire",
    "saphir-alpha":"omega-ruby-alpha-sapphire", "ultra-soleil":"ultra-sun-ultra-moon",
    "ultra-lune":"ultra-sun-ultra-moon", "diamant-etincelant":"brilliant-diamond-shining-pearl",
    "perle-scintillante":"brilliant-diamond-shining-pearl", "legendes-pokemon-arceus":"legends-arceus",
})


@dataclass(frozen=True)
class ExplicitConstraints:
    form: str | None
    version_group: str | None
    version_ambiguous: bool
    explicit_game: bool
    level_bounds: tuple[int | None, int | None] | None
    level_explicit: bool
    form_ambiguous: bool = False
    national_number: int | None = None
    generation: int | None = None
    pokemon_types: tuple[str, ...] = ()
    type_match: str | None = None
    move_type: str | None = None
    damage_class: str | None = None
    power_bounds: tuple[int | None, int | None] | None = None
    legendary: bool | None = None
    mythical: bool | None = None
    ranking: dict | None = None
    form_category: str | None = None


def normalize(text: str | None) -> str:
    if text is None:
        return ""
    value = unicodedata.normalize("NFKD", str(text))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.casefold()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def extract_named_pokemon(question: str, catalogue: list[tuple[str, str, str | None]]) -> dict | None:
    """Mentions exactes avec frontières ; pas de nom déduit ou de matching flou."""
    text = "-" + normalize(question) + "-"
    hits = []
    for alias, species, form in catalogue:
        for match in re.finditer(rf"(?=-{re.escape(normalize(alias))}-)", text):
            hits.append((match.start(), match.start() + len(normalize(alias)) + 1, species, form))
    # Un alias complet de forme contient souvent aussi le nom de l'espèce.
    hits = [hit for hit in hits if not any(other[0] <= hit[0] and hit[1] <= other[1]
            and other[1]-other[0] > hit[1]-hit[0] for other in hits)]
    species = {hit[2] for hit in hits}
    if not species:
        return None
    forms = {hit[3] for hit in hits if hit[3]}
    if len(species) != 1 or len(forms) > 1:
        raise ValueError("Plusieurs Pokémon ou formes explicites : précisez une cible unique.")
    return {"pokemon":species.pop(), **({"form":forms.pop()} if forms else {})}


def is_named_identity_question(question: str) -> bool:
    text = normalize(question)
    return bool(re.search(r"(?:^|-)(?:numero-(?:national|du-pokedex)|(?:numero|identite)-.*pokedex)(?:-|$)", text))


def extract_generation(question: str) -> int | None:
    """Origine explicitement numérotée, pas la génération déduite d'un jeu."""
    text = normalize(question)
    ordinal = {"premiere":1, "deuxieme":2, "seconde":2, "troisieme":3,
               "quatrieme":4, "cinquieme":5, "sixieme":6, "septieme":7,
               "huitieme":8, "neuvieme":9}
    values = {int(value) for value in re.findall(
        r"(?:^|-)(?:generations?-|g-?)(\d+)(?=-|$)", text)}
    values.update(int(value) for value in re.findall(
        r"(?:^|-)(\d+)(?:e|eme|ere|re|ieme)?-?(?:generation|g)(?=-|$)", text))
    values.update(value for word, value in ordinal.items()
                  if re.search(rf"(?:^|-){word}-generation(?=-|$)", text))
    if not values:
        return None
    if re.search(r"g[ée]n[ée]rations?\s+\d+[.,]\d|\d+[.,]\d+(?:e|ème)?\s+g[ée]n[ée]ration", question, re.I):
        raise ValueError("Précisez une génération d'origine entière.")
    if re.search(r"g(?:énération|eneration)\s*-\s*\d", question, re.I):
        raise ValueError("Une génération d'origine doit être positive.")
    if len(values) != 1 or 0 in values or re.search(
            r"(?:avant|apres|depuis|hors|sauf|non)-(?:la-|les-|de-)?(?:generation|\d|"
            + "|".join(ordinal) + ")", text):
        raise ValueError("Génération multiple, négative ou intervalle non représentable.")
    if re.search(r"generations?-\d+-(?:ou|et|a)-\d+|\d+-(?:ou|et|a)-\d+(?:e|eme)?-generation", text):
        raise ValueError("Précisez une seule génération d'origine.")
    return values.pop()


def extract_classifications(question: str) -> dict[str, bool]:
    """Mentions positives indépendantes ; négations/alternatives non représentées."""
    text = normalize(question)
    token = r"(?:legendaires?|fabuleux|mythiques?)"
    if re.search(rf"(?:^|-)(?:non|pas|sans|sauf|hors|ni)-(?:les-|des-|de-)?{token}(?=-|$)|"
                 rf"{token}-(?:et-)?ou-{token}", text):
        raise ValueError("Classification ambiguë ou négative : précisez les filtres.")
    result = {}
    if re.search(r"(?:^|-)legendaires?(?=-|$)", text):
        result["legendary"] = True
    if re.search(r"(?:^|-)(?:fabuleux|mythiques?)(?=-|$)", text):
        result["mythical"] = True
    return result


def extract_move_constraints(question: str) -> dict:
    """Catégorie/type attachés à une capacité ; jamais une statistique spéciale."""
    text = normalize(question)
    # « meilleures Attaques Spéciales » désigne une statistique, pas une
    # catégorie de capacités. Masquer ces seuls motifs statistiques explicites.
    text = re.sub(r"(?:plus-(?:de|d)|moins-(?:de|d)|meilleur(?:e|s|es)?|pire(?:s)?)-"
                  r"attaques?-speciales?(?=-|$)", "", text)
    type_aliases = {normalize(alias): identifier for identifier, label in _TYPE_NAMES.items()
                    for alias in (identifier, label)}
    type_pattern = "|".join(sorted(type_aliases, key=len, reverse=True))
    category_pattern = r"physiques?|speciales?|de-statut|statut"
    noun = r"(?:capacites?|attaques?)"
    move_context = bool(re.search(r"(?:^|-)(?:capacites?|attaques|une-attaque)(?=-|$)", text)
                        or re.search(r"(?:^|-)(?:apprendre|apprend|apprennent)(?=-|$)", text))
    if not move_context:
        return {}
    categories = set()
    for match in re.finditer(rf"(?:^|-){noun}-(?:de-categorie-|de-)?(?:type-)?"
                            rf"(?:(?:{type_pattern})-)?({category_pattern})(?=-|$)", text):
        value = match.group(1)
        if re.match(rf"-(?:et|ou)-(?:{category_pattern})(?=-|$)", text[match.end():]):
            raise ValueError("Plusieurs catégories de capacités non représentables.")
        categories.add("physical" if value.startswith("physique") else
                       "special" if value.startswith("special") else "status")
    types = set()
    for match in re.finditer(
        rf"(?:^|-){noun}-(?:(?:{category_pattern})-)?(?:de-types?-|types?-)?"
        rf"({type_pattern})(?=-|$)", text):
        if re.match(rf"-(?:et|ou)-(?:{type_pattern})(?=-|$)", text[match.end():]):
            raise ValueError("Plusieurs types de capacités non représentables.")
        types.add(type_aliases[match.group(1)])
    if len(categories) > 1 or len(types) > 1 or re.search(
            rf"{noun}-(?:{category_pattern}|(?:de-type-)?{type_pattern})-(?:et|ou)-"
            rf"(?:{category_pattern}|{type_pattern})", text):
        raise ValueError("Plusieurs catégories ou types de capacités non représentables par un filtre unique.")
    if re.search(rf"(?:sans|sauf|non|pas)-(?:les-|de-)?{noun}-(?:{category_pattern}|de-type)", text):
        raise ValueError("Filtre négatif de capacité non représentable.")
    return {**({"damage_class":categories.pop()} if categories else {}),
            **({"move_type":types.pop()} if types else {})}


def names_learning_method(question: str) -> bool:
    """Vocabulaire volontairement large : au moindre mot de méthode, le choix du modèle est gardé."""
    return bool(re.search(
        r"(?:^|-)(?:c[ts]\d*|dt\d*|machines?|capsules?|disques?|niveaux?|montee|montant|monter|level-up|"
        r"o?eufs?|ufs?|reproduction|parents?|herit[a-z]*|tuteurs?|donneurs?|maitres?|methodes?|"
        r"comment|entrainement)(?=-|$)", normalize(question)))


def without_unnamed_learning_method(question: str, arguments: dict) -> dict:
    """Retire un learning_method que la question ne nomme pas ; ne restaure ni ne remplace rien."""
    if arguments.get("learning_method") is None or names_learning_method(question):
        return arguments
    return {key: value for key, value in arguments.items() if key != "learning_method"}


def extract_pokemon_types(question: str) -> dict:
    """Types littéraux d'un groupe de Pokémon, hors clauses de capacités."""
    text = normalize(question)
    aliases = {normalize(alias): identifier for identifier, label in _TYPE_NAMES.items()
               for alias in (identifier, label)}
    pattern = "|".join(sorted(aliases, key=len, reverse=True))
    # Retirer uniquement les expressions de type de capacité ; ne pas inférer
    # les types d'une espèce, d'une résistance ou de la réponse à « quels types ».
    text = re.sub(rf"(?:capacites?|attaques?)-(?:physiques?-|speciales?-)?"
                  rf"(?:de-types?-|types?-)?(?:{pattern})(?:-(?:physiques?|speciales?))?", "", text)
    sequences = []
    for match in re.finditer(rf"(?:^|-)(?:de-types?-|pokemons?-(?:(?:monotypes?|megas?)-)?)"
                             rf"({pattern})(?:-(et|ou)-({pattern})|-({pattern}))?(?=-|$)", text):
        if re.match(rf"-(?:et|ou)-(?:{pattern})(?=-|$)", text[match.end():]):
            raise ValueError("Plus de deux types explicitement demandés.")
        first, connector, second, slash_second = match.groups()
        values = (aliases[first],) + ((aliases[second or slash_second],) if second or slash_second else ())
        mode = "any" if connector == "ou" else "all"
        sequences.append((values, mode))
    if not sequences:
        return {}
    types = tuple(dict.fromkeys(value for values, _ in sequences for value in values))
    if len(types) > 2 or len(set(sequences)) > 1:
        raise ValueError("Combinaison de types ambiguë ou non représentable.")
    if re.search(r"(?:non|sans|sauf|hors|pas)-(?:les-|des-|de-)?(?:pokemons?-)?(?:de-)?types?-", text):
        raise ValueError("Type négatif non représentable.")
    mode = sequences[0][1]
    if re.search(r"(?:^|-)(?:monotypes?|uniquement-de-type|exactement-de-type)(?=-|$)", text):
        mode = "exact"
    return {"types":types, "type_match":mode}


def reconcile_search_args(question: str, arguments: dict) -> dict:
    """Invariants de recherche : classement explicite et classifications indépendantes."""
    result = reconcile_stat_ranking_args(question, arguments)
    text = normalize(question)
    if extract_stat_ranking_args(question) is None:
        # Un tri ne suffit pas à prouver une demande d'optimum.
        if result.get("best_only"):
            if re.search(r"(?:^|-)(?:(?:le|la|les)-(?:plus|moins)|meilleur(?:e|s|es)?|minimum|maximum)(?:-|$)", text):
                raise ValueError("Superlatif non reconnu : précisez la statistique ou une quantité.")
            result["best_only"] = False
    classifications = extract_classifications(question)
    if classifications:
        for key in ("legendary", "mythical"):
            if key in classifications:
                result[key] = True
            else:
                result.pop(key, None)
    return result


def extract_stat_ranking_args(question: str) -> dict | None:
    """Reconnaît des superlatifs explicites, jamais des valeurs ou un classement.

    Hors motifs reconnus, le choix du modèle reste inchangé. Les comparaisons
    entre espèces nommées ne sont pas couvertes. Types = mentions littérales,
    pas inférence depuis un nom d'espèce, une résistance ou une capacité.
    """
    text = normalize(question)
    ranking_text = re.sub(r"entre-(?:les-)?niveaux-\d+-et-\d+|"
                          r"entre-(?:le-)?niveau-\d+-et-(?:le-)?niveau-\d+", "", text)
    if (not re.search(r"(?:^|-)(?:pokemons?|megas?|top-?\d+|les-\d+-plus)(?:-|$)", text)
            or re.search(r"(?:^|-)(?:entre|compare|comparaison|page|offset|suivants|suivantes)(?:-|$)", ranking_text)):
        return None
    aliases = {normalize(label): identifier for identifier, label in BASE_STAT_NAMES.items()}
    aliases.update({identifier: identifier for identifier in BASE_STAT_NAMES})
    aliases.update({"attaques":"attack", "defenses":"defense",
                    "attaques-speciales":"special-attack", "defenses-speciales":"special-defense"})
    aliases.update({"total-de-statistiques":"base-stat-total", "total-de-base":"base-stat-total",
                    "total-des-statistiques-de-base":"base-stat-total",
                    "total-de-statistiques-de-base":"base-stat-total",
                    "total-des-stats":"base-stat-total", "total-de-stats":"base-stat-total"})
    stat_pattern = "|".join(sorted(aliases, key=len, reverse=True))
    matches = set()
    cues = {
        "asc": r"moins-(?:de|d)|plus-faibles?|pire(?:s)?|minimum-(?:de|d)|minimum|min",
        "desc": r"plus-(?:de|d)|meilleur(?:e|s|es)?|plus-(?:gros|grand|haut|eleve)(?:e|s|es)?|maximum|max",
    }
    for order, cue in cues.items():
        for match in re.finditer(rf"(?:^|-)(?:{cue})-({stat_pattern})(?=-|$)", text):
            matches.add((aliases[match.group(1)], order))
    # « la Défense la plus faible » / « les PV les plus élevés ».
    for match in re.finditer(
            rf"(?:^|-)({stat_pattern})-(?:le|la|les)-(plus-(?:faibles?|bas(?:se|ses)?|"
            rf"eleve(?:e|s|es)?|hauts?|hautes?)|moins-eleve(?:e|s|es)?)(?=-|$)", text):
        cue = match.group(2)
        order = "asc" if any(word in cue for word in ("faible", "bas", "moins")) else "desc"
        matches.add((aliases[match.group(1)], order))
    if re.search(r"(?:^|-)plus-rapides?(?:-|$)", text):
        matches.add(("speed", "desc"))
    if re.search(r"(?:^|-)plus-lent(?:e|s|es)?(?:-|$)", text):
        matches.add(("speed", "asc"))
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("Classement ambigu : précisez une statistique et un seul ordre.")
    stat, order = matches.pop()
    counts = {int(match.group(1)) for match in re.finditer(
        r"(?:^|-)(?:top-|les-)?(\d+)-(?:pokemons?|megas?)(?:-|$)", text)}
    counts.update(int(match.group(1)) for match in re.finditer(r"(?:^|-)top-?(\d+)(?:-|$)", text))
    counts.update(int(match.group(1)) for match in re.finditer(r"(?:^|-)les-(\d+)-plus(?:-|$)", text))
    if len(counts) > 1 or any(not 1 <= count <= 100 for count in counts):
        raise ValueError("Top N invalide ou ambigu : demandez entre 1 et 100 Pokémon.")
    result = {"sort_by":stat, "sort_order":order, "best_only":not counts,
              "limit":counts.pop() if counts else 30, "offset":0}
    if re.search(r"(?:^|-)megas?(?:-|$)", text):
        result["form_category"] = "mega"
        variants = set(re.findall(r"(?:^|-)mega-([xyz])(?:-|$)", text))
        if len(variants) > 1:
            raise ValueError("Précisez une seule variante Méga pour ce classement.")
        if variants:
            result["form"] = "mega-" + variants.pop()
    return result


def reconcile_stat_ranking_args(question: str, arguments: dict) -> dict:
    """Restaure les motifs reconnus et leurs types littéraux sans comparer de stats."""
    ranking = extract_stat_ranking_args(question)
    corrected = dict(arguments)
    if ranking is None:
        return corrected
    text = normalize(question)
    extracted_types = extract_pokemon_types(question)
    # Dans une question de classement, « en combat » ne définit pas un type Combat.
    if re.search(r"(?:^|-)(?:en|au)-combat(?:-|$)", text):
        raise ValueError("Ce classement porte sur les statistiques de base, pas celles en combat.")
    if not extracted_types and not extract_move_constraints(question).get("move_type") and re.search(
            r"(?:^|-)de-types?-(?:[^-]+)(?:-|$)", text):
        raise ValueError("Type demandé non reconnu : précisez son nom.")
    corrected.update(ranking)
    if "form_category" not in ranking:
        corrected.pop("form_category", None)
    if extracted_types:
        corrected["types"] = list(extracted_types["types"])
        corrected["type_match"] = extracted_types["type_match"]
    else:
        corrected.pop("types", None)
        corrected.pop("type_match", None)
    if ranking.get("form_category") == "mega" and normalize(corrected.get("form")) == "mega":
        corrected.pop("form")  # Toutes les Méga incluent aussi X/Y/Z.
    return corrected


def extract_form(question: str) -> str | None:
    normalized = normalize(question)
    matches = [
        form
        for token, form in REGION_FORMS.items()
        if re.search(rf"(?:^|-){re.escape(token)}(?:-|$)", normalized)
    ]
    return matches[0] if len(matches) == 1 else None


def has_explicit_game(question: str) -> bool:
    normalized = normalize(question)
    padded = f"-{normalized}-"
    if any(f"-{alias}-" in padded for alias in VERSION_ALIASES):
        return True
    return bool(
        re.search(
            r"(?:^|-)(?:dans|in|version|versions|jeu|jeux|(?:en|sur)-pokemon)(?:-|$)",
            normalized,
        )
    )


def extract_version_group(
    question: str,
    known_version_groups: set[str] | None = None,
) -> tuple[str | None, bool]:
    normalized = normalize(question)
    padded = f"-{normalized}-"
    hits = [(match.start(), match.start()+len(alias)+1, value)
            for alias, value in VERSION_ALIASES.items()
            for match in re.finditer(rf"(?=-{re.escape(alias)}-)", padded)]
    matches = {hit[2] for hit in hits if not any(
        other[0] <= hit[0] and hit[1] <= other[1] and other[1]-other[0] > hit[1]-hit[0]
        for other in hits)}
    if len(matches) > 1:
        return None, True
    if len(matches) == 1:
        return next(iter(matches)), False

    direct = {
        identifier
        for identifier in (known_version_groups or set())
        if f"-{normalize(identifier)}-" in padded
    }
    if len(direct) > 1:
        return None, True
    if direct:
        return next(iter(direct)), False
    return None, has_explicit_game(question)


def extract_level_bounds(question: str) -> tuple[int | None, int | None] | None:
    return _extract_numeric_bounds(question, "level")


def extract_power_bounds(question: str) -> tuple[int | None, int | None] | None:
    """Puissance explicitement chiffrée ; aucune inférence de catégorie."""
    return _extract_numeric_bounds(question, "power")


def _extract_numeric_bounds(question: str, quantity: str) -> tuple[int | None, int | None] | None:
    text = normalize(question)
    raw_noun = r"(?:niveaux?|levels?)" if quantity == "level" else "puissance"
    if re.search(rf"{raw_noun}\s*[<>≤≥]|[<>≤≥]\s*\d+\s*(?:de\s+)?{raw_noun}", question, re.I):
        raise ValueError(f"Opérateur numérique de {quantity} non pris en charge ; utilisez une borne en mots.")
    if re.search(rf"{raw_noun}\s+-\s*\d|(?:moins|plus)\s+-\s*\d+\s+(?:de\s+)?{raw_noun}", question, re.I):
        raise ValueError(f"Borne négative de {quantity}.")
    if re.search(rf"{raw_noun}\s+(?:de\s+)?\d+[.,]\d|\d+[.,]\d+\s+(?:de\s+)?{raw_noun}", question, re.I):
        raise ValueError(f"Borne non entière de {quantity}.")
    if quantity == "level":
        noun = r"(?:niveau|niveaux|level|levels)"
        ranges = [rf"entre-(?:les-)?{noun}-(\d+)-et-(\d+)",
                  rf"entre-(?:le-)?{noun}-(\d+)-et-(?:le-)?{noun}-(\d+)"]
        patterns = [
            (rf"(?:apres|after)-(?:le-)?{noun}-(\d+)", "min", 1),
            (rf"(?:a-partir-du|a-partir-de|from)-{noun}-(\d+)", "min", 0),
            (rf"(?:avant|before)-(?:le-)?{noun}-(\d+)", "max", -1),
            (rf"(?:jusqu-au|jusqu-a|jusque-au|jusque-a)-{noun}-(\d+)", "max", 0),
            (rf"(?:au-moins)-(?:le-)?{noun}-(\d+)", "min", 0),
            (rf"(?:au-plus)-(?:le-)?{noun}-(\d+)", "max", 0),
            (rf"(?:au|a|at)-{noun}-(\d+)-(?:au-minimum|minimum|et-plus)", "min", 0),
            (rf"(?:au|a|at)-{noun}-(\d+)-(?:au-maximum|maximum|et-moins)", "max", 0),
            (rf"(?:au|a|at)-{noun}-(\d+)", "exact", 0),
            (rf"{noun}-(?:d-)?au-moins-(\d+)", "min", 0),
            (rf"{noun}-(?:d-)?au-plus-(\d+)", "max", 0),
        ]
    else:
        noun = r"puissance"
        ranges = [r"puissance-(?:comprise-)?entre-(\d+)-et-(\d+)",
                  r"entre-(\d+)-et-(\d+)-(?:de-)?puissance"]
        patterns = []
        for cue, kind, offset in [("au-moins", "min", 0), ("au-plus", "max", 0),
                                  ("plus-de", "min", 1), ("moins-de", "max", -1)]:
            patterns.extend([(rf"(?:d-)?{cue}-(\d+)-(?:points?-de-|de-)?puissance", kind, offset),
                             (rf"puissance-(?:d-)?{cue}-(\d+)", kind, offset)])
        patterns.extend([(r"puissance-(?:de-)?(\d+)-(?:au-minimum|minimum|et-plus)", "min", 0),
                         (r"puissance-(?:de-)?(\d+)-(?:au-maximum|maximum|et-moins)", "max", 0),
                         (r"puissance-(?:de-)?(\d+)", "exact", 0),
                         (r"(\d+)-de-puissance", "exact", 0)])
    lower, upper, spans = [], [], []
    for pattern in ranges:
        for match in re.finditer(rf"(?:^|-)(?:{pattern})(?=-|$)", text):
            if any(start <= match.start(1) < end for start, end in spans):
                continue
            low, high = int(match.group(1)), int(match.group(2))
            if low > high:
                raise ValueError(f"Intervalle de {quantity} impossible.")
            lower.append(low)
            upper.append(high)
            spans.append(match.span())
    for pattern, kind, offset in patterns:
        for match in re.finditer(rf"(?:^|-)(?:{pattern})(?=-|$)", text):
            if any(start <= match.start(1) < end for start, end in spans):
                continue
            spans.append(match.span())
            value = int(match.group(1)) + offset
            if kind in {"min", "exact"}:
                lower.append(value)
            if kind in {"max", "exact"}:
                upper.append(value)
    if not spans:
        return None
    # Les autres nombres (génération, top N, puissance/niveau, numéro) sont
    # indépendants. Seules les alternatives locales de cette quantité bloquent.
    for start, end in spans:
        if re.match(r"-(?:ou|or|et|a)-(?:au-|le-)?(?:niveau-|level-)?\d+", text[end:]) or re.search(
                r"(?:^|-)(?:pas|sauf|hors|environ|approximativement)$", text[:start].rstrip("-")):
            return None
    remaining = list(text)
    for start, end in spans:
        remaining[start:end] = " " * (end-start)
    if re.search(rf"{noun}-(?:[a-z]+-){{0,3}}\d+", "".join(remaining)):
        return None
    if quantity == "level" and re.search(r"(?:avant|apres|before|after)-\d+", "".join(remaining)):
        return None
    minimum, maximum = max(lower) if lower else None, min(upper) if upper else None
    if (minimum is not None and minimum < 0) or (maximum is not None and maximum < 0) or (
            minimum is not None and maximum is not None and minimum > maximum):
        raise ValueError(f"Intervalle de {quantity} impossible.")
    if re.search(rf"{noun}\s*-\s*\d", question, re.I):
        raise ValueError(f"Borne négative de {quantity}.")
    return minimum, maximum


def extract_national_pokedex_number(question: str) -> int | None:
    """Numéro explicite en contexte Pokémon/Pokédex, sans résolution d'espèce.

    Reconnaît numéro/n°/no suivis de chiffres, pas les nombres isolés de
    niveau ou génération. Refuse plusieurs numéros distincts et les Pokédex
    régionaux, qui ne doivent pas devenir un numéro national.
    """
    normalized = normalize(question)
    if not re.search(r"(?:^|-)(?:pokemon|pokedex)(?=-|$)", normalized):
        return None
    mentions = list(re.finditer(
        r"(?:^|-)(?:numeros?-(?:national-)?|n-?|no-?|pokedex-national-)(\d+)(?=-|$)", normalized))
    numbers = {int(match.group(1)) for match in mentions}
    if not numbers:
        return None
    if re.search(r"(?:num[eé]ros?|n[°º]|no|pokedex\s+national|pokédex\s+national)\s+"
                 r"(?:national\s+)?\d+[.,]\d", question, re.I):
        raise ValueError("Numéro national non entier ou plusieurs numéros non représentables.")
    for mention in mentions:
        # Ne pas absorber un top N, un niveau ou une génération plus loin.
        chain = re.match(r"(?:(?:-(?:ou|et|a)-|,)(?:numero-)?\d+)+", normalized[mention.end():])
        if chain:
            numbers.update(int(value) for value in re.findall(r"\d+", chain.group()))
    if re.search(r"(?:num[eé]ros?|n[°º]|no)\s*-\s*\d", question, re.IGNORECASE):
        raise ValueError("Le numéro national doit être strictement positif.")
    if re.search(r"(?:^|-)pokedex-(?:regional|de|d|kanto|johto|hoenn|sinnoh|unys|kalos|alola|galar|hisui|paldea)(?=-|$)", normalized):
        raise ValueError("Ce numéro concerne un Pokédex régional, pas le Pokédex national.")
    if len(numbers) != 1 or 0 in numbers:
        raise ValueError("Précisez un seul numéro national strictement positif.")
    return numbers.pop()


def extract_explicit_constraints(
    question: str,
    known_version_groups: set[str] | None = None,
) -> ExplicitConstraints:
    normalized = normalize(question)
    level_explicit = bool(re.search(
        r"(?:^|-)(?:niveau|niveaux|level|levels)-"
        r"(?:(?:d|de|au|a|moins|plus|minimum|maximum|environ|exactement)-){0,4}\d+(?=-|$)", normalized))
    version_group, version_ambiguous = extract_version_group(
        question,
        known_version_groups=known_version_groups,
    )
    move = extract_move_constraints(question)
    types = extract_pokemon_types(question)
    classification = extract_classifications(question)
    power_bounds = extract_power_bounds(question)
    # Une quantité marquée mais non interprétable ne doit pas être transformée
    # en filtre exact par le modèle (environ, alternatives, formulations inconnues).
    if power_bounds is None and re.search(
            r"puissance-(?:[a-z]+-){0,3}\d+|\d+-(?:points?-de-|de-)?puissance", normalized):
        raise ValueError("Borne de puissance explicite ambiguë ou non reconnue.")
    return ExplicitConstraints(
        form=extract_form(question),
        version_group=version_group,
        version_ambiguous=version_ambiguous,
        explicit_game=has_explicit_game(question),
        level_bounds=extract_level_bounds(question),
        level_explicit=level_explicit,
        form_ambiguous=sum(bool(re.search(rf"(?:^|-){region}(?=-|$)", normalized))
                           for region in REGION_FORMS) > 1,
        national_number=extract_national_pokedex_number(question),
        generation=extract_generation(question),
        pokemon_types=types.get("types", ()),
        type_match=types.get("type_match"),
        move_type=move.get("move_type"),
        damage_class=move.get("damage_class"),
        power_bounds=power_bounds,
        legendary=classification.get("legendary"),
        mythical=classification.get("mythical"),
        ranking=extract_stat_ranking_args(question),
        form_category="mega" if re.search(r"(?:^|-)pokemons?-megas?(?=-|$)|(?:^|-)les-megas?(?=-|$)", normalized) else None,
    )
