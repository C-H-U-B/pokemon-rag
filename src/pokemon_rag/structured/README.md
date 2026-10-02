# Requêtes structurées

`query_engine.py` traduit une question en plan validé puis appelle une fonction SQL prédéfinie. Le parseur rapide couvre les formulations sûres ; le modèle traite les autres formulations. La base utilisée est définie dans `config.py`.

## Interfaces et limites

Les extracteurs de formes, jeux et niveaux sont partagés avec le client MCP dans
[`constraints/query_constraints.py`](../constraints/README.md). Le moteur fournit
les groupes de versions connus depuis SQLite et conserve la validation des plans.
La résolution des espèces et capacités reste ici, notamment la correspondance
de Tonnerre vers l'identifiant interne `thunderbolt`. L'interface reste française.

- `query_structured_data(question)` renvoie un résultat avec `error`. Toujours lire ce champ : `count == 0` peut accompagner une erreur et ne suffit pas à conclure à l'absence de données.
- `execute_plan(plan)` valide le plan ; les fonctions `get_*` sont aussi appelées directement par MCP et peuvent lever une exception.
- Les bornes de niveau sont inclusives dans le plan. « Après le niveau 40 » devient donc un minimum de 41.
- Pour les CT/CS, un jeu omis sélectionne le groupe le plus récent possédant
  des données de machines pour le Pokémon et sa forme, selon `version_groups.order`.
  Le résultat indique `version_group` et `version_selection="latest_available"`.
  Un jeu explicite reste inchangé (`"explicit"`), même si son résultat est vide.
  La disponibilité signifie ici présence de données locales de CT, pas preuve
  exhaustive de présence dans tous les jeux.
- `get_level_up_moves` choisit aussi le dernier groupe avec des relations de
  montée de niveau, avant d'appliquer les bornes. `get_move_learning_methods`
  choisit le dernier movepool des formes résolues, avant le filtre de capacité.
  `get_pokemon_moves` et `search_pokemon` appliquent la même idée à une méthode
  demandée sans jeu, y compris par des bornes de niveau : ils retiennent le
  dernier jeu où le Pokémon a cette méthode. Dans Pokémon Champions, tout
  s'apprend par la seule méthode `train` ; sans cette règle, une demande de CT
  ou de niveaux y trouverait une liste vide. Les filtres de type, catégorie et
  puissance ne changent jamais de jeu, et un jeu explicite reste strict.
  Les jeux explicites restent stricts et la résolution des formes reste celle
  des outils historiques. Les trois fonctions exposent `all_versions=True`
  pour conserver l'historique ; ce mode est incompatible avec un jeu unique.
  `version_selection` distingue `latest_available`, `explicit` et `all_versions`.
- Espèce, forme et groupe de versions sont des paramètres distincts. Ne pas remplacer une forme introuvable par la forme de base.
- Les types, l'identité Pokédex et les capacités signature viennent du Pokédex personnalisé. Ces opérations ne prennent pas en charge les filtres par jeu. Une valeur absente reste non renseignée ; les annotations de source sont conservées.
  Lorsque le nom d'espèce n'est pas un nom complet d'entrée, le moteur utilise
  le catalogue PokéAPI pour retrouver `species_id`, puis l'entrée personnalisée
  par défaut. Une forme explicite reste prioritaire ; aucune forme manquante
  n'est remplacée par défaut, et plusieurs entrées possibles restent une erreur.
- La protection contre certaines mentions de jeux inconnus appartient au parseur de questions. Ne pas supposer que les appels directs aux fonctions SQL bénéficient de ce contrôle de langage naturel.

`pokemon_name_catalogue()` fournit au guard les alias d'espèces et d'entrées
de formes réellement présents dans `pokemon.db`, avec l'espèce canonique et
l'identifiant éventuel de forme. L'extraction des mentions se fait ensuite
sans SQLite dans les contraintes ; elle n'utilise pas le parseur LLM.

## Recherche Pokémon et movepool filtrable via MCP

Ces fonctions déterministes sont appelées directement par MCP/ADK. Elles ne
modifient pas le catalogue d'opérations du parseur ou le routage du graphe.
Les talents sont reportés : aucune table, donnée ou source n'a été ajoutée.

```python
search_pokemon(
    pokedex_number=None, generation=None, types=None, type_match="all",
    legendary=None, mythical=None, form=None, version_group=None,
    move_type=None, damage_class=None, min_power=None, max_power=None,
    learning_method=None, min_level=None, max_level=None, limit=30, offset=0,
    sort_by="national_number", sort_order="asc",
    best_only=False, form_category=None,
)
get_pokemon_moves(
    pokemon, form=None, version_group=None, move_type=None, damage_class=None,
    min_power=None, max_power=None, learning_method=None,
    min_level=None, max_level=None, limit=30, offset=0,
)
```

