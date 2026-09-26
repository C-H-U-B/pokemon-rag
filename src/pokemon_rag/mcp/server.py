from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from pokemon_rag.structured.query_engine import get_evolutions


mcp = MCPServer("Pokemon RAG")


@mcp.tool()
def pokemon_evolutions(
    pokemon: str,
    form: str | None = None,
    version_group: str | None = None,
) -> dict[str, Any]:
    """Retourne les évolutions connues d'un Pokémon.

    Args:
        pokemon: Nom français, anglais ou identifiant PokéAPI du Pokémon.
        form: Forme particulière du Pokémon, si nécessaire.
        version_group: Groupe de versions PokéAPI à utiliser comme filtre.
    """
    return get_evolutions(
        pokemon=pokemon,
        form=form,
        version_group=version_group,
    )

if __name__ == "__main__":
    mcp.run()