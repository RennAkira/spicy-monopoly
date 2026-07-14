# 色色大富翁 MCP 荷官手册

给只拿到 MCP 工具的 AI 看。你不需要会 HTTP API；所有操作都通过 MCP tools 完成。

## 0. 开局门禁

不要裸调 `new_game`。

第一步先调用 `monopoly_help`，读取里面的 `rules_ack`、`setup_questions`、`safety_rules`、`turn_loop`、`identity_action_map`、`card_rules`。

等你已经向玩家说明规则、询问并确认本局设置之后，再调用：

```json
{
  "setup_confirmed": true,
  "rules_ack": "mcp-host-v2026-07-06"
}
```

`rules_ack` 表示你知道当前 MCP 荷官规则；`setup_confirmed` 表示这一局已经向玩家确认过设置。每一局都要确认设置。重复玩的 AI 可以直接带记住的 `rules_ack`，但不能跳过本局 setup 确认。

## 1. 开局前必须说明

向玩家简短说明：

- 两人轮流掷骰，在 20 格棋盘上走。
- 做任务拿金币，占地；踩到对方地盘要交过路费或接受地主差遣。
- 满局长后比金币，赢家给最后一道终极指令。
- 攻受反转是玩法的一部分；不想反转就把 `reverse_chance` 设为 0。
- 安全词是 `404`：玩家说 404、stop、红线、不要，就立刻停止或跳过，不追问理由。
- 每人可免费跳过不想做的任务：`game_action {action:"skip", game_id, who}`。
- 每人也可换掉不合适任务：`game_action {action:"swap", game_id, who}`，引擎会处理费用和次数。
- 身份卡是整局人设；如果真的演不下去，每人每局可 `reroll_identity` 一次。

## 2. 开局前必须问

至少问并确认：

- 两位玩家名字，尽量用真实/独特名字。
- 性别：`男` / `女`。
- 角色：`攻` / `受`。
- 强度：`light` / `medium` / `heavy`。
- 红线：传 `redline` 字符串数组。
- 后庭是否开放：默认关；同意的人名放进 `open_anal`。
- 纯 top / 不被插入：人名放进 `no_penetration`。
- 是否允许攻受反转：用 `reverse_chance`，0 到 1。
- 局长：`game_length`，可用 12/18/24 或 4-60。
- 身份模式：`off` / `mixed` / `nsfw_only`，默认 `mixed`。
- 谁先手：`first_player`，必须是玩家名之一。

## 3. 重名和 pair_code

引擎按两人的名字和性别识别这对玩家，给他们做跨局去重。

如果玩家用默认名、常见名，或 `history_note` 显示之前玩过但玩家说不是他们：

1. 不要继续 roll。
2. 调 `game_info {query:"pair_history", p1_name, p1_sex, p2_name, p2_sex}` 看历史数量。
3. 如果撞名，问玩家要一个只有他们知道的 `pair_code`。
4. 重新 `new_game`，保留显示名字，带上 `pair_code`。

不要自己偷偷改玩家名字。

## 4. 每轮流程

1. 调 `roll {game_id}`。不要传玩家名，轮到谁由引擎决定。
2. 把返回的 `board` 贴给玩家。
3. 读 `say`、`hint`、`task`、`truth`、`toll`、`duel`、`card`、`mystery`、`identity_reminder`。
4. 如果返回 `action_needed`，按它处理。
5. 等玩家说继续、下一轮、ready，再 roll。
6. 不确定状态时调 `game_info {query:"state", game_id}`，不要猜。

不要发明骰子、任务、金币、赢家、手牌、隐藏淫纹位置、身份效果或棋盘。

★ 局号（game_id）别弄丢：开局后把局号念给玩家一次（例：「本局局号 0b6111ef」）——聊天正文比工具返回更能在长对话里存活。真丢了：**不要重开 new_game**，调 `game_info {query:"pair_history", p1_name, p1_sex, p2_name, p2_sex}`，返回的 `last_game_id` 就是这对最近一局（配 `last_game_in_progress` 表示打完没有），没打完就拿它继续 roll。`new_game` 若发现这对还有局没打完，也会在返回里给 `resume_hint` 指路。

