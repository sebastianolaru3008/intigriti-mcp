# intigriti-mcp

Model Context Protocol server for Intigriti researcher program data.

## Features

- Authenticate with an Intigriti researcher API PAT, an existing bearer token, or credential login where OIDC password grant is allowed.
- Cache the token in `./config/token.json` next to the server.
- List public and private programs available to your account.
- Cache the programs list in `./config/programs_cache.json`.
- Search programs by name/handle/id from cache first, fetching from the API only when needed.
- Fetch full program detail, domains/scope, rules of engagement, rewards, testing requirements, and activity updates.

## Install

```bash
cd /mnt/d/ctf/bugbounty/tools/intigriti-mcp
uv sync
```

Smoke test the server import:

```bash
uv run python -c 'import server; print("ok")'
```

## Add To Claude Code User Level

User-level MCP servers are available in every Claude Code project for your current OS user. Claude Code stores user-scoped MCP config in `~/.claude.json`.

Use the console script:

```bash
claude mcp add \
  --scope user \
  --transport stdio \
  intigriti \
  -- uv --directory /mnt/d/ctf/bugbounty/tools/intigriti-mcp run intigriti-mcp
```

Or use `server.py` directly:

```bash
claude mcp add \
  --scope user \
  --transport stdio \
  intigriti \
  -- uv --directory /mnt/d/ctf/bugbounty/tools/intigriti-mcp run server.py
```

Verify:

```bash
claude mcp list
claude mcp get intigriti
```

Inside Claude Code, run:

```text
/mcp
```

Then authenticate once:

```text
Call the intigriti authenticate tool with pat="<your Intigriti researcher PAT>"
```

## Authentication

Recommended:

```text
Call authenticate with pat="<your Intigriti researcher PAT>"
```

Other options:

```text
Call authenticate with access_token="<bearer token>"
Call authenticate with email="<email>", password="<password>", otp="<optional otp>"
```

The official researcher API documents PAT/Bearer auth. Credential auth uses Intigriti's OIDC password grant and may require `client_id`/`client_secret` depending on Intigriti's current identity configuration.

Environment variables also work:

```bash
export INTIGRITI_PAT=...
# or
export INTIGRITI_TOKEN=...
```

You can also register the token as an MCP environment variable instead of calling `authenticate`, but storing it through `authenticate` keeps the secret in `./config/token.json` next to this server:

```bash
claude mcp add \
  --scope user \
  --transport stdio \
  --env INTIGRITI_PAT=your_pat_here \
  intigriti \
  -- uv --directory /mnt/d/ctf/bugbounty/tools/intigriti-mcp run intigriti-mcp
```

## Add To Claude Desktop

Open Claude Desktop settings, go to Developer, and use **Edit Config**. Add this server under the top-level `mcpServers` key in `claude_desktop_config.json`.

macOS:

```text
~/Library/Application Support/Claude/claude_desktop_config.json
```

Windows:

```text
%APPDATA%\Claude\claude_desktop_config.json
```

Linux:

```text
~/.config/Claude/claude_desktop_config.json
```

Example config:

```json
{
  "mcpServers": {
    "intigriti": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "/mnt/d/ctf/bugbounty/tools/intigriti-mcp",
        "run",
        "intigriti-mcp"
      ],
      "env": {}
    }
  }
}
```

If `uv` is not on Claude Desktop's PATH, use the absolute path from:

```bash
which uv
```

Then restart Claude Desktop. The Intigriti tools should appear in Claude's tools/search menu. Authenticate with the `authenticate` tool or set `INTIGRITI_PAT` in the `env` object:

```json
{
  "mcpServers": {
    "intigriti": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "/mnt/d/ctf/bugbounty/tools/intigriti-mcp",
        "run",
        "intigriti-mcp"
      ],
      "env": {
        "INTIGRITI_PAT": "your_pat_here"
      }
    }
  }
}
```

## Tools

| Tool | Description |
| --- | --- |
| `authenticate` | Store PAT/token or attempt credential login |
| `list_programs` | List accessible programs with private/public filters |
| `search_program` | Search cache first, API second |
| `get_program` | Full program detail, scope/domains, rewards, rules |
| `get_program_domains` | Get a specific/current domains version |
| `get_program_rules` | Get a specific/current rules-of-engagement version |
| `get_program_activities` | List program activity changes |
| `clear_cache` | Remove local programs cache |

## Notes

Intigriti uses GUID program IDs in the researcher API. This server accepts IDs, handles, exact names, and unambiguous partial names by resolving them through the cached program list.

The server uses stdio transport, which is the local MCP transport expected by Claude Code and Claude Desktop for this kind of Python MCP server.
# intigriti-mcp
