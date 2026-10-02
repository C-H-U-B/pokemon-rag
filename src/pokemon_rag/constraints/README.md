# Contraintes explicites des questions

`query_constraints.py` rassemble les règles déterministes utilisées par le
[moteur structuré](../structured/README.md), le [client MCP](../mcp/README.md)
et le [guard ADK](../agent/README.md)
pour extraire les contraintes explicitement reconnaissables : formes, jeux,
niveaux, numéro national, génération, types, catégorie et puissance de
capacités, classifications et classements.
Il utilise uniquement la bibliothèque standard : aucun accès SQLite, appel LLM
ou appel MCP. `__init__.py` ne réexporte actuellement aucune fonction.

## Responsabilité et intégration

Le module décrit ce qu'il reconnaît dans la question. Il ne choisit pas d'outil,
ne valide pas un plan SQL et ne décide pas du message à afficher à l'utilisateur.

- Le moteur structuré appelle les extracteurs depuis ses fonctions `_fast_*`.
  Il fournit les identifiants de groupes de versions connus dans SQLite et
  conserve la responsabilité du parsing, de la validation et de l'exécution.
- Le client appelle `extract_explicit_constraints` depuis `reconcile_tool_call`,
  après le choix de Qwen et avant `session.call_tool`. Il utilise les alias du
  module sans fournir de catalogue SQLite. La réconciliation des arguments et
  les refus sont implémentés dans le client, pas dans ce dossier.
- Un appel direct à un outil du serveur MCP ne passe pas par cette
  réconciliation du client.
- Le guard ADK appelle `extract_explicit_constraints` avant l'exécution d'un
  outil, indépendamment des arguments proposés. Il utilise les alias sans catalogue SQLite et conserve dans le package
  `agent` la restauration des arguments et les refus selon l'outil sélectionné.
  Il applique tous les champs reconnus ; le graphe et le client MCP existant
  conservent leurs propres opérations et sous-ensembles de réconciliation.

La résolution des espèces et des capacités reste hors de ce module.
`extract_named_pokemon` reçoit un catalogue d'alias fourni par le
moteur : correspondances exactes après normalisation, frontières de noms,
priorité à un alias complet sur un nom d'espèce qu'il contient. Plusieurs
espèces ou formes détectées sont refusées ; aucune mention ne produit `None`.
L'extracteur conserve séparément l'espèce et la forme et ne déduit aucun nom.
`is_named_identity_question` reconnaît le motif numéro national / identité
Pokédex ; le guard garde la responsabilité du refus d'outil incompatible.
La correspondance interne `Tonnerre` → `thunderbolt` appartient à
`structured/query_engine.py`. L'interface du projet reste française ; les alias
anglais présents dans le code ne constituent pas un contrat d'interface bilingue.

## Contrat des extracteurs

`normalize` retire les accents, uniformise la casse et remplace les séparateurs
par des tirets. Cette normalisation sert à comparer les mentions, pas à produire
un texte destiné à l'utilisateur.