La recherche utilise `custom_pokedex` pour le numéro national, les noms et les
types, avec ses liens vers `pokemon` et `pokemon_forms`. La génération vient de
`pokemon_species.generation_id` : origine de l'espèce, même pour une forme plus
récente. `legendary` et `mythical` filtrent séparément les deux flags PokéAPI ;
`False` est un filtre, `None` ne filtre pas. Les contraintes se combinent par ET.

Le classement se compose avec tous les filtres existants : `WHERE` pour les
contraintes, `ORDER BY` pour la statistique, `LIMIT/OFFSET` pour la page.
`sort_by` accepte `national_number` (défaut) ou une statistique de base :

| Identifiant | Libellé français | Colonne dans `custom_pokedex_fr` |
| --- | --- | --- |
| `hp` | PV | `pv` |
| `attack` | Attaque | `attaque` |
| `defense` | Défense | `defense` |
| `special-attack` | Attaque Spéciale | `attaque_speciale` |
| `special-defense` | Défense Spéciale | `defense_speciale` |
| `speed` | Vitesse | `vitesse` |
| `base-stat-total` | Total des statistiques | somme SQL des six colonnes |

`BASE_STAT_NAMES` dans les contraintes centralise les identifiants et libellés ;
`BASE_STAT_FIELDS` dans le moteur associe les colonnes SQL. Les appels directs au moteur
acceptent aussi ces libellés français ; MCP expose les identifiants canoniques
dans une enum. Aucune expression SQL utilisateur n'est acceptée. `sort_order`
accepte uniquement `asc` ou `desc`. Il s'agit de statistiques de base, sans
IV, EV, nature, niveau ou effet de combat ; les talents restent reportés.

Les statistiques sont jointes par `source_row`, donc celles de l'entrée et de
sa forme. Une valeur NULL est exclue du classement concerné ; le total exige
les six valeurs. Le moteur recalcule le total, sans utiliser `total_de_base`.
Chaque ligne classée renvoie `base_stat_value`, avec `stat_name_fr` au niveau
du résultat. `base_speed` est conservé pour compatibilité ; le classement par
total renvoie aussi `base_stat_total`. Aucun tri ou total n'est calculé en Python
ou laissé au modèle. Les égalités sont départagées par numéro national,
identifiant de Pokémon puis de forme pour une pagination stable.

Pour un top N, garder `best_only=False`, choisir le tri et `limit=N`. Un
`limit=1` seul donne une première ligne sans attester un gagnant unique.
Pour un superlatif singulier, utiliser `best_only=True` avec un tri statistique.
SQL calcule MIN (`asc`) ou MAX (`desc`) après tous les filtres, puis sélectionne
tous les gagnants au seuil. `best_value`, `tie`, `tie_count` et `matching_count`
indiquent valeur gagnante, égalité, nombre de gagnants et nombre de candidats
avec une valeur connue. `total_count` compte alors les gagnants ; pagination
et `limit` restent applicables à cet ensemble. Une page contenant un seul nom
peut donc avoir `tie=true`. Sans candidat : `best_value=null`, aucun résultat,
`tie=false`, comptes à zéro. Les clients doivent signaler les ex aequo et toute
page partielle, sans compléter les noms manquants de mémoire.

Exemple : le légendaire de 4G le plus rapide utilise `generation=4`,
`legendary=True`, `sort_by="speed"`, `sort_order="desc"`, `best_only=True`.
Le top 5 Spectre par Attaque Spéciale utilise `types=["ghost"]`,
`sort_by="special-attack"`, `sort_order="desc"`, `limit=5`.

`types` contient un ou deux noms français, anglais ou identifiants. `all` exige
tous les types, `any` au moins un, `exact` exactement la combinaison. Un seul
type en mode `all` inclut les doubles types. Les doublons de types sont fusionnés.

Sans `form`, la recherche exige le Pokémon par défaut et sa forme PokéAPI par
défaut ; le flag personnalisé seul ne suffit pas pour Arceus ou Silvallié.
Avec `form`, elle cherche un `form_identifier` ou identifiant complet exact,
normalisé (notamment `alola`, `galar`, `hisui`, `paldea`). Le movepool réutilise
le résolveur existant, exige un seul `pokemon_id` et ne replie jamais une forme
explicite introuvable. Des formes cosmétiques partageant un `pokemon_id` partagent
aussi les données de movepool : aucune différence absente de la base n'est inventée.

