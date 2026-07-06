# 涩涩大富翁 MCP 使用说明

这个 MCP server 让支持 MCP 的客户端直接调用大富翁工具，不需要自己写 HTTP POST。

默认连接公开托管实例：

```text
https://spicy-monopoly.lol
```

也可以用环境变量切到自己的服务：

```bash
SPICY_MONOPOLY_BASE_URL=http://127.0.0.1:8069 node /path/to/spicy-monopoly/mcp-server.js
```

## 安装

需要 Node.js 18+。

```bash
git clone https://github.com/RennAkira/spicy-monopoly.git
cd spicy-monopoly
npm install
```

## 客户端配置

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

如果要连自建 API：

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

## 给 AI 的一句话

```text
请用 spicy-monopoly MCP 工具运行游戏。不要自己编骰子、任务、金币、赢家或隐藏位置。先 new_game，再每轮 roll，并严格按返回的 hint/action_needed 继续。跳过/换卡/终局等都用 game_action。
```

## 注意

- 任何人说 `404`、停、红线、不想做，AI 应该立刻用 `game_action` 的 `skip`，或停止游戏。
- `player_token` 用来列局/删局；跨局去重主要按玩家名字+性别+可选暗号自动识别。
- 公开托管实例有限流，公开分享时请提醒用户不要刷请求。