| Fonction | Résultat et limites |
| --- | --- |
| `extract_form(question)` | Une forme parmi `alola`, `galar`, `hisui`, `paldea` si une seule est reconnue ; sinon `None` |
| `extract_stat_ranking_args(question)` | Arguments de tri pour des superlatifs explicites (`moins de Défense`, `meilleure Attaque Spéciale`, `plus rapide/lent`) et top N ; `None` hors motifs reconnus, comparaisons nommées et pagination explicite ; ambiguïtés ou N invalide refusés |
| `reconcile_stat_ranking_args(question, arguments)` | Copie les arguments, restaure le classement reconnu et les types littéraux demandés ; retire un type ou une catégorie Méga inventés ; conserve les autres filtres |
| `extract_national_pokedex_number(question)` | Numéro explicite après numéro/n°/no, dans un contexte Pokémon ou Pokédex ; `None` sans mention reconnue ; `ValueError` pour plusieurs numéros, zéro, une valeur négative reconnue ou un Pokédex régional explicite |
| `has_explicit_game(question)` | Détection heuristique d'un alias ou d'une mention de jeu ; ne prouve pas que le jeu est valide |
| `extract_version_group(question, known_version_groups=None)` | Couple `(groupe, ambiguïté)` ; les alias sont examinés avant les identifiants optionnels fournis par l'appelant |
| `extract_level_bounds(question)` | Couple inclusif `(minimum, maximum)`, avec `None` pour une borne absente ; `None` si la formulation n'est pas entièrement reconnue ; `ValueError` si l'intervalle reconnu est impossible |
| `extract_power_bounds(question)` | Bornes inclusives de puissance : au moins/au plus, plus de/moins de, valeur exacte ou intervalle chiffré ; aucune catégorie déduite d'une puissance absente |
| `extract_generation(question)` | Origine explicitement numérotée (`génération 4`, `4e génération`, `7G`) ou ordinal français de première à neuvième ; jamais déduite du jeu ; alternatives/intervalles reconnus refusés |
| `extract_pokemon_types(question)` | Types littéraux après « de type » ou « Pokémon Eau/Vol » ; `all`, `any` pour un « ou » local, `exact` pour monotype/uniquement ; aucune déduction depuis résistance ou espèce |
| `extract_move_constraints(question)` | Type et catégorie physique/spéciale/statut attachés à attaque/capacité ; ne transforme pas Attaque Spéciale en catégorie de capacité |
| `names_learning_method(question)` | Vrai dès qu'un mot de méthode apparaît (CT/CS, niveau, œuf, reproduction, donneur, méthode, comment…) ; vocabulaire large, sans identifier la méthode |
| `without_unnamed_learning_method(question, arguments)` | Retire `learning_method` si la question ne nomme aucune méthode ; ne restaure ni ne remplace jamais une méthode |
| `extract_classifications(question)` | Filtres positifs indépendants légendaire et fabuleux/mythique ; négations/alternatives reconnues refusées |
| `extract_explicit_constraints(question, known_version_groups=None)` | Objet `ExplicitConstraints` regroupant les résultats ; erreurs explicites pour les contraintes reconnues mais impossibles ou ambiguës |

`ExplicitConstraints` contient `form`, `version_group`, `version_ambiguous`,
`explicit_game`, `level_bounds` et `level_explicit`, ainsi que les champs
typés des filtres ci-dessus, `form_ambiguous`, `ranking` et `form_category`.

Le numéro national est aussi disponible dans `national_number`, sans ajouter
une opération au parseur du graphe. Par exemple,
« Quel Pokémon numéro 369 du Pokédex national ? » retourne 369, tandis que
« Quel est le numéro national de Lockpin ? » ne contient aucun numéro à chercher.
Le motif reconnaît aussi « Pokédex national 369 », sans couvrir les nombres
écrits en lettres ou les nombres isolés. Les nombres de niveau, puissance,
génération et quantité n'appartiennent pas à la même contrainte numérique.

Les indicateurs de présence permettent de distinguer une mention non résolue
d'une absence de contrainte.

