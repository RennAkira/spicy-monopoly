#!/usr/bin/env node
import crypto from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod/v4";

const __dirname = dirname(fileURLToPath(import.meta.url));

const DEFAULT_BASE_URL = "https://spicy-monopoly.lol";
const BASE_URL = (process.env.SPICY_MONOPOLY_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, "");
const TIMEOUT_MS = Number.parseInt(process.env.SPICY_MONOPOLY_TIMEOUT_MS || "20000", 10);

const server = new McpServer({
  name: "spicy-monopoly",
  title: "Spicy Monopoly",
  version: "0.1.0",
  description: "MCP tools for playing Spicy Monopoly through the public or self-hosted HTTP API.",
  websiteUrl: "https://github.com/RennAkira/spicy-monopoly",
});

function compact(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  return Object.fromEntries(Object.entries(value).filter(([, v]) => {
    if (v === undefined || v === null || v === "") return false;
    if (Array.isArray(v) && v.length === 0) return false;
    return true;
  }));
}

function pairHistoryKey({ p1_name, p1_sex, p2_name, p2_sex, pair_code = "" }) {
  const players = [
    [String(p1_name), String(p1_sex)],
    [String(p2_name), String(p2_sex)],
  ].sort((a, b) => (a[0] === b[0] ? (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0) : (a[0] < b[0] ? -1 : 1)));
  const pair = [
    players,
    String(pair_code || ""),
  ];
  // Python backend uses json.dumps(..., ensure_ascii=False), whose default
  // separators include a space after commas and colons. Match it exactly so
  // MCP-side history tools open the same dedup drawer as /new_game.
  const pythonJson = JSON.stringify(pair).replace(/,/g, ", ").replace(/:/g, ": ");
  return "n_" + crypto
    .createHash("md5")
    .update(pythonJson)
    .digest("hex")
    .slice(0, 14);
}

function urlFor(path, query = undefined) {
  const url = new URL(path.startsWith("/") ? path : `/${path}`, `${BASE_URL}/`);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  return url;
}

async function request(method, path, body = undefined, query = undefined) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const headers = {};
    const init = { method, signal: controller.signal, headers };
    if (body !== undefined) {
      headers["content-type"] = "application/json";
      init.body = JSON.stringify(compact(body));
    }
    const response = await fetch(urlFor(path, query), init);
    const text = await response.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { text };
    }
    if (!response.ok) {
      const detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data);
      throw new Error(`HTTP ${response.status}: ${detail}`);
    }
    return data;
  } finally {
    clearTimeout(timeout);
  }
}

function readable(data) {
  const lines = [];
  if (data?.game_id) lines.push(`game_id: ${data.game_id}`);
  if (data?.player_token) lines.push(`player_token: ${data.player_token}`);
  if (data?.who) lines.push(`who: ${data.who}`);
  if (data?.settled) lines.push(`settled: ${data.settled}`);
  if (data?.say) lines.push(`say: ${data.say}`);
  if (data?.task) lines.push(`task: ${typeof data.task === "string" ? data.task : JSON.stringify(data.task, null, 2)}`);
  if (data?.truth) lines.push(`truth: ${JSON.stringify(data.truth, null, 2)}`);
  if (data?.duel) lines.push(`duel: ${JSON.stringify(data.duel, null, 2)}`);
  if (data?.toll) lines.push(`toll: ${JSON.stringify(data.toll, null, 2)}`);
  if (data?.mystery) lines.push(`mystery: ${JSON.stringify(data.mystery, null, 2)}`);
  if (data?.card) lines.push(`card: ${JSON.stringify(data.card, null, 2)}`);
  if (data?.result) lines.push(`result: ${typeof data.result === "string" ? data.result : JSON.stringify(data.result, null, 2)}`);
  if (data?.history_note) lines.push(`history_note: ${data.history_note}`);
  if (data?.active_limits) lines.push(`active_limits: ${typeof data.active_limits === "string" ? data.active_limits : JSON.stringify(data.active_limits, null, 2)}`);
  if (data?.hint) lines.push(`hint: ${data.hint}`);
  if (data?.next_turn) lines.push(`next_turn: ${data.next_turn}`);
  if (data?.board) lines.push(`board:\n${data.board}`);
  if (data?.status && !data?.board) lines.push(`status:\n${data.status}`);
  return lines.length ? lines.join("\n\n") : JSON.stringify(data, null, 2);
}

