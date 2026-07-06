#!/usr/bin/env node
import crypto from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod/v4";

const __dirname = dirname(fileURLToPath(import.meta.url));

const DEFAULT_BASE_URL = "https://spicy-monopoly.lol";
const BASE_URL = (process.env.SPICY_MONOPOLY_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, "");
const TIMEOUT_MS = Number.parseInt(process.env.SPICY_MONOPOLY_TIMEOUT_MS || "20000", 10);
const MCP_TRANSPORT = (process.env.SPICY_MONOPOLY_MCP_TRANSPORT || (process.argv.includes("--http") ? "http" : "stdio")).toLowerCase();
const MCP_HOST = process.env.SPICY_MONOPOLY_MCP_HOST || process.env.HOST || "127.0.0.1";
const MCP_PORT = Number.parseInt(process.env.SPICY_MONOPOLY_MCP_PORT || process.env.PORT || "3000", 10);
const MCP_PATH = process.env.SPICY_MONOPOLY_MCP_PATH || "/mcp";
const MCP_BEARER_TOKEN = process.env.SPICY_MONOPOLY_MCP_BEARER_TOKEN || "";
const MCP_ENABLE_JSON_RESPONSE = (process.env.SPICY_MONOPOLY_MCP_JSON_RESPONSE || "true").toLowerCase() !== "false";
const MCP_ALLOWED_HOSTS = (process.env.SPICY_MONOPOLY_MCP_ALLOWED_HOSTS || "")
  .split(",")
  .map((host) => host.trim())
  .filter(Boolean);

function ensureMcpAcceptHeader(req) {
  const desired = "application/json, text/event-stream";
  const accept = String(req.headers.accept || "");
  if (accept.includes("application/json") && accept.includes("text/event-stream")) return;

  req.headers.accept = desired;

  if (!Array.isArray(req.rawHeaders)) return;
  let found = false;
  for (let i = 0; i < req.rawHeaders.length; i += 2) {
    if (String(req.rawHeaders[i]).toLowerCase() === "accept") {
      req.rawHeaders[i + 1] = desired;
      found = true;
    }
  }
  if (!found) req.rawHeaders.push("Accept", desired);
}

function createSpicyMonopolyServer() {
  const server = new McpServer({
    name: "spicy-monopoly",
    title: "Spicy Monopoly",
    version: "0.1.0",
    description: "MCP tools for playing Spicy Monopoly through the public or self-hosted HTTP API.",
    websiteUrl: "https://github.com/RennAkira/spicy-monopoly",
  });
  registerSpicyMonopoly(server);
  return server;
}

function compact(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  return Object.fromEntries(Object.entries(value).filter(([, v]) => {
    if (v === undefined || v === null || v === "") return false;
    if (Array.isArray(v) && v.length === 0) return false;
    return true;
  }));
}

function normalizeSex(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["女", "female", "f", "woman", "girl"].includes(normalized)) return "女";
  if (["男", "male", "m", "man", "boy"].includes(normalized)) return "男";
  return value;
}

function normalizeRole(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["攻", "top", "seme", "dom", "dominant"].includes(normalized)) return "攻";
  if (["受", "bottom", "uke", "sub", "submissive"].includes(normalized)) return "受";
  return value;
}

function normalizeLineup(value) {
  const normalized = String(value || "").trim().toLowerCase().replace(/[\s_-]+/g, "");
  if (["男女", "mf", "fm", "malefemale", "femalemale"].includes(normalized)) return "男女";
  if (["男男", "mm", "malemale"].includes(normalized)) return "男男";
  if (["女女", "ff", "femalefemale"].includes(normalized)) return "女女";
  return value;
}

const argAliases = {
  gameid: "game_id",
  game_id: "game_id",
  playertoken: "player_token",
  player_token: "player_token",
  p1name: "p1_name",
  p1_name: "p1_name",
  p1sex: "p1_sex",
  p1_sex: "p1_sex",
  p1role: "p1_role",
  p1_role: "p1_role",
  p2name: "p2_name",
  p2_name: "p2_name",
  p2sex: "p2_sex",
  p2_sex: "p2_sex",
  p2role: "p2_role",
  p2_role: "p2_role",
  paircode: "pair_code",
  pair_code: "pair_code",
  firstplayer: "first_player",
  first_player: "first_player",
  setupconfirmed: "setup_confirmed",
  setup_confirmed: "setup_confirmed",
};

function aliasKey(key) {
  const normalized = String(key).replace(/[\s_-]+/g, "").toLowerCase();
  return argAliases[normalized] || key;
}

function normalizeQuery(value) {
  const normalized = String(value || "").trim().replace(/^\/+/, "").toLowerCase().replace(/[\s_-]+/g, "");
  const aliases = {
    state: "state",
    status: "state",
    shop: "shop",
    list: "list_games",
    games: "list_games",
    listgame: "list_games",
    listgames: "list_games",
    pairhistory: "pair_history",
    history: "pair_history",
  };
  return aliases[normalized] || value;
}

