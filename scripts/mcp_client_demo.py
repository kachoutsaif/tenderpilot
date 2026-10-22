"""Un vrai client MCP, en quelques lignes : il fait exactement ce que fait Claude Desktop.

    python scripts/mcp_client_demo.py                 # liste les outils, puis 3 appels
    python scripts/mcp_client_demo.py 26-99151        # qualifie un autre avis

1. il LANCE le serveur comme sous-processus (transport stdio) ;
2. il ouvre une session et fait la poignée de main (initialize) ;
3. il demande la liste des outils (tools/list) : noms, descriptions, schémas JSON ;
4. il appelle des outils (tools/call), comme le ferait un LLM.
Aucun appel LLM n'est fait : les outils utilisés ici ne consomment pas de tokens.
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def show(result) -> None:
    # structured_content : le résultat en JSON, tel que l'outil l'a renvoyé
    data = result.structured_content
    if data is None:  # repli : le texte brut
        data = [getattr(block, "text", "") for block in result.content]
    print(json.dumps(data, ensure_ascii=False, indent=2)[:1500])


async def main(notice_id: str) -> None:
    server = StdioServerParameters(
        command=sys.executable, args=["-m", "tenderpilot.mcpserver.server"]
    )
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        print("=== Outils exposés par le serveur (ce que voit le LLM) ===")
        for tool in (await session.list_tools()).tools:
            first_line = (tool.description or "").strip().splitlines()[0]
            params = ", ".join(tool.input_schema.get("properties", {}))
            print(f"- {tool.name}({params})\n    {first_line}")

        print("\n=== rechercher_avis('nettoyage de vitres') ===")
        show(
            await session.call_tool("rechercher_avis", {"question": "nettoyage de vitres", "k": 3})
        )

        print(f"\n=== qualifier_avis('{notice_id}') ===")
        show(await session.call_tool("qualifier_avis", {"avis": notice_id}))

        print("\n=== lister_lecons() ===")
        show(await session.call_tool("lister_lecons", {}))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "26-98519"))