function result(data) {
  return {
    content: [
      { type: "text", text: readable(data) },
      { type: "text", text: `\nJSON:\n${JSON.stringify(data, null, 2)}` },
    ],
    structuredContent: data && typeof data === "object" && !Array.isArray(data) ? data : { result: data },
  };
}

function errorResult(error) {
  return {
    isError: true,
    content: [{ type: "text", text: error instanceof Error ? error.message : String(error) }],
  };
}

function tool(name, config, handler) {
  server.registerTool(name, config, async (args) => {
    try {
      return result(await handler(args || {}));
    } catch (error) {
      return errorResult(error);
    }
  });
}

const strArray = z.array(z.string()).default([]);
const playerName = z.string().min(1);
const gameId = z.string().min(1).describe("Game id returned by new_game.");
const who = z.string().min(1).describe("Player name exactly as used when starting the game.");

tool("monopoly_help", {
  title: "玩法与 MCP 帮助",
  description: "查看当前 MCP 接到哪个 API，以及推荐的工具调用流程。",
  annotations: { readOnlyHint: true, openWorldHint: true },
}, async () => ({
  base_url: BASE_URL,
  flow: [
    "Call new_game first. Read active_limits and history_note to players.",
    "Call roll for each turn. If the previous turn had pending work, pass task/toll/super_action/duel_winner in the next roll.",
    "Use game_action for side actions such as skip, swap, duel_result, cards, identity events, or final_result.",
    "Use game_info for read-only state/shop/list/history queries.",
    "Use game_admin only for delete, clear history, or voluntary feedback.",
  ],
  env: {
    SPICY_MONOPOLY_BASE_URL: "Optional. Defaults to https://spicy-monopoly.lol. Point it at your self-hosted API if needed.",
    SPICY_MONOPOLY_TIMEOUT_MS: "Optional HTTP timeout. Defaults to 20000.",
  },
}));

tool("new_game", {
  title: "开新局",
  description: "Create a new two-player game. The returned game_id is needed for later tools.",
  inputSchema: {
    lineup: z.enum(["男女", "男男", "女女"]).default("男女"),
    flavor: z.enum(["light", "medium", "heavy"]).default("medium"),
    p1_name: playerName.default("P1"),
    p1_sex: z.enum(["男", "女"]).default("男"),
    p1_role: z.enum(["攻", "受"]).default("攻"),
    p2_name: playerName.default("P2"),
    p2_sex: z.enum(["男", "女"]).default("女"),
    p2_role: z.enum(["攻", "受"]).default("受"),
    p1_color: z.string().default("🔵"),
    p2_color: z.string().default("🔴"),
    redline: strArray.describe("Kinks or switches to exclude, e.g. 后庭, 打, 绑, 玩具, 暴露, 羞辱, 失禁, 电."),
    no_receive_anal: strArray.describe("Players who must not receive anal. Mostly legacy; anal defaults off."),
    open_anal: strArray.describe("Players who explicitly allow receiving anal. Empty means anal is off for both players."),
    no_penetration: strArray.describe("Players who are pure top this game: no penetration of any hole."),
    theme: z.string().optional(),
    reverse_chance: z.number().min(0).max(1).default(0.3),
    identity_mode: z.enum(["off", "mixed", "nsfw_only"]).default("mixed"),
    game_length: z.number().int().min(4).max(60).optional(),
    player_token: z.string().optional().describe("Optional owner token for delete/list. Dedup does not rely on it."),
    pair_code: z.string().default("").describe("Optional private code to separate common names without changing displayed names."),
    reset_blocklist: z.boolean().default(false),
    first_player: z.string().default("").describe("Optional exact player name who rolls first."),
  },
  annotations: { destructiveHint: false, openWorldHint: true },
}, (args) => request("POST", "/new_game", args));

