# Google Tasks MCP Server

A Model Context Protocol (MCP) server for Google Tasks. Manage task lists and tasks through natural language in Claude Desktop and other MCP clients.

Forked from [zcaceres/gtasks-mcp](https://github.com/zcaceres/gtasks-mcp) with stronger auth options, multi-list support, pagination, and hierarchy tools.

![](https://badge.mcpx.dev?type=server "MCP Server")
[![npm version](https://img.shields.io/npm/v/@alvincrave/gtasks-mcp)](https://www.npmjs.com/package/@alvincrave/gtasks-mcp)
[![MCP Registry](https://img.shields.io/badge/MCP-Registry-blue)](https://registry.modelcontextprotocol.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**Registry name:** `io.github.alvinjchoi/gtasks-mcp`  
**npm:** [`@alvincrave/gtasks-mcp`](https://www.npmjs.com/package/@alvincrave/gtasks-mcp)

## Features

- List and search tasks (optionally scoped to one task list)
- Paginate through all tasks (no silent 100-task cap)
- Create, update, delete, and clear completed tasks
- Discover task lists (`list_task_lists`)
- View parent/child hierarchy (`list_with_tree`)
- Reorder, nest, or move tasks across lists (`move`)
- OAuth2 auth via env vars, credential files, or interactive `auth`
- Docker support

## Installation

Recommended (Claude Desktop / any MCP client) — runs the latest published npm package:

```bash
npx -y @alvincrave/gtasks-mcp
```

Or install globally:

```bash
npm install -g @alvincrave/gtasks-mcp
```

### From source

```bash
git clone https://github.com/alvinjchoi/gtasks-mcp.git
cd gtasks-mcp
npm install
npm run build
```

## Setup

### Option A — Environment variables (Claude Desktop)

1. Create a Google Cloud project and enable the **Google Tasks API**.
2. Create OAuth 2.0 Desktop credentials and obtain a refresh token (OAuth Playground with scope `https://www.googleapis.com/auth/tasks` works).
3. Configure Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "gtasks": {
      "command": "npx",
      "args": ["-y", "@alvincrave/gtasks-mcp"],
      "env": {
        "GOOGLE_CLIENT_ID": "your_client_id_here",
        "GOOGLE_CLIENT_SECRET": "your_client_secret_here",
        "GOOGLE_REFRESH_TOKEN": "your_refresh_token_here"
      }
    }
  }
}
```

### Option B — Credential files (local / shared with other Google MCP servers)

1. Download your OAuth client JSON (`gcp-oauth.keys.json`).
2. Authenticate once:

```bash
export GTASKS_CREDENTIALS_PATH=/path/to/gcp-oauth.keys.json
export GTASKS_TOKEN_PATH=/path/to/.gtasks-server-credentials.json
node dist/index.js auth
```

3. Run the server with the same env vars set (or place `gcp-oauth.keys.json` in the project root and use the defaults).

Aliases also accepted:

| Purpose | Preferred | Alias |
| --- | --- | --- |
| OAuth client keys | `GTASKS_CREDENTIALS_PATH` | `GOOGLE_OAUTH_KEYS_PATH` |
| Saved tokens | `GTASKS_TOKEN_PATH` | `GOOGLE_TASKS_CREDENTIALS_PATH` |

### Option C — Home config file

Create `~/.gtasks-credentials.json`:

```json
{
  "clientId": "your_client_id",
  "clientSecret": "your_client_secret",
  "refreshToken": "your_refresh_token"
}
```

## Tools

| Tool | Description |
| --- | --- |
| `search` | Search tasks by title/notes. Optional `taskListId`. |
| `list` | List tasks (all lists, or one via `taskListId`). Fully paginated. |
| `list_task_lists` | List task list names and IDs. |
| `list_with_tree` | Tree view for one list (parent/child, position order). |
| `move` | Reorder, nest/un-nest, or move across lists. |
| `create` | Create a task (`title` required; optional notes/due/`taskListId`). |
| `update` | Patch a task (only provided fields change). |
| `delete` | Delete a task. |
| `clear` | Clear completed tasks from a list. |

## Usage examples

```
show my task lists
list tasks in list <id>
search for tasks containing "meeting"
create a task named "Prepare presentation" due 2026-07-20
show the task tree for list <id>
move task <id> under parent <parentId>
mark task <id> completed
```

## Docker

```bash
docker build -t gtasks-mcp .
docker run -i \
  -e GOOGLE_CLIENT_ID=your_client_id \
  -e GOOGLE_CLIENT_SECRET=your_client_secret \
  -e GOOGLE_REFRESH_TOKEN=your_refresh_token \
  gtasks-mcp
```

## Development

```bash
npm install
npm run build
npm start
```

Auth check / interactive login:

```bash
npm run build
node dist/index.js auth
```

## Security Notes

- Treat refresh tokens like passwords
- Prefer env vars or ignored credential files — never commit them
- Rotate credentials if they leak

## Contributors

- [ArtyMcLabin](https://github.com/ArtyMcLabin) — pagination, `taskListId` filtering, `list_task_lists`, `list_with_tree`, `move`, and file-based auth ([#1](https://github.com/alvinjchoi/gtasks-mcp/pull/1))
- [zcaceres](https://github.com/zcaceres) — original Google Tasks MCP server
- [alvinjchoi](https://github.com/alvinjchoi) — fork maintenance, Smithery/npm packaging

See [CONTRIBUTORS.md](./CONTRIBUTORS.md).

## License

MIT