function normalizeAction(value) {
  const normalized = String(value || "").trim().replace(/^\/+/, "").toLowerCase().replace(/[\s_-]+/g, "");
  const aliases = {
    finalresult: "final_result",
    skip: "skip",
    swap: "swap",
    done: "done",
    paytoll: "pay_toll",
    duelresult: "duel_result",
    buyout: "buyout_super",
    buyoutsuper: "buyout_super",
    buycard: "buy_card",
    usecard: "use_card",
    discard: "discard_card",
    discardcard: "discard_card",
    buy: "buy_collectible",
    buycollectible: "buy_collectible",
    rerollidentity: "reroll_identity",
    rerolltask: "reroll_task",
    extratask: "extra_task",
    guessmark: "guess_mark",
    declarepersona: "declare_persona",
    idevent: "id_event",
  };
  return aliases[normalized] || value;
}

function normalizeToolArgs(args) {
  const normalized = {};
  for (const [key, value] of Object.entries(args || {})) {
    const canonicalKey = aliasKey(key);
    if (isBlank(value) && !isBlank(normalized[canonicalKey])) continue;
    normalized[canonicalKey] = value;
  }
  for (const key of ["p1_sex", "p2_sex"]) {
    if (normalized[key] !== undefined) normalized[key] = normalizeSex(normalized[key]);
  }
  for (const key of ["p1_role", "p2_role"]) {
    if (normalized[key] !== undefined) normalized[key] = normalizeRole(normalized[key]);
  }
  if (normalized.lineup !== undefined) normalized.lineup = normalizeLineup(normalized.lineup);
  if (normalized.query !== undefined) normalized.query = normalizeQuery(normalized.query);
  if (normalized.action !== undefined) normalized.action = normalizeAction(normalized.action);
  return normalized;
}

function isBlank(value) {
  return value === undefined || value === null || value === "";
}

function formatValue(value) {
  return typeof value === "string" ? `"${value}"` : JSON.stringify(value);
}

function invalidParam(name, value, allowed, hint = "") {
  const suffix = hint ? ` ${hint}` : "";
  throw new Error(`参数错误: \`${name}\` = ${formatValue(value)} 不支持。可用值: ${allowed.join(", ")}.${suffix}`);
}

function oneOf(args, name, allowed, { required: mustExist = false, hint = "" } = {}) {
  const value = args[name];
  if (isBlank(value)) {
    if (mustExist) throw new Error(`参数错误: 缺少必填参数 \`${name}\`.`);
    return undefined;
  }
  if (!allowed.includes(value)) invalidParam(name, value, allowed, hint);
  return value;
}

function numberParam(args, name, { min, max, int = false } = {}) {
  if (isBlank(args[name])) return undefined;
  const value = typeof args[name] === "number" ? args[name] : Number(args[name]);
  if (!Number.isFinite(value)) throw new Error(`参数错误: \`${name}\` 必须是数字，当前是 ${formatValue(args[name])}.`);
  if (int && !Number.isInteger(value)) throw new Error(`参数错误: \`${name}\` 必须是整数，当前是 ${formatValue(args[name])}.`);
  if (min !== undefined && value < min) throw new Error(`参数错误: \`${name}\` 不能小于 ${min}，当前是 ${value}.`);
  if (max !== undefined && value > max) throw new Error(`参数错误: \`${name}\` 不能大于 ${max}，当前是 ${value}.`);
  args[name] = value;
  return value;
}

function booleanParam(args, name) {
  if (isBlank(args[name])) return undefined;
  if (typeof args[name] === "boolean") return args[name];
  const value = String(args[name]).trim().toLowerCase();
  if (["true", "1", "yes", "y"].includes(value)) {
    args[name] = true;
    return true;
  }
  if (["false", "0", "no", "n"].includes(value)) {
    args[name] = false;
    return false;
  }
  throw new Error(`参数错误: \`${name}\` 必须是 true/false，当前是 ${formatValue(args[name])}.`);
}

function setupRequiredError(details) {
  const error = new Error([
    "开局前置步骤未完成：不要直接开局。",
    "你必须先向玩家说明游戏规则和安全规则，询问并确认设置，然后用 setup_confirmed=true 重新调用 new_game。",
    "至少要说明：金币/地盘胜负、攻受反转、安全词 404、skip/swap、身份可重抽；至少要询问：名字、性别、攻受、强度、红线、后庭/open_anal、纯 top/no_penetration、反转概率、回合数、身份模式、先手。",
  ].join("\n"));
  error.structuredContent = {
    setup_required: true,
    action_needed: "Explain rules and ask setup questions before starting. Then call new_game again with setup_confirmed=true.",
    ...details,
  };
  return error;
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

function pick(value, keys) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  return compact(Object.fromEntries(keys.map((key) => [key, value[key]])));
}