tool("roll", {
  title: "掷骰 / 下一轮",
  description: "Roll the current turn. Also settles prior pending task/toll/duel/super decisions.",
  inputSchema: {
    game_id: gameId,
    toll: z.enum(["pay", "serve"]).optional(),
    task: z.enum(["done", "skip"]).optional(),
    super_action: z.enum(["done", "buyout"]).optional(),
    duel_winner: z.string().optional(),
    guess: z.enum(["大", "小"]).optional(),
    swap_identity: z.boolean().optional(),
  },
  annotations: { destructiveHint: false, openWorldHint: true },
}, ({ game_id, ...body }) => request("POST", `/roll/${encodeURIComponent(game_id)}`, body));

const pairSchema = {
  p1_name: playerName,
  p1_sex: z.enum(["男", "女"]),
  p2_name: playerName,
  p2_sex: z.enum(["男", "女"]),
  pair_code: z.string().default(""),
};
const optionalPairSchema = {
  p1_name: z.string().optional(),
  p1_sex: z.enum(["男", "女"]).optional(),
  p2_name: z.string().optional(),
  p2_sex: z.enum(["男", "女"]).optional(),
  pair_code: z.string().default(""),
};

function required(args, name) {
  if (args[name] === undefined || args[name] === null || args[name] === "") {
    throw new Error(`${name} is required for ${args.action || args.query}`);
  }
  return args[name];
}

tool("game_action", {
  title: "游戏操作",
  description: "Single compact tool for non-roll gameplay actions: final_result, skip, swap, cards, identity events, mark guessing, etc.",
  inputSchema: {
    action: z.enum([
      "final_result",
      "skip", "swap", "done", "pay_toll", "duel_result", "buyout_super",
      "buy_card", "use_card", "discard_card", "buy_collectible",
      "reroll_identity", "reroll_task", "extra_task",
      "guess_mark", "declare_persona", "id_event",
    ]),
    game_id: gameId,
    who: z.string().optional().describe("Player name, required by most actions."),
    winner: z.string().optional().describe("Winner name for duel_result."),
    index: z.union([z.string(), z.number()]).optional().describe("Card index or name for use_card/discard_card."),
    spot: z.string().optional().describe("Guessed body spot for guess_mark."),
    persona: z.string().optional().describe("Persona text for declare_persona."),
    event: z.enum(["first_climax", "say_banned", "no_kiss_2turns"]).optional().describe("Identity event for id_event."),
  },
  annotations: { destructiveHint: false, openWorldHint: true },
}, (args) => {
  const game = encodeURIComponent(args.game_id);
  const player = () => encodeURIComponent(required(args, "who"));
  switch (args.action) {
    case "final_result":
      return request("GET", `/final_result/${game}`);
    case "skip":
      return request("POST", `/skip/${game}/${player()}`);
    case "swap":
      return request("POST", `/swap/${game}/${player()}`);
    case "done":
      return request("POST", `/done/${game}/${player()}`);
    case "pay_toll":
      return request("POST", `/pay_toll/${game}/${player()}`);
    case "duel_result":
      return request("POST", `/duel_result/${game}/${encodeURIComponent(required(args, "winner"))}`);
    case "buyout_super":
      return request("POST", `/buyout/${game}/${player()}`);
    case "buy_card":
      return request("POST", `/buy_card/${game}/${player()}`);
    case "use_card":
      return request("POST", `/use_card/${game}/${player()}/${encodeURIComponent(String(required(args, "index")))}`);
    case "discard_card":
      return request("POST", `/discard/${game}/${player()}/${encodeURIComponent(String(required(args, "index")))}`);
    case "buy_collectible":
      return request("POST", `/buy/${game}/${player()}`);
    case "reroll_identity":
      return request("POST", `/reroll_identity/${game}/${player()}`);
    case "reroll_task":
      return request("POST", `/reroll_task/${game}/${player()}`);
    case "extra_task":
      return request("POST", `/extra_task/${game}/${player()}`);
    case "guess_mark":
      return request("POST", `/guess_mark/${game}/${player()}/${encodeURIComponent(required(args, "spot"))}`);
    case "declare_persona":
      return request("POST", `/declare_persona/${game}/${player()}`, { persona: required(args, "persona") });
    case "id_event":
      return request("POST", `/id_event/${game}/${player()}/${encodeURIComponent(required(args, "event"))}`);
    default:
      throw new Error(`Unsupported action: ${args.action}`);
  }
});