`BASE_STAT_NAMES` centralise les libellés français et identifiants statistiques.
Le moteur conserve les colonnes SQL et tous les calculs. Les deux clients
appliquent la réconciliation de classement uniquement à `pokemon_search`.
Elle distingue top N et superlatif, reconnaît les Méga (et X/Y/Z explicites),
les types monotypes et ne confond pas un type d'attaque avec un type de Pokémon.
Sans quantité explicite, un superlatif singulier ou pluriel conserve tous les
ex aequo (`best_only=true`) ; avec N explicite, `best_only=false` et `limit=N`.
Les formulations « Défense la plus basse » et « PV les plus élevés » sont aussi
reconnues, ainsi que les libellés pluriels d'Attaque et de Défense.
Elle ne calcule ni valeur, ni maximum, ni total. La reconnaissance reste limitée
aux motifs documentés ; les autres contraintes sont traitées comme auparavant.
`reconcile_search_args` ajoute les invariants des listes : pas de `best_only=true`
sans optimum reconnu, et classifications positives indépendantes (`légendaire`
→ `legendary=true`, `fabuleux` → `mythical=true`). Un filtre de l'autre catégorie
inventé par le modèle est retiré. Les négations reconnues et alternatives entre
classifications sont refusées plutôt que traduites en une intersection incorrecte.
`VERSION_GROUP_NAMES_FR` fournit des libellés de présentation des jeux connus,
sans modifier leurs identifiants internes.
`level_explicit` exige un nombre attaché à un mot de niveau ; une
demande générale « en montant de niveau » ne constitue pas une borne explicite.
`version_ambiguous` couvre aussi une mention de jeu non reconnue, pas seulement
plusieurs groupes possibles. `form_ambiguous` distingue plusieurs régions
reconnues d'une absence ; les formes complètes sont extraites séparément depuis
le catalogue injecté. Une forme inconnue reste hors extraction.

## Exemples de niveaux et de versions

| Mention | Résultat |
| --- | --- |
| « après le niveau 40 » | `(41, None)` |
| « jusqu'au niveau 30 » | `(None, 30)` |
| « au niveau 30 » | `(30, 30)` |
| « entre les niveaux 10 et 20 » | `(10, 20)` |
| « après le niveau 40 et avant le niveau 50 » | `(41, 49)` |
| « au niveau 20 ou au niveau 30 » | `None` : une alternative n'est pas un intervalle |
| « dans Pokémon Rouge » | `version_group="red-blue"` |

Les jeux sont ramenés aux groupes de versions du modèle de données, pas à une
édition individuelle. La table d'alias couvre actuellement Rouge/Bleu,
Diamant/Perle, Soleil/Lune, Épée/Bouclier et Écarlate/Violet. Elle n'est pas
exhaustive ; les titres complets comme Ultra-Soleil, Rouge Feu ou Diamant
Étincelant ont priorité sur l'alias court qu'ils contiennent. Les identifiants
des jeux de la table de libellés sont également reconnus, sauf `champions` :
ce mot courant ne désigne le jeu que dans le titre complet « Pokémon Champions ».
Des identifiants supplémentaires peuvent être fournis par l'appelant.

## Limites et évolution

Ce parseur repose sur des motifs textuels, sans compréhension générale de la
phrase. Par exemple, le mot « dans » peut signaler un jeu à tort. Les nombres
en lettres, comparaisons entre espèces, pagination de classement, propriétés
implicites, génération déduite d'un jeu et formes inconnues ne sont pas extraits.
Les opérateurs numériques symboliques ne sont pas normalisés en une valeur
exacte : ils sont refusés lorsqu'ils sont attachés à une quantité reconnue.
Les bornes reconnues d'une même quantité sont intersectées, y compris après
un intervalle ; les alternatives locales et bornes incomplètes empêchent son
extraction. Un « ou » sans rapport avec cette quantité ne change pas l'intervalle
ou le double type. `None` n'autorise pas à supprimer arbitrairement un filtre.
Une borne explicitement présente mais ambiguë est refusée par le guard ; une
formulation sans motif fiable ne produit pas de contrainte inventée.

Ajouter ici les règles d'extraction communes, puis vérifier leurs consommateurs.
Garder dans le moteur structuré les accès aux données et la validation des plans,
et dans le client la compatibilité des contraintes avec les outils découverts.
Les régressions concernées sont
[`test_mcp_constraint_preservation.py`](../../../tests/unit/test_mcp_constraint_preservation.py)
et [`test_structured_constraint_preservation.py`](../../../tests/integration/test_structured_constraint_preservation.py).
Les E2E avec Qwen sont dans `tests/long/test_mcp_client_e2e.py` ; leur exécution
relève de l'utilisateur. Voir le [guide des tests](../../../tests/README.md).