function slimCard(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  return pick(value, [
    "内容", "强度", "玩法类型", "target", "kink", "receiver", "reward",
    "完成奖励", "buyout", "mechanic", "差遣", "羞耻", "对决",
    "赌注", "判赢", "landlord", "fee", "serve_only", "options",
    "type", "stored", "msg",
    "name", "desc", "drawn", "effect", "fee", "owner", "winner", "loser",
    "super", "id", "title",
  ]);
}

function slimList(items, limit = 10) {
  if (!Array.isArray(items)) return items;
  return {
    count: items.length,
    items: items.slice(0, limit),
    truncated: items.length > limit,
  };
}

function slimData(data, context = {}) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return { result: data };

  const slim = {};
  const copyKeys = [
    "ok", "error", "msg", "logged", "muted",
    "game_id", "player_token", "who", "dice", "tile", "say", "settled",
    "result", "status", "history_note", "active_limits", "blocked_count",
    "action_needed", "hint", "next_turn", "identity_reminder",
    "feedback_prompt", "pair_history_key",
    "game_over", "jailed", "asleep", "in_jail",
    "turn", "positions", "coins", "laps",
    "theme", "price", "p1_owned", "p2_owned",
    "games_played", "tasks_remembered", "current_game_tasks", "dedup",
    "base_url", "flow", "host_guide", "setup_questions", "safety_rules",
    "turn_loop", "action_map", "mcp_resources",
  ];
  for (const key of copyKeys) {
    if (data[key] !== undefined && data[key] !== null && data[key] !== "") slim[key] = data[key];
  }

  for (const key of ["task", "truth", "duel", "toll", "mystery", "card"]) {
    if (data[key] !== undefined && data[key] !== null) slim[key] = slimCard(data[key]);
  }

  if (data.games) slim.games = slimList(data.games, 12);
  if (data.items) slim.items = slimList(data.items, 12);

  // The board is player-facing output, not debug noise: keep it so the host AI
  // can paste the current table to players after each turn/action.
  if (data.board) slim.board = data.board;

  // Full status is intentionally opt-in; ordinary roll/action calls stay small
  // while still carrying the rendered board above.
  if (context.tool === "game_info" && context.args?.query === "state") {
    if (data.status) slim.status = data.status;
  }
  if (context.tool === "game_info" && context.args?.query === "shop" && data.status) {
    slim.status = data.status;
  }

  return compact(slim);
}

function readable(data, context = {}) {
  const slim = slimData(data, context);
  const lines = [];
  for (const [key, value] of Object.entries(slim)) {
    lines.push(`${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`);
  }
  return lines.length ? lines.join("\n") : "{}";
}

function result(data, context = {}) {
  const structuredContent = slimData(data, context);
  return {
    content: [{ type: "text", text: readable(data, context) }],
    structuredContent,
  };
}

function errorResult(error) {
  const message = error instanceof Error ? error.message : String(error);
  const structuredContent = compact({
    ok: false,
    error: message,
    ...(error?.structuredContent && typeof error.structuredContent === "object" ? error.structuredContent : {}),
  });
  const response = {
    content: [{ type: "text", text: readable(structuredContent) }],
    structuredContent,
  };
  return response;
}