tool("game_info", {
  title: "游戏查询",
  description: "Single read-only tool for state, shop, active game list, and pair history.",
  inputSchema: {
    query: z.enum(["state", "shop", "list_games", "pair_history"]),
    game_id: z.string().optional(),
    player_token: z.string().optional(),
    ...optionalPairSchema,
  },
  annotations: { readOnlyHint: true, openWorldHint: true },
}, async (args) => {
  switch (args.query) {
    case "state":
      return request("GET", `/state/${encodeURIComponent(required(args, "game_id"))}`);
    case "shop":
      return request("GET", `/shop/${encodeURIComponent(required(args, "game_id"))}`);
    case "list_games":
      return request("GET", "/games", undefined, { token: required(args, "player_token") });
    case "pair_history": {
      const key = pairHistoryKey(args);
      return { pair_history_key: key, ...(await request("GET", `/seen/${encodeURIComponent(key)}`)) };
    }
    default:
      throw new Error(`Unsupported query: ${args.query}`);
  }
});

tool("game_admin", {
  title: "管理与反馈",
  description: "Rare admin actions: delete a game, clear pair history, or submit voluntary feedback.",
  inputSchema: {
    action: z.enum(["delete_game", "clear_pair_history", "submit_feedback"]),
    game_id: z.string().optional(),
    player_token: z.string().optional(),
    text: z.string().optional(),
    kind: z.enum(["bug", "idea", "feedback"]).default("feedback"),
    mute: z.boolean().default(false),
    ...optionalPairSchema,
  },
  annotations: { destructiveHint: true, openWorldHint: true },
}, async (args) => {
  switch (args.action) {
    case "delete_game":
      return request("DELETE", `/game/${encodeURIComponent(required(args, "game_id"))}`, undefined, { token: required(args, "player_token") });
    case "clear_pair_history": {
      const key = pairHistoryKey(args);
      return { pair_history_key: key, ...(await request("DELETE", `/seen/${encodeURIComponent(key)}`)) };
    }
    case "submit_feedback":
      return request("POST", "/feedback", {
        text: args.text || "",
        kind: args.kind,
        game_id: args.game_id,
        player_token: args.player_token,
        mute: args.mute,
      });
    default:
      throw new Error(`Unsupported admin action: ${args.action}`);
  }
});

const manualFiles = [
  ["spicy-monopoly://manual/ai", "monopoly-给AI的操作手册.md", "给 AI 荷官/玩家的操作手册"],
  ["spicy-monopoly://manual/api", "monopoly-API使用手册.md", "HTTP API 使用手册"],
  ["spicy-monopoly://manual/human", "monopoly-怎么玩-人类版.md", "给人类玩家的玩法简介"],
  ["spicy-monopoly://readme", "README.md", "项目 README"],
];

for (const [uri, file, title] of manualFiles) {
  server.registerResource(file, uri, {
    title,
    description: `${title} (${file})`,
    mimeType: "text/markdown",
  }, async () => ({
    contents: [{
      uri,
      mimeType: "text/markdown",
      text: await readFile(join(__dirname, file), "utf8"),
    }],
  }));
}

server.registerPrompt("start_spicy_monopoly", {
  title: "开始一局色色大富翁",
  description: "A reusable host prompt that reminds the AI to use MCP tools instead of improvising game state.",
  argsSchema: {
    player_names: z.string().optional().describe("Optional player names or setup preferences."),
  },
}, ({ player_names = "" }) => ({
  messages: [{
    role: "user",
    content: {
      type: "text",
      text: [
        "Use the Spicy Monopoly MCP tools to run the game. Do not invent dice rolls, tasks, coins, winners, or hidden mark positions.",
        "First call monopoly_help if you need the flow, then call new_game with the players' setup.",
        "Read active_limits and history_note back to the players before the first roll.",
        "For each turn, call roll and follow its hint/action_needed fields.",
        "If a player says stop, redline, 404, or does not want a task, call game_action with action='skip' immediately without asking them to justify it.",
        player_names ? `Player/setup notes: ${player_names}` : "",
      ].filter(Boolean).join("\n"),
    },
  }],
}));

await server.connect(new StdioServerTransport());