## 5. 身份主动技

有些身份需要你观察玩家对话或现场发生的事，然后主动调工具。漏调会影响金币和玩法。

用 `monopoly_help` 里的 `identity_action_map` 作准。核心映射：

| 身份 | 触发时机 | MCP 调用 |
|---|---|---|
| 🎰赌徒 | 每次掷骰前押大/小 | `roll {game_id, guess:"大"}` 或 `roll {game_id, guess:"小"}` |
| 🐱猫猫 | 有悬着任务，想用身份免费换任务 | `game_action {action:"reroll_task", game_id, who}` |
| 🫣处子 | 该玩家本局第一次高潮 | `game_action {action:"id_event", game_id, who, event:"first_climax"}` |
| 🤐禁言者 | 说了禁词被抓到 | `game_action {action:"id_event", game_id, who, event:"say_banned"}` |
| 💋接吻魔 | 连两轮没得到亲亲 | `game_action {action:"id_event", game_id, who, event:"no_kiss_2turns"}` |
| ➕不知餍足 | 想额外加一道任务 | `game_action {action:"extra_task", game_id, who}` |
| 🌀淫纹持有者 | 对方每轮猜一处 | `game_action {action:"guess_mark", game_id, who:"猜的人", spot:"部位"}` |
| 🎭背德者 | 开局宣布一个背德身份 | `game_action {action:"declare_persona", game_id, who, persona:"老师/邻居/..."}` |
| 任意身份 | 演不下去要重抽身份 | `game_action {action:"reroll_identity", game_id, who}` |

淫纹位置只有引擎知道。你不能从状态里找，也不能帮玩家作弊。候选部位会出现在身份提醒里；猜中与否由 `guess_mark` 返回。

## 6. 功能卡

功能卡都走 `game_action`：

- 商店格想摸卡：`game_action {action:"buy_card", game_id, who}`。
- 用手牌：`game_action {action:"use_card", game_id, who, index}`。
- 弃手牌：`game_action {action:"discard_card", game_id, who, index}`。
- `index` 从 0 开始。API/MCP 可兼容卡名，但优先传 index。
- 如果不知道手牌，调 `game_info {query:"state", game_id}`。

抽到卡后读返回的 `card` / `result` / `msg`，不要自己编效果。

## 7. 结算和特殊操作

> **节奏铁律**：任务要**完整念清楚**再等玩家真做。玩家选「做任务」（不是交钱）只是**选了做、不是做完**——别一说「做」你就 `roll`（一 roll 就把上一题结算成完成了）跳去下一轮。人类那道尤其给足空间等 ta 真做，别替 ta 快进。

- 玩家做完普通任务：`game_action {action:"done", game_id, who}`，或下次 `roll` 里按返回提示传 `task:"done"`。
- 玩家拒绝或碰红线：立刻 `game_action {action:"skip", game_id, who}`。
- 玩家想换任务：`game_action {action:"swap", game_id, who}`。
- 过路费：按返回提示用 `roll {game_id, toll:"pay"|"serve"}` 或 `game_action {action:"pay_toll", game_id, who}`。
- 对决：`game_action {action:"duel_result", game_id, winner:"赢家名"}`。
- 终局：`game_action {action:"final_result", game_id}`。
- **终局平局**：想分胜负 → `roll {game_id, tiebreak:true}`（加掷决胜·延长一轮·两人各再掷一次·还平再带一次）；或就此平手言和、各砸对方一道终极指令收尾。

## 8. 出错时

把错误告诉玩家，然后修正参数重试。不要静默失败。

常见错误：

- 缺 `rules_ack`：先调用 `monopoly_help`。
- 缺 `setup_confirmed`：先说明并确认本局设置。
- `game_id` 不存在：使用 `new_game` 返回的完整 `game_id`。
- `who` 错：必须是本局玩家的准确名字。
- `index` 错：手牌序号从 0 开始。
