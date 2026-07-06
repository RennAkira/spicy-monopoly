# 涩涩大富翁 MCP 使用说明

这个 MCP server 让支持 MCP 的客户端直接调用大富翁工具，不需要自己写 HTTP POST。

它有两种模式：

- **远程 MCP**：玩家只在客户端里填一个 MCP URL，不需要 clone / npm install。
- **本地 stdio MCP**：玩家在自己电脑上 clone 仓库，适合还不支持远程 MCP 的客户端。

无论哪种模式，默认都会把游戏请求转发到公开托管 API：

```text
https://spicy-monopoly.lol
```

## 玩家接入远程 MCP

官方公开远程 MCP 地址：

```text
https://spicy-monopoly.lol/mcp
```

如果客户端支持远程 MCP / Streamable HTTP MCP，把这个 URL 填进去即可。
这个地址同时兼容较新的 Streamable HTTP 和旧式 HTTP+SSE 客户端；如果客户端明确要求 SSE URL，也填同一个 `/mcp`。

有些客户端用 JSON 配置，通常长这样：

```json
{
  "mcpServers": {
    "spicy-monopoly": {
      "url": "https://spicy-monopoly.lol/mcp"
    }
  }
}
```

自建远程 MCP 时，把 URL 换成自己的域名：

```json
{
  "mcpServers": {
    "spicy-monopoly": {
      "url": "https://你的域名/mcp"
    }
  }
}
```

如果服务方设置了访问 token，客户端还需要带请求头：

```json
{
  "mcpServers": {
    "spicy-monopoly": {
      "url": "https://你的域名/mcp",
      "headers": {
        "Authorization": "Bearer 服务方给你的token"
      }
    }
  }
}
```

## 服务方部署远程 MCP

需要 Node.js 18+。

```bash
git clone https://github.com/RennAkira/spicy-monopoly.git
cd spicy-monopoly
npm install
npm run mcp:http
```

默认监听：

```text
http://127.0.0.1:3000/mcp
```

公开部署时一般要绑定到 `0.0.0.0`，并让平台提供 HTTPS 域名：

```bash
SPICY_MONOPOLY_MCP_HOST=0.0.0.0 PORT=3000 npm run mcp:http
```

常用环境变量：

| 变量 | 作用 |
|---|---|
| `SPICY_MONOPOLY_MCP_TRANSPORT` | `stdio` 或 `http`。也可以用 `node mcp-server.js --http`。 |
| `SPICY_MONOPOLY_MCP_HOST` | HTTP 监听地址，公开部署常用 `0.0.0.0`。 |
| `SPICY_MONOPOLY_MCP_PORT` / `PORT` | HTTP 端口，默认 `3000`。 |
| `SPICY_MONOPOLY_MCP_PATH` | MCP 路径，默认 `/mcp`。 |
| `SPICY_MONOPOLY_MCP_ALLOWED_HOSTS` | 可选，逗号分隔的 Host 白名单。 |
| `SPICY_MONOPOLY_MCP_BEARER_TOKEN` | 可选，设置后远程客户端必须带 `Authorization: Bearer ...`。 |
| `SPICY_MONOPOLY_MCP_JSON_RESPONSE` | 可选，默认 `true`，远程 MCP 用普通 JSON 响应；设为 `false` 才用 SSE 响应。 |
| `SPICY_MONOPOLY_BASE_URL` | 可选，默认转发到 `https://spicy-monopoly.lol`；自建 API 时改成自己的 API。 |
| `SPICY_MONOPOLY_TIMEOUT_MS` | 可选，转发 API 的超时时间，默认 `20000`。 |

自建 API + 远程 MCP 的例子：

```bash
SPICY_MONOPOLY_BASE_URL=https://api.example.com \
SPICY_MONOPOLY_MCP_HOST=0.0.0.0 \
PORT=3000 \
npm run mcp:http
```

## 本地 stdio MCP

如果客户端还不支持远程 MCP，可以用本地 stdio 方式。

```bash
git clone https://github.com/RennAkira/spicy-monopoly.git
cd spicy-monopoly
npm install
```

把下面配置加到支持 MCP 的客户端里，路径换成你本机仓库路径：

```json
{
  "mcpServers": {
    "spicy-monopoly": {
      "command": "node",
      "args": ["/ABSOLUTE/PATH/TO/spicy-monopoly/mcp-server.js"]
    }
  }
}
```

本地 stdio 想连自建 API：

```json
{
  "mcpServers": {
    "spicy-monopoly": {
      "command": "node",
      "args": ["/ABSOLUTE/PATH/TO/spicy-monopoly/mcp-server.js"],
      "env": {
        "SPICY_MONOPOLY_BASE_URL": "http://127.0.0.1:8069"
      }
    }
  }
}
```

## 工具入口

- `monopoly_help`：查看当前连接的 API 和推荐流程。
- `new_game`：开局，返回 `game_id` 和 `player_token`。
- `roll`：每轮掷骰，也会结算上一轮悬着的任务/过路费/对决。
- `game_action`：所有非掷骰玩法操作，例如 `skip`、`swap`、`duel_result`、`final_result`、功能卡、身份事件、淫纹猜测。
- `game_info`：只读查询，例如 `state`、`shop`、`list_games`、`pair_history`。
- `game_admin`：少用的管理动作，例如 `delete_game`、`clear_pair_history`、`submit_feedback`。

MCP 菜单刻意压到 6 个工具，避免客户端每轮都把一大串细碎工具 schema 塞进上下文。完整能力仍在 `game_action` / `game_info` / `game_admin` 的 `action` 或 `query` 参数里。

工具返回也默认瘦身：普通开局、掷骰、操作只返回 AI 下一步必须用的字段，不附完整后端 JSON，也不每轮塞棋盘大块；需要完整局面时再调用 `game_info` 的 `state`。

## 给 AI 的一句话

```text
请用 spicy-monopoly MCP 工具运行游戏。不要自己编骰子、任务、金币、赢家或隐藏位置。先 new_game，再每轮 roll，并严格按返回的 hint/action_needed 继续。跳过/换卡/终局等都用 game_action。
```

## 注意

- 任何人说 `404`、停、红线、不想做，AI 应该立刻用 `game_action` 的 `skip`，或停止游戏。
- `player_token` 用来列局/删局；跨局去重主要按玩家名字+性别+可选暗号自动识别。
- 公开托管实例有限流，公开分享时请提醒用户不要刷请求。
