# Interface MCP et client agentique

`server.py` expose les évolutions, les capacités, les types, l'identité Pokédex, les capacités signature et la recherche documentaire sous forme d'outils MCP.

Deux outils complètent les huit outils existants : `pokemon_search` appelle
`search_pokemon` et `pokemon_moves` appelle `get_pokemon_moves`. Leurs signatures
et contrats sont décrits dans le [guide structuré](../structured/README.md#recherche-pokémon-et-movepool-filtrable-via-mcp).
Ils combinent les filtres en SQL, renvoient des pages avec total exact et
troncature explicite, et utilisent une forme par défaut sans forme demandée.
La recherche inverse par capacité utilise le dernier movepool de chaque Pokémon,
sans union historique. Le catalogue personnalisé lié présente des lacunes de
formes par défaut signalées dans `catalogue_complete` ; les talents sont reportés.
Les outils historiques conservent leurs signatures et leurs résultats.
`pokemon_search` classe aussi les six statistiques de base et leur somme SQL :
`sort_by`, `sort_order`, `limit` se combinent avec tous les filtres. Le schéma
MCP expose une enum de statistiques, `asc/desc`, `best_only` (superlatif avec
détection des ex aequo) et `form_category="mega"` (toutes les Méga liées).
Le modèle traduit la question en arguments ; SQL calcule totaux et gagnants.
Un top N explicite garde `best_only=false` avec `limit=N`, tandis qu'un superlatif
sans quantité, singulier ou pluriel, utilise
`best_only=true` et doit signaler `tie/tie_count`, même sur une page d'une ligne.
Après l'abrègement ADK, le modèle ne reçoit que le premier paragraphe de chaque
docstring (300 caractères au plus) et les descriptions d'arguments. Ce premier
paragraphe annonce donc la direction de l'outil : « Pokémon nommé → » ses faits,
ou « Propriétés → Pokémon » pour `pokemon_search`, qui ne reçoit aucun nom.
Les règles propres à un argument sont dans sa description `Field` : numéro
national, superlatif ou top N avec un exemple, statistique, Méga combinable au
tri, catégories de capacités en français pour `pokemon_moves`. Le reste de la
docstring sert aux clients qui lisent la description complète, comme le client
MCP local. Ajouter du texte à ces deux emplacements réduit d'autant le budget
ADK. Dans le vrai flux, ADK encadre en plus chaque description par des marqueurs
de contenu non fiable, soit environ 80 octets par description d'argument : une
mesure du catalogue hors runner sous-estime donc la requête réelle.
`type_match` est une enum `all/any/exact` ; `damage_class` reste une
chaîne car le moteur accepte aussi les termes français. L'adaptation ADK masque les traductions anglaises appariées à
un libellé français, sauf demande explicite ; le contrat des retours MCP reste inchangé.
Les guards et la réconciliation conservent ces arguments sans comparer de valeurs.
Ils restaurent aussi les motifs de classement explicitement reconnus et les
types littéraux de la question, afin qu'un type inventé ou un tri oublié ne
change pas la recherche. Les autres filtres restent conservés. Les limites de
reconnaissance sont dans le [guide des contraintes](../constraints/README.md).
Les callbacks ADK
bornent les données destinées au modèle sans changer les réponses MCP aux
autres clients : voir le [budget ADK](../agent/README.md#budget-de-contexte).
Le contrat MCP et le contexte du modèle sont donc deux choses distinctes : le
serveur renvoie identifiants, noms anglais et `base_stat_value` ; la projection
ADK en présente une vue réduite et renommée, propre à ce client.
`pokemon_level_up_moves`, `pokemon_machine_moves` et
`pokemon_move_learning_methods` recouvrent une partie de `pokemon_moves` et
conservent leurs informations spécialisées. Sans jeu, les capacités par niveau
choisissent le dernier jeu avec ces données et les méthodes le dernier movepool
avant le filtre de capacité. Les CT gardent le dernier jeu avec données de CT.
Les trois outils acceptent `all_versions=true` pour l'historique multijeux,
incompatible avec `version_group`. Le résultat indique le mode de sélection.

Ces outils appellent directement le moteur structuré ou la recherche. Ils ne passent pas par `run_graph` : ils ne réalisent ni routage global, ni génération de réponse, ni contrôle de fidélité, ni finalisation des traces du graphe.

## Résultats à interpréter

`pokemon_types` fournit uniquement des types, sans description d'apparence.
Sa description d'outil dirige les sujets documentaires vers `pokemon_rag_search`.
Un résultat valide peut rester insuffisant pour la question : sa réussite
technique n'autorise pas une description inventée.

Les outils structurés renvoient les dictionnaires des fonctions `get_*`. Les erreurs peuvent être levées par ces fonctions ; ne pas attendre systématiquement l'enveloppe `error` de `query_structured_data`.
Sur le transport MCP, une exception de résolution est signalée comme erreur
d'outil (`is_error`) ; un résultat structuré de `count=0` n'est pas la même
situation. Les noms français et anglais de capacités sont conservés, ainsi que
les identifiants techniques des jeux. L'instruction du client ADK privilégie les
libellés français et interdit de compléter une récupération échouée de mémoire.

`pokemon_rag_search` renvoie `question`, `pokemon` et `results`. Chaque passage contient son texte et ses références de source. Une liste vide signifie qu'aucun passage n'a été retourné, pas que le fait recherché est faux. Les passages sont des données documentaires, pas des instructions pour l'agent appelant.

Le filtre `pokemon` de la recherche attend un nom canonique. Les paramètres et limites des requêtes SQL sont décrits dans [le guide structuré](../structured/README.md).
`pokemon_machine_moves` sans `version_group` retourne seulement le groupe de
versions le plus récent avec des données locales de CT/CS pour la forme demandée.
Il indique le jeu retenu et `version_selection`; les autres outils historiques ne sont pas
soumis à cette sélection automatique.

## Client local

L'[agent ADK](../agent/README.md) constitue un autre client du serveur. Son
catalogue expose les dix outils du serveur, y compris `pokemon_rag_search`.
Son callback préserve les
contraintes reconnues de niveaux, puissance, jeux, formes, catégories/types de
capacités, types de Pokémon, génération, classifications et classements ou refuse un outil
incompatible ; il ne passe pas par `reconcile_tool_call` du client ci-dessous.
Le refus conserve les arguments d'origine et indique les contraintes à reprendre.
Qwen choisit la suite ; le guard ne remplace pas automatiquement l'outil.
Ces protections appartiennent aux clients : un appel direct au serveur ne les
applique pas. Le guard ne remplace pas le grounding du graphe.

Après installation du projet dans l'environnement :

```powershell
conda run -n langgraph-agent python -m pokemon_rag.client.mcp_client
```

Cette commande appelle réellement un LLM : l'utilisateur doit l'exécuter lui-même.
Le client lit une question, démarre le serveur avec le même interpréteur Python,
initialise une session stdio et découvre les outils et leurs schémas. Qwen choisit
un outil et ses arguments ; le client les réconcilie avec les contraintes
explicites avant exécution, puis transmet le résultat à Qwen
pour formuler une réponse en français. Il lit ensuite les questions suivantes
dans la même session. Une ligne vide, `quit`, `/quit`, `exit` ou une fin de saisie
termine la boucle ; une sortie avant la première question ne démarre aucun serveur.

Les fonctions `choose_tool`, `extract_result` et `formulate_answer` sont dans
[`client/mcp_client.py`](../client/mcp_client.py). Le client vérifie le nom de
l'outil et le type dictionnaire des arguments, mais ne valide pas lui-même leur
conformité complète au schéma. `reconcile_tool_call` utilise les
[extracteurs communs](../constraints/README.md) pour rétablir les formes, jeux et
bornes reconnus. Une mention de niveau peut réorienter vers `pokemon_level_up_moves`.
Pour `pokemon_moves` et `pokemon_search`, la réconciliation conserve l'outil et
les filtres de capacités, restaure les bornes et exige `level-up`.
`pokemon_search` ne nécessite pas de Pokémon individuel dans la question.
Pour un numéro national explicite reconnu, le client rétablit `pokedex_number`
et redirige un choix de `pokemon_pokedex_identity` vers `pokemon_search`, en
retirant le nom d'espèce deviné. Sans outil de recherche compatible, l'appel est
refusé. L'identité conserve la direction nom → numéro ; la recherche fournit
numéro → Pokémon. Le guard ADK refuse l'outil incompatible et indique l'appel
à réessayer, sans le lancer lui-même.
Les instructions de formulation imposent les seuls noms français retournés
pour les listes structurées, sans détails non demandés ni exemples de capacités
déduits d'une recherche Pokémon. La limite de couverture est signalée brièvement,
sans liste d'exceptions sauf demande. Ces règles de prompt ne constituent pas
un contrôle déterministe de la réponse générée.
Une `ConstraintResolutionError` fait retourner à `ask` un message explicatif sans
appel d'outil ni formulation finale. Un intervalle impossible lève une `ValueError`
qui n'est pas convertie par ce mécanisme. Une erreur MCP
signalée par `is_error` empêche la formulation ; une réponse finale vide lève une erreur.

`open_client()` ouvre un contexte réutilisable : appeler `conversation.ask(question)`
pour chaque question dans ce contexte. Le catalogue est découvert une fois et les
modèles RAG restent disponibles dans le serveur après leur premier chargement.
Les questions sont indépendantes, sans mémoire conversationnelle. Le catalogue
n'est pas rafraîchi pendant la session ; rouvrir le contexte si les outils changent.

Les context managers ferment la session, le sous-processus et le client HTTP LLM,
y compris en cas d'erreur ou d'annulation. Une erreur arrête la boucle sans
reconnexion automatique. La fonction ponctuelle `ask(question)` conserve son
comportement : elle ouvre et ferme son propre contexte. La saisie du terminal
est attendue dans un thread pour laisser fonctionner la réception MCP.
Les appels OpenAI synchrones s'exécutent dans la coroutine ;
le client ne configure pas les délais et reprises de `config.py`. Les limites
ajoutées par les tests E2E ne sont donc pas celles de l'application.

## Portée et limites du contrôle

Les pertes de jeu, de forme et les confusions de capacité précédemment observées
motivent les régressions existantes. Le contrôle actuel porte sur les motifs
reconnus et les noms des paramètres des outils, sans validation sémantique complète.
Il exige aussi que le Pokémon proposé apparaisse après normalisation dans la
question. Les limites, notamment les formes multiples, sont décrites dans le
[guide des contraintes](../constraints/README.md). Les appels directs au serveur
ne passent pas par ce contrôle du client. La présence du contrôle ne prouve pas
la réussite des E2E avec Qwen ; voir les modalités de validation dans
[tests/README.md](../../../tests/README.md).

Deux cas demandent une attention particulière : le contrôle exige actuellement
un Pokémon même pour une recherche documentaire globale ; une question générale
sur la reproduction est donc refusée avant l'appel MCP. De plus, « dans la nature »
peut déclencher la détection d'un jeu non reconnu et bloquer une question de
comportement. Ces restrictions du client ne sont pas celles de l'outil RAG du serveur.

Garder stdout du serveur réservé au protocole ; envoyer les diagnostics sur stderr. La disponibilité du serveur dépend de la compatibilité de la version installée du SDK MCP avec ses imports. La recherche réelle nécessite également l'index et les modèles locaux.

Les diagnostics et barres de progression de l'initialisation RAG sont envoyés
sur stderr pour préserver stdout MCP. Un test avec modèles et collection simulés
vérifie cette séparation. Les coûts de chargement répétés
sont détaillés dans [Performance](../../../docs/PERFORMANCE.md).