`form_category="mega"` remplace la restriction aux formes par défaut par
`pokemon_forms.is_mega=1`. Cela couvre les variantes X/Y/Z et autres Méga
signalées par les données, sans liste codée en dur. Le classement utilise leurs
propres lignes de statistiques. Un `form` explicite se combine par ET avec la
catégorie ; `form="mega"` conserve son sens d'identifiant exact et n'est pas
un alias pour toutes les variantes. Sans catégorie ni forme, la sélection par
défaut reste inchangée. La génération reste celle de l'espèce, même pour une
Méga introduite plus tard. La couverture porte sur les formes liées au catalogue,
pas sur toutes les formes PokéAPI. Aucun schéma ou contenu de base n'est modifié.

La recherche couvre les formes liées au catalogue personnalisé. Les formes par
défaut de Xerneas, Mimiqui et Morpeko n'y sont actuellement pas représentées.
`catalogue_complete=false` et `catalogue_missing_default_forms` signalent cette
limite ; les totaux portent sur le catalogue lié, sans substitution d'une forme.
Leurs movepools restent accessibles depuis PokéAPI. Cette couverture est calculée
depuis les données, pas une liste d'exceptions codée en dur.

Les filtres de capacités sont existentiels : au moins une capacité et relation
d'apprentissage doivent satisfaire tous les filtres dans le même jeu. Le type
vient de `moves.type_id`, la catégorie exclusivement de `moves.damage_class_id`
(1 statut, 2 physique, 3 spéciale). `damage_class` accepte `status`, `physical`,
`special` et leurs libellés français. `power=NULL` reste une puissance inconnue,
y compris pour Frappe Atlas physique ; une borne de puissance exclut ces valeurs.
Toutes les bornes sont inclusives. Les bornes de niveau impliquent `level-up` et
sont refusées avec une autre méthode. Les autres méthodes utilisent les
identifiants présents dans `pokemon_move_methods`.

Un `version_group` explicite doit être connu et est strict, même sans données.
Sinon, un helper SQL commun aux deux nouvelles fonctions choisit le dernier
groupe avec des lignes `pokemon_moves` pour chaque `pokemon_id`, selon
`version_groups.order`, puis génération et ID pour départager. Ce choix précède
les filtres : aucune capacité ancienne ne provoque un repli historique.
Chaque résultat de recherche inverse indique son jeu ; le movepool indique
`version_group`, `version_group_explicit` et `version_selection`.
Les propriétés des capacités restent actuelles, sans historicisation ;
`move_properties="current_not_historicized"` le rappelle.
Les anciens outils gardent leur sélection de versions et leur API.

Les capacités sont uniques par `move_id`. Leur champ `learning` conserve les
couples méthode/niveau satisfaisant les filtres, sans dupliquer les capacités.
`movepool_available` distingue une absence de données pour le jeu retenu d'un
movepool connu sans capacité correspondante. `total_count>0` permet de répondre
à une question d'existence ; un zéro avec `movepool_available=false` ne prouve
pas une impossibilité d'apprentissage.

Les résultats contiennent `results`, `total_count`, `returned_count`, `limit`,
`offset`, `truncated` et `has_more`. `limit` vaut 30 par défaut, entre 0 et 100 ;
0 permet un comptage sans lignes. Le total est calculé en SQL avant pagination.
`truncated` signifie que la page n'est pas toute la liste, même sur la dernière
page ; `has_more` indique une page suivante. L'ordre est stable : numéro national,
Pokémon et forme pour la recherche ; nom français puis ID pour les capacités.
Les arguments invalides lèvent une erreur, distincte d'un résultat valide vide.

L'inspection du plan d'une recherche Eau + génération + Glace spéciale confirme
l'utilisation des index existants de Pokémon et de movepool, dont
`idx_pokemon_moves_lookup(pokemon_id, version_group_id, ...)`. Aucun index ajouté,
aucune reconstruction de la base. Une recherche historique multijeux n'est pas
exposée par ces nouvelles primitives.

## Étendre le parseur du graphe

Vérifier d'abord que les données locales permettent réellement de répondre. Ajouter l'exécution et la validation du plan, puis adapter le parseur, le routeur et le formatage dans `graph/nodes.py`. Si l'opération doit être accessible aux clients MCP, ajouter son outil explicitement : l'exposition n'est pas automatique.

Tester la bonne réponse ainsi que la conservation des filtres et le traitement des données absentes. Adapter les attentes du benchmark et ajouter une référence factuelle vérifiée dans la source, sans la dériver de la réponse générée. Voir [tests/README.md](../../../tests/README.md).