function registerSpicyMonopoly(server) {
  function tool(name, config, handler) {
    server.registerTool(name, config, async (args) => {
      try {
        const safeArgs = normalizeToolArgs(args || {});
        return result(await handler(safeArgs), { tool: name, args: safeArgs });
      } catch (error) {
        return errorResult(error);
      }
    });
  }

const strArray = z.array(z.string()).default([]);
const playerName = z.string().min(1);
const gameId = z.string().optional().describe("Required after new_game. Must be the exact game_id returned by new_game; do not invent one.");
const gameIdAlias = z.string().optional().describe("Alias for game_id. Prefer game_id when possible.");
const playerTokenAlias = z.string().optional().describe("Alias for player_token. Prefer player_token when possible.");
const who = z.string().min(1).describe("Exact player name as used in new_game.");
const sexInput = z.string()
  .describe("Allowed: 男 or 女. Also accepts male/female/m/f/man/woman/boy/girl and converts to 男/女.");
const roleInput = z.string()
  .describe("Allowed: 攻 or 受. Also accepts top/bottom/seme/uke/dom/sub and converts to 攻/受.");
const lineupInput = z.string()
  .describe("Allowed: 男女, 男男, 女女. Also accepts mf/fm/mm/ff and male-female/female-male/male-male/female-female.");
const lineups = ["男女", "男男", "女女"];
const sexes = ["男", "女"];
const roles = ["攻", "受"];
const flavors = ["light", "medium", "heavy"];
const identityModes = ["off", "mixed", "nsfw_only"];
const tollActions = ["pay", "serve"];
const taskActions = ["done", "skip"];
const superActions = ["done", "buyout"];
const guesses = ["大", "小"];
const gameActions = [
  "final_result",
  "skip", "swap", "done", "pay_toll", "duel_result", "buyout_super",
  "buy_card", "use_card", "discard_card", "buy_collectible",
  "reroll_identity", "reroll_task", "extra_task",
  "guess_mark", "declare_persona", "id_event",
];
const identityEvents = ["first_climax", "say_banned", "no_kiss_2turns"];
const infoQueries = ["state", "shop", "list_games", "pair_history"];
const adminActions = ["delete_game", "clear_pair_history", "submit_feedback"];
const feedbackKinds = ["bug", "idea", "feedback"];
const setupQuestions = [
  "Before new_game, explain: two-player board game, take turns rolling on a 20-tile board, do tasks to earn coins/territory, highest coins wins final command.",
  "Ask and confirm: player names, sex 男/女, role 攻/受, flavor light/medium/heavy, redlines, anal/open_anal, pure top/no_penetration, reverse_chance, game_length, identity_mode, first_player.",
  "Use real/unique player names. For default/common names, call game_info query=pair_history before new_game; if games_played is not expected, ask for a private pair_code instead of silently changing it.",
  "Tell players: coins come from tasks and passing start; completed tasks claim territory; stepping on opponent territory means pay toll or serve.",
  "Tell players: role reversal is an intentional surprise; set reverse_chance=0 if they do not want it.",
];
const safetyRules = [
  "Safety word 404: stop immediately, do not ask for justification.",
  "Players may skip any unwanted task for free: game_action action=skip with game_id and who.",
  "Players may swap an unwanted task before the next roll: game_action action=swap with game_id and who; costs 1 coin, limited uses.",
  "After new_game, read active_limits/history_note/identity_reminder and the board to players before the first roll.",
];
const turnLoop = [
  "Call roll with game_id only; never pass a player name to roll.",
  "Show the full board every turn unless players explicitly say not to.",
  "Read say/hint/task/truth/toll/duel/card/mystery to players and follow action_needed.",
  "Do not rush. Wait for players to say continue/next/ready before the next roll.",
  "If a task does not fit the current scene, preserve its strength/core kink and adapt it, or use game_action action=swap.",
  "Never invent dice, tasks, coins, winners, hidden marks, or state. If unsure or error, say so and call game_info query=state.",
];
const actionMap = {
  skip: "game_action {action:'skip', game_id, who}",
  swap: "game_action {action:'swap', game_id, who}",
  done: "game_action {action:'done', game_id, who}",
  toll: "roll settlement toll='pay' or toll='serve', or game_action action='pay_toll'",
  duel: "game_action {action:'duel_result', game_id, winner}",
  final: "game_action {action:'final_result', game_id}",
  cards: "game_action action='buy_card'/'use_card'/'discard_card', with who and index when needed",
  identity: "game_action action='reroll_identity'/'id_event'/'extra_task'/'guess_mark'/'declare_persona'",
};
const mcpResources = [
  "spicy-monopoly://manual/ai",
  "spicy-monopoly://manual/human",
  "spicy-monopoly://manual/api",
  "spicy-monopoly://readme",
];
const newGameHostGuide = [
  "You are the host and a participant, not just a tool caller. Use the engine for state, then roleplay only your own side.",
  "Before first roll, tell players the coin/territory win condition, role reversal rule, safety word 404, skip/swap options, and identity reroll option.",
  "Read active_limits, history_note, identity_reminder, and board from this new_game result to players.",
  "If history_note says this pair played before and players say that is wrong, stop before rolling. Ask for a unique pair_code or names, then start a new game with that pair_code.",
  "Every turn: call roll(game_id), paste board, read task/hint/action_needed, wait for players before rolling again.",
  "If anyone refuses/stops/says redline/404, use skip or stop immediately; do not argue.",
  "Never invent hidden state. On errors, show the parameter error and retry with corrected args.",
];
const newGameDescription = [
  "Start a new two-player game only after setup is explained and confirmed. If you only have the bare MCP URL, first call monopoly_help or use this description as the host manual.",
  "Before new_game, you MUST explain coin/territory win condition, role reversal, safety word 404, skip/swap, and identity reroll; ask player names, sex, role, flavor, redlines, anal/open_anal, pure top/no_penetration, reverse_chance, game_length, identity_mode, and first_player.",
  "Set setup_confirmed=true only after you have explained and asked those settings. If setup_confirmed is false/missing, this tool returns a setup_required error instead of starting.",
  "Required/important args: p1_name, p2_name, p1_sex, p2_sex, p1_role, p2_role.",
  "Use real/unique names for couple history. For default/common names, first call game_info with query=pair_history to show games_played; if that count surprises the players, ask for pair_code and pass it to new_game.",
  "After new_game, always read history_note to players. If it says prior games but players say this is not them, stop before the first roll and restart with a unique pair_code or names.",
  "Allowed values: lineup=男女/男男/女女 (also accepts mf/mm/ff or male-female); p*_sex=男/女 (also accepts male/female/m/f); p*_role=攻/受 (also accepts top/bottom); flavor=light/medium/heavy; identity_mode=off/mixed/nsfw_only.",
  "Optional setup: redline, open_anal, no_receive_anal, no_penetration are string arrays; game_length is integer 4-60; reverse_chance is 0-1.",
  "Do not invent game_id. Use the returned game_id for roll/game_action/game_info. Bad parameters return an explicit 参数错误 message.",
].join(" ");
const rollDescription = [
  "Advance the current turn. Required: game_id from new_game. Do not pass a player name; turn order is automatic.",
  "Optional settlement args only when the previous result asked for them: task=done/skip, toll=pay/serve, super_action=done/buyout, duel_winner=exact player name, guess=大/小, swap_identity=true/false.",
  "Call roll once per turn and show the returned board to players.",
].join(" ");
const actionDescription = [
  `Non-roll actions. Required: action and game_id. action must be one of: ${gameActions.join(", ")}.`,
  "Most actions also require who=exact player name. duel_result requires winner. use_card/discard_card require index. guess_mark requires spot. declare_persona requires persona. id_event requires event=first_climax/say_banned/no_kiss_2turns.",
  "Use skip immediately when a player refuses, says stop/redline/404, or does not want a task.",
].join(" ");
const infoDescription = [
  `Read-only queries. Required: query, one of: ${infoQueries.join(", ")}.`,
  "state/shop require game_id. list_games requires player_token. pair_history requires p1_name, p1_sex, p2_name, p2_sex, and optional pair_code.",
].join(" ");
const adminDescription = [
  `Rare admin/feedback actions. Required: action, one of: ${adminActions.join(", ")}.`,
  "delete_game requires game_id and player_token. clear_pair_history requires p1_name, p1_sex, p2_name, p2_sex, optional pair_code. submit_feedback accepts text, kind=bug/idea/feedback, optional game_id/player_token/mute.",
].join(" ");

tool("monopoly_help", {
  title: "玩法与 MCP 帮助",
  description: "MUST call this before hosting a game. Returns the compressed host manual: setup questions, safety rules, turn loop, MCP actions, and resource URIs for the full manuals.",
  annotations: { readOnlyHint: true, openWorldHint: true },
}, async () => ({
  base_url: BASE_URL,
  setup_questions: setupQuestions,
  safety_rules: safetyRules,
  turn_loop: turnLoop,
  action_map: actionMap,
  mcp_resources: mcpResources,
  flow: [
    "First explain the game, ask setup/safety questions, then call new_game.",
    "When and only when setup is explained and confirmed, call new_game with setup_confirmed=true.",
    "Read active_limits, history_note, identity_reminder, and board to players.",
    "Call roll for each turn. If the previous turn had pending work, pass task/toll/super_action/duel_winner only when the result asks for it.",
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
  description: newGameDescription,
  inputSchema: {
    lineup: lineupInput.default("男女"),
    flavor: z.string().default("medium").describe("Allowed: light, medium, heavy. Default medium."),
    p1_name: playerName.default("P1"),
    p1_sex: sexInput.default("男"),
    p1_role: roleInput.default("攻"),
    p2_name: playerName.default("P2"),
    p2_sex: sexInput.default("女"),
    p2_role: roleInput.default("受"),
    p1_color: z.string().default("🔵").describe("Short display marker for player 1."),
    p2_color: z.string().default("🔴").describe("Short display marker for player 2."),
    p1name: z.string().optional().describe("Alias for p1_name."),
    p1sex: sexInput.optional().describe("Alias for p1_sex."),
    p1role: roleInput.optional().describe("Alias for p1_role."),
    p2name: z.string().optional().describe("Alias for p2_name."),
    p2sex: sexInput.optional().describe("Alias for p2_sex."),
    p2role: roleInput.optional().describe("Alias for p2_role."),
    redline: strArray.describe("String array of excluded topics/terms. Keep empty unless players specify limits."),
    no_receive_anal: strArray.describe("String array of exact player names who must not receive this category. Legacy; defaults off unless opened."),
    open_anal: strArray.describe("String array of exact player names who explicitly allow this category. Empty means off for both players."),
    no_penetration: strArray.describe("String array of exact player names who are pure top this game."),
    theme: z.string().optional().describe("Optional short theme text."),
    reverse_chance: z.union([z.number(), z.string()]).default(0.3).describe("Number 0-1. Default 0.3."),
    identity_mode: z.string().default("mixed").describe("Allowed: off, mixed, nsfw_only. Default mixed."),
    game_length: z.union([z.number(), z.string()]).optional().describe("Optional integer 4-60 total turns."),
    player_token: z.string().optional().describe("Optional owner token for delete/list. Dedup does not rely on it."),
    playertoken: playerTokenAlias,
    pair_code: z.string().default("").describe("Optional private code to separate common names without changing displayed names."),
    paircode: z.string().optional().describe("Alias for pair_code."),
    reset_blocklist: z.union([z.boolean(), z.string()]).default(false).describe("Boolean true/false. Usually false."),
    first_player: z.string().default("").describe("Optional exact player name who rolls first."),
    firstplayer: z.string().optional().describe("Alias for first_player."),
    setup_confirmed: z.union([z.boolean(), z.string()]).default(false).describe("Required gate. Set true only after you explained rules/safety and confirmed setup with players; false/missing returns setup_required instead of starting."),
    setupconfirmed: z.union([z.boolean(), z.string()]).optional().describe("Alias for setup_confirmed."),
  },
  annotations: { destructiveHint: false, openWorldHint: true },
}, (args) => {
  oneOf(args, "lineup", lineups, { hint: "也接受 male-female/mf、male-male/mm、female-female/ff，会自动转换。" });
  oneOf(args, "flavor", flavors);
  oneOf(args, "p1_sex", sexes, { required: true, hint: "也接受 male/female/m/f，会自动转换。" });
  oneOf(args, "p2_sex", sexes, { required: true, hint: "也接受 male/female/m/f，会自动转换。" });
  oneOf(args, "p1_role", roles, { required: true, hint: "也接受 top/bottom，会自动转换。" });
  oneOf(args, "p2_role", roles, { required: true, hint: "也接受 top/bottom，会自动转换。" });
  oneOf(args, "identity_mode", identityModes);
  numberParam(args, "reverse_chance", { min: 0, max: 1 });
  numberParam(args, "game_length", { min: 4, max: 60, int: true });
  booleanParam(args, "reset_blocklist");
  booleanParam(args, "setup_confirmed");
  if (!args.setup_confirmed) {
    throw setupRequiredError({
      setup_questions: setupQuestions,
      safety_rules: safetyRules,
      turn_loop: turnLoop,
      action_map: actionMap,
      mcp_resources: mcpResources,
    });
  }
  return request("POST", "/new_game", args).then((data) => ({
    ...data,
    host_guide: newGameHostGuide,
  }));
});

tool("roll", {
  title: "掷骰 / 下一轮",
  description: rollDescription,
  inputSchema: {
    game_id: gameId,
    gameid: gameIdAlias,
    toll: z.string().optional().describe("Only if previous result asks for toll settlement. Allowed: pay, serve."),
    task: z.string().optional().describe("Only if previous task needs settlement. Allowed: done, skip."),
    super_action: z.string().optional().describe("Only if previous prompt asks. Allowed: done, buyout."),
    duel_winner: z.string().optional().describe("Exact winner player name, only when resolving a duel."),
    guess: z.string().optional().describe("Gambler guess before rolling. Allowed: 大 or 小."),
    swap_identity: z.union([z.boolean(), z.string()]).optional().describe("Boolean true/false, only when the previous result offers identity swap."),
  },
  annotations: { destructiveHint: false, openWorldHint: true },
}, ({ game_id, ...body }) => {
  required({ game_id }, "game_id");
  oneOf(body, "toll", tollActions);
  oneOf(body, "task", taskActions);
  oneOf(body, "super_action", superActions);
  oneOf(body, "guess", guesses);
  booleanParam(body, "swap_identity");
  return request("POST", `/roll/${encodeURIComponent(game_id)}`, body).catch((error) => ({
    ok: false,
    error: error instanceof Error ? error.message : String(error),
    action_needed: "Use the exact game_id returned by new_game. If you lost it or used an external id, call game_info query=list_games with player_token, or start a new game after setup_confirmed=true.",
  }));
});

const pairSchema = {
  p1_name: playerName,
  p1_sex: sexInput,
  p2_name: playerName,
  p2_sex: sexInput,
  pair_code: z.string().default(""),
};
const optionalPairSchema = {
  p1_name: z.string().optional(),
  p1_sex: sexInput.optional(),
  p2_name: z.string().optional(),
  p2_sex: sexInput.optional(),
  pair_code: z.string().default(""),
};
const optionalPairAliasSchema = {
  p1name: z.string().optional().describe("Alias for p1_name."),
  p1sex: sexInput.optional().describe("Alias for p1_sex."),
  p2name: z.string().optional().describe("Alias for p2_name."),
  p2sex: sexInput.optional().describe("Alias for p2_sex."),
  paircode: z.string().optional().describe("Alias for pair_code."),
};

function required(args, name) {
  if (args[name] === undefined || args[name] === null || args[name] === "") {
    throw new Error(`参数错误: 缺少必填参数 \`${name}\`${args.action || args.query ? `，当前操作是 ${args.action || args.query}` : ""}.`);
  }
  return args[name];
}

tool("game_action", {
  title: "游戏操作",
  description: actionDescription,
  inputSchema: {
    action: z.string().describe(`Action to run. Allowed: ${gameActions.join(", ")}.`),
    game_id: gameId,
    gameid: gameIdAlias,
    who: z.string().optional().describe("Player name, required by most actions."),
    winner: z.string().optional().describe("Winner name for duel_result."),
    index: z.union([z.string(), z.number()]).optional().describe("Card index or name for use_card/discard_card."),
    spot: z.string().optional().describe("Guessed body spot for guess_mark."),
    persona: z.string().optional().describe("Persona text for declare_persona."),
    event: z.string().optional().describe(`Identity event for id_event. Allowed: ${identityEvents.join(", ")}.`),
  },
  annotations: { destructiveHint: false, openWorldHint: true },
}, (args) => {
  oneOf(args, "action", gameActions, { required: true });
  const game = encodeURIComponent(required(args, "game_id"));
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
      oneOf(args, "event", identityEvents, { required: true });
      return request("POST", `/id_event/${game}/${player()}/${encodeURIComponent(required(args, "event"))}`);
    default:
      throw new Error(`Unsupported action: ${args.action}`);
  }
});

tool("game_info", {
  title: "游戏查询",
  description: infoDescription,
  inputSchema: {
    query: z.string().describe(`Query to run. Allowed: ${infoQueries.join(", ")}.`),
    game_id: z.string().optional(),
    gameid: gameIdAlias,
    player_token: z.string().optional(),
    playertoken: playerTokenAlias,
    ...optionalPairSchema,
    ...optionalPairAliasSchema,
  },
  annotations: { readOnlyHint: true, openWorldHint: true },
}, async (args) => {
  oneOf(args, "query", infoQueries, { required: true });
  switch (args.query) {
    case "state":
      try {
        return await request("GET", `/state/${encodeURIComponent(required(args, "game_id"))}`);
      } catch (error) {
        return {
          ok: false,
          error: error instanceof Error ? error.message : String(error),
          action_needed: "Use the exact game_id returned by new_game. If you do not have one, explain setup, call new_game with setup_confirmed=true, then use that game_id.",
        };
      }
    case "shop":
      try {
        return await request("GET", `/shop/${encodeURIComponent(required(args, "game_id"))}`);
      } catch (error) {
        return {
          ok: false,
          error: error instanceof Error ? error.message : String(error),
          action_needed: "Use the exact game_id returned by new_game before querying shop.",
        };
      }
    case "list_games":
      if (isBlank(args.player_token)) {
        return {
          ok: false,
          error: "player_token is required for list_games.",
          action_needed: "Do not use list_games to start a new game. If no player_token is available, call monopoly_help, explain setup, then call new_game with setup_confirmed=true.",
        };
      }
      return request("GET", "/games", undefined, { token: args.player_token });
    case "pair_history": {
      required(args, "p1_name");
      oneOf(args, "p1_sex", sexes, { required: true, hint: "也接受 male/female/m/f，会自动转换。" });
      required(args, "p2_name");
      oneOf(args, "p2_sex", sexes, { required: true, hint: "也接受 male/female/m/f，会自动转换。" });
      const key = pairHistoryKey(args);
      return { pair_history_key: key, ...(await request("GET", `/seen/${encodeURIComponent(key)}`)) };
    }
    default:
      throw new Error(`Unsupported query: ${args.query}`);
  }
});

tool("game_admin", {
  title: "管理与反馈",
  description: adminDescription,
  inputSchema: {
    action: z.string().describe(`Admin action. Allowed: ${adminActions.join(", ")}.`),
    game_id: z.string().optional(),
    gameid: gameIdAlias,
    player_token: z.string().optional(),
    playertoken: playerTokenAlias,
    text: z.string().optional(),
    kind: z.string().default("feedback"),
    mute: z.union([z.boolean(), z.string()]).default(false),
    ...optionalPairSchema,
    ...optionalPairAliasSchema,
  },
  annotations: { destructiveHint: true, openWorldHint: true },
}, async (args) => {
  oneOf(args, "action", adminActions, { required: true });
  oneOf(args, "kind", feedbackKinds);
  booleanParam(args, "mute");
  switch (args.action) {
    case "delete_game":
      return request("DELETE", `/game/${encodeURIComponent(required(args, "game_id"))}`, undefined, { token: required(args, "player_token") });
    case "clear_pair_history": {
      required(args, "p1_name");
      oneOf(args, "p1_sex", sexes, { required: true, hint: "也接受 male/female/m/f，会自动转换。" });
      required(args, "p2_name");
      oneOf(args, "p2_sex", sexes, { required: true, hint: "也接受 male/female/m/f，会自动转换。" });
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
  ["spicy-monopoly://manual/ai", "monopoly-给AI的操作手册.md", "完整荷官手册：开局说明、安全规则、回合节奏、身份/红线"],
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
  description: "Host prompt that tells the AI to read monopoly_help/manual rules before using MCP tools.",
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
        "First call monopoly_help and follow its setup_questions, safety_rules, turn_loop, and action_map. If resources are available, read spicy-monopoly://manual/ai.",
        "Before new_game, explain the coin/territory win condition, role reversal, safety word 404, skip/swap options, and ask setup/redlines.",
        "After new_game, read active_limits, history_note, identity_reminder, and board back to the players before the first roll.",
        "For each turn, call roll(game_id only), show board, follow hint/action_needed, then wait for players before rolling again.",
        "If a player says stop, redline, 404, or does not want a task, call game_action with action='skip' immediately without asking them to justify it.",
        player_names ? `Player/setup notes: ${player_names}` : "",
      ].filter(Boolean).join("\n"),
    },
  }],
}));
}

async function runStdio() {
  const server = createSpicyMonopolyServer();
  await server.connect(new StdioServerTransport());
}

function isAuthorized(req) {
  if (!MCP_BEARER_TOKEN) return true;
  return req.get("authorization") === `Bearer ${MCP_BEARER_TOKEN}`;
}

async function runHttp() {
  const app = createMcpExpressApp({
    host: MCP_HOST,
    allowedHosts: MCP_ALLOWED_HOSTS.length ? MCP_ALLOWED_HOSTS : undefined,
  });
  const sseTransports = new Map();

  app.use((req, res, next) => {
    res.setHeader("access-control-allow-origin", "*");
    res.setHeader("access-control-allow-methods", "GET, POST, DELETE, OPTIONS");
    res.setHeader("access-control-allow-headers", "authorization, content-type, mcp-protocol-version, mcp-session-id");
    if (req.method === "OPTIONS") {
      res.status(204).end();
      return;
    }
    next();
  });

  app.get("/", (_req, res) => {
    res.json({
      name: "spicy-monopoly",
      transport: "streamable-http",
      endpoint: MCP_PATH,
      mcp_url: `${MCP_PATH}`,
      api_base_url: BASE_URL,
    });
  });

  app.get("/healthz", (_req, res) => {
    res.json({ ok: true, api_base_url: BASE_URL });
  });

  app.post(MCP_PATH, async (req, res) => {
    if (!isAuthorized(req)) {
      res.status(401).json({
        jsonrpc: "2.0",
        error: { code: -32001, message: "Unauthorized" },
        id: null,
      });
      return;
    }

    ensureMcpAcceptHeader(req);

    const server = createSpicyMonopolyServer();
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
      enableJsonResponse: MCP_ENABLE_JSON_RESPONSE,
    });

    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
      res.on("close", () => {
        transport.close();
        server.close();
      });
    } catch (error) {
      console.error("Error handling MCP request:", error);
      transport.close();
      server.close();
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: "2.0",
          error: { code: -32603, message: "Internal server error" },
          id: null,
        });
      }
    }
  });

  async function handleLegacySse(_req, res) {
    const transport = new SSEServerTransport("/messages", res);
    sseTransports.set(transport.sessionId, transport);
    res.on("close", () => {
      sseTransports.delete(transport.sessionId);
    });
    const server = createSpicyMonopolyServer();
    await server.connect(transport);
  }

  app.get(MCP_PATH, async (req, res) => {
    try {
      await handleLegacySse(req, res);
    } catch (error) {
      console.error("Error handling legacy MCP SSE request:", error);
      if (!res.headersSent) res.status(500).send("Internal server error");
    }
  });

  app.get("/sse", async (req, res) => {
    try {
      await handleLegacySse(req, res);
    } catch (error) {
      console.error("Error handling legacy MCP SSE request:", error);
      if (!res.headersSent) res.status(500).send("Internal server error");
    }
  });

  app.post("/messages", async (req, res) => {
    const sessionId = String(req.query.sessionId || "");
    const transport = sseTransports.get(sessionId);
    if (!transport) {
      res.status(400).json({
        jsonrpc: "2.0",
        error: { code: -32000, message: "No legacy SSE transport found for sessionId." },
        id: null,
      });
      return;
    }
    await transport.handlePostMessage(req, res, req.body);
  });

  app.delete(MCP_PATH, (_req, res) => {
    res.status(405).json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Method not allowed in stateless MCP mode." },
      id: null,
    });
  });

  const httpServer = app.listen(MCP_PORT, MCP_HOST, () => {
    console.log(`Spicy Monopoly remote MCP listening on http://${MCP_HOST}:${MCP_PORT}${MCP_PATH}`);
    console.log(`Forwarding game API calls to ${BASE_URL}`);
  });

  httpServer.on("error", (error) => {
    console.error("Failed to start MCP HTTP server:", error);
    process.exit(1);
  });

  let shuttingDown = false;
  async function shutdown() {
    if (shuttingDown) return;
    shuttingDown = true;

    for (const transport of sseTransports.values()) {
      transport.close().catch((error) => {
        console.error("Error closing legacy SSE transport:", error);
      });
    }
    sseTransports.clear();

    httpServer.close(() => process.exit(0));
    httpServer.closeIdleConnections?.();
    const forceExit = setTimeout(() => {
      httpServer.closeAllConnections?.();
      process.exit(0);
    }, 5000);
    forceExit.unref();
  }

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

if (MCP_TRANSPORT === "http" || MCP_TRANSPORT === "streamable-http") {
  await runHttp();
} else if (MCP_TRANSPORT === "stdio") {
  await runStdio();
} else {
  console.error(`Unsupported SPICY_MONOPOLY_MCP_TRANSPORT: ${MCP_TRANSPORT}`);
  process.exit(1);
}
