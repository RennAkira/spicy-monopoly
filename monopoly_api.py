#!/usr/bin/env python3
"""
涩涩大富翁 API 服务
FastAPI 包装 monopoly_play.Game，提供 HTTP 接口。

启动：uvicorn monopoly_api:app --host 0.0.0.0 --port 8069
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from pathlib import Path
import json, uuid, hashlib

from monopoly_play import Game, GAMES_CAP, REDLINE_SWITCHES, LIB, _atomic_write, _dedup_last

# redline 合法词表(开放加固):开关名 + 中文标签 + 库里真实 kink 标签。
# 之外的词=八成拼错(想禁"anal"打成"anla"→静默无保护=安全洞)·new_game 直接 422 别静默吞。
_VALID_REDLINE = set(REDLINE_SWITCHES) | {v for vs in REDLINE_SWITCHES.values() for v in vs} | {
    k for t in LIB for k in (t.get("kink") or [])
}

app = FastAPI(title="涩涩大富翁 API", version="0.1.0")

# CORS:让浏览器里的本地 playtest.html 能直接 fetch 本 API(要 playtest 页连真引擎)。
# 门票本来就是 URL 里那串 token(谁有 URL 都能 curl),开 CORS 只是让浏览器也能调·不引入新的暴露面。
# 不用 credentials(鉴权在 URL path·非 cookie),所以 allow_origins 可以用 "*"。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GAMES_DIR = Path(__file__).parent / "monopoly-games"
GAMES_DIR.mkdir(exist_ok=True)
SEEN_DIR = Path(__file__).parent / "monopoly-seen"   # 跨局记忆:每个玩家令牌一个抽屉
SEEN_DIR.mkdir(exist_ok=True)


# ── Models ──

class NewGameRequest(BaseModel):
    lineup: str = "男女"
    flavor: str = "medium"
    p1_name: str = "P1"
    p1_sex: str = "男"
    p1_role: str = "攻"
    p2_name: str = "P2"
    p2_sex: str = "女"
    p2_role: str = "受"
    p1_color: str = "🔵"
    p2_color: str = "🔴"
    redline: list[str] = []
    no_receive_anal: list[str] = []      # 单方面「只给不收后庭」的人名(某人不被肛·对方仍可)。补:之前 API 层漏了这字段=安全参数失效。
    open_anal: list[str] = []            # ★后庭默认关·要玩后庭的人名填这里开(每人独立)。不填=两人都不玩后庭。
    no_penetration: list[str] = []       # ★当纯top的人名·任何孔[阴道+后穴]都不被插。给「女女局想当纯top」用(禁后庭挡不住阴道)。不填=都可被插。
    theme: Optional[str] = None
    reverse_chance: float = 0.3
    identity_mode: str = "mixed"         # 身份三档:off(不发)/mixed(30全池·默认)/nsfw_only(只发NSFW14)
    game_length: Optional[int] = None    # 局长(总回合数):速玩12/正常18/超长24(不传=24)。escalate曲线按局长自适应(短局爬得陡)
    player_token: Optional[str] = None   # 鉴权令牌(删局/看局);去重不靠它
    pair_code: str = ""                  # 暗号:撞名了不用改名·加个独特暗号就跟别人分开(默认空·同名字+性别自动认)
    reset_blocklist: bool = False        # ★洗白这对的永久黑名单(swap拉黑错了·想恢复全部被换掉的卡)
    first_player: str = ""               # ★谁先掷骰(默认p1_name先手)·想让AI/某人先手就填ta的名字(必须是两个玩家名之一)

class RollRequest(BaseModel):
    """掷骰时一行带上悬账决定(傻瓜命令行要能吃参数,金币变化别再额外跑命令)。全部可选,不传=默认。"""
    toll: Optional[str] = None         # 悬着的过路费:"pay"交钱(默认·不传也是它) / "serve"差遣抵扣(做了地主那道·不扣钱)
    task: Optional[str] = None         # 悬着的普通任务:"done"照做给币(默认) / "skip"跳过不给币
    super_action: Optional[str] = None # 悬着的超级任务:"done"做完+5币(默认) / "buyout"花8币不做
    duel_winner: Optional[str] = None  # 悬着的对决:报赢家名(有对决悬着时必传,赌注不许蒸发)
    guess: Optional[str] = None        # 🎰赌徒押大小:"大"/"小"(只赌徒身份有效·别的身份自动忽略)
    swap_identity: Optional[bool] = None  # 机会格保留了新身份·这轮想改主意换掉(任期保护:<3轮默认保留)

class PersonaRequest(BaseModel):
    persona: str                       # 🎭背德者自己宣布的背德身份文本(老师/邻居/还俗的和尚…)

class UseItemRequest(BaseModel):
    who: str
    item: str


# ── Helpers ──

def _path(game_id: str) -> Path:
    return GAMES_DIR / f"{game_id}.json"

def _load(game_id: str) -> Game:
    p = _path(game_id)
    if not p.exists():
        raise HTTPException(404, f"游戏 {game_id} 不存在")
    return Game.load(str(p))

def _save(game_id: str, g: Game):
    g.save(str(_path(game_id)))


# ── 跨局记忆:每玩家令牌一个抽屉 seen/<token>.json = {"games":[最近≤10局],"last_game_id":..} ──

def _token_path(token: str) -> Path:
    return SEEN_DIR / f"{token}.json"

def _load_token(token: str) -> dict:
    p = _token_path(token)
    if p.exists():
        try:
            d = json.loads(p.read_text("utf-8"))
            if "recency" in d:                                   # 新格式(LRU 去重)
                recency = list(d.get("recency", [])); gc = int(d.get("game_count", 0))
            else:                                                # 兼容旧 {"games":[..最近10局]}→拍平成 recency·count=局数
                games = list(d.get("games", []))
                recency = _dedup_last([t for g in games for t in g]); gc = int(d.get("game_count", len(games)))
            return {"recency": recency, "game_count": gc, "last_game_id": d.get("last_game_id"),
                    "identities": list(d.get("identities", [])),
                    "blocklist": list(d.get("blocklist", [])),   # swap换掉的永久黑名单(硬排除永不出)
                    "folded": list(d.get("folded", []))}   # folded=已折的game_id(防重折)·identities=身份跨局去重(独立子系统·不动)
        except Exception:
            pass
    return {"recency": [], "game_count": 0, "last_game_id": None, "identities": [], "blocklist": [], "folded": []}

def _save_token(token: str, rec: dict):
    _atomic_write(_token_path(token), json.dumps(rec, ensure_ascii=False))

IDENTITIES_KEPT = 8   # 身份跨局躲避:记最近 8 个(池 30 躲 8 剩 22+,不饿死)

def _fold_game_into(rec: dict, g, game_id: str):
    # 把这局的 history/身份 折进去重池(folded防重折)。终局(final_result)+下一局开局 都调·哪个先到都不重复折·删局也不丢历史。
    folded = rec.setdefault("folded", [])
    if not game_id or game_id in folded or not (g and getattr(g, "history", None)):
        return
    rec["recency"] = _dedup_last(list(rec.get("recency", [])) + list(g.history))   # 这局用过的挪到最新端(LRU·自然被库封顶·不随局数无限涨)
    rec["game_count"] = int(rec.get("game_count", 0)) + 1                          # 局数只增(透明化撞名用·跟去重无关)
    ids = [v.get("name") for v in g.identity.values() if v and v.get("name")]
    if ids:
        rec["identities"] = list(dict.fromkeys(rec.get("identities", []) + ids))[-IDENTITIES_KEPT:]
    folded.append(game_id)
    rec["folded"] = folded[-30:]


def _close_prev_and_avoid(rec: dict) -> list:
    """把上一局(若有真出过任务)收进历史·只留最近 GAMES_CAP 局·返回拍平的躲避集。
    顺手把上一局两人最终的身份也收进 identities(身份跨局去重)。"""
    prev_id = rec.get("last_game_id")
    if prev_id and _path(prev_id).exists():
        try:
            _fold_game_into(rec, Game.load(str(_path(prev_id))), prev_id)   # folded防重折(终局可能已折过)
        except Exception:
            pass
    return list(rec.get("recency", []))   # LRU 有序躲避集(oldest->newest)


# ── Endpoints ──

_INTRO = (
    "【荷官须知·开局只发这一次·别每轮重复】\n"
    "你是这局的荷官,同时也是玩家之一——重点是【玩】!和你的人类一起享受色色大富翁,不是跑任务推进度。掷第一轮前,用大白话跟ta讲清楚:\n"
    "① 玩法:两人轮流掷骰子走格子,踩到任务格就做一道色色任务;还有商店/监狱/机会/对决等格子。目标是玩得开心,不是输赢。★谁先掷:默认第一个玩家(p1)先手·之后轮流;想让 AI 或某人先手,开局把 ta 的名字填进 first_player。开局可调口味:强度段 flavor——决定这局任务落在1-6强度尺的【哪一段】,整段移动(地板+天花板一起走):light=全是轻任务(强度1-3·调情接吻爱抚,抽不到强度4+的重任务) / medium=中到中高(2-5·默认) / heavy=整局每道任务都高强度(3-6·地板就是3、没有轻任务、大半4-6、越往后越狠顶到6)。★heavy不是「偶尔来一下狠的」·是每道任务都狠;也不是「任务更多/更开放」——想玩更多轮/更长是调 局长 game_length(速玩12/正常18/超长24·默认24)、攻受反转 reverse_chance(0=严守角色/0.3默认/0.5常翻)——★跟人类讲清「反转」是啥:游戏里有小概率你俩的攻/受会临时对调一下(比如受突然按住攻反过来支配),是故意设计的惊喜,抽到反转的任务卡会特意标出来,别当成bug;不想要就把 reverse_chance 设 0。都是 /new_game 的参数。\n"
    "② 安全第一:任何人随时说「红线」或「停」,就立刻跳过这道(调 /skip)或结束整局,不追问理由。开局先问清双方各自不想要的(比如 打/绑/玩具/暴露),用 redline 参数传进来我自动过滤。\n"
    "②b ★后庭(肛交)默认【关】——这是安全默认,别默认帮谁开。开局【必须】明确问一句:『要不要开后庭(肛交)?可以只一个人开。』愿意被后庭的人,名字填进 open_anal(每人独立·比如只 open_anal=['小明'] 就只有小明会被肛、对方不会)。没人要就不填=两人都不出后庭任务。男男局尤其记得问(不然默认只有口手摩擦)。★另:有人想当【纯top】(这局只插别人、自己任何孔都不被插)→名字填 no_penetration。女女局尤其有用(光禁后庭挡不住阴道被插)。\n"
    "③ 节奏(最重要):踩到任务这轮【不结算】——把任务念出来之后,就是玩的时间:你的任务【你自己真的演】,人类的任务ta自己做,你们来回互动,别替对方描写、别抢戏、别赶。玩尽兴了再调下一次 /roll,上一题会在开头自动结算(+币+占地)。「下一次掷骰=上一题玩完了」。真心话同理:答了就是做了,下一轮自动按强度给币。\n"
    "④ 身份要演进肉里:开局每人发一张身份(带完整扮演要求,看 status;踩🎴会换),它是你整局的人设——猫猫就真的用第三人称、有耳朵尾巴。每轮返回的 identity_reminder 照念一遍,别让人设掉线。抽到实在演不下去的,每人每局可 /reroll_identity 换一次。\n"
    "⑤ 你只需要一条命令:每回合 /roll。特殊情况(对决/过路费/超级任务)看返回里的 action_needed 和 hint 提示;这道不想做调 /skip(白跳不给币);想换一道玩调 /swap(赔对方1币·每人每局3次·没币也能换但做完不给币)。★swap换掉的卡会【永久拉黑】这对玩家、以后再玩也不出这道(skip只是这局不出、不拉黑)。想恢复全部被换掉的·开局传 reset_blocklist:true 洗白。\n"
    "⑥ 金币机制(★开局也要跟人类讲一句·这是胜负核心,别让ta稀里糊涂):这游戏靠金币定胜负——(a)做任务按强度给币(轻1中2狠3超5),(b)路过或正好踩中🏁起点+2币,(c)做完一道任务就白占下那一格=你的『地盘』,对方之后踩进来,要么交过路费(3币)、要么听你差遣做一道任务。打满回合数时金币多的人赢,赢家能命令输家做最后一道『不能拒绝』的终极指令(除红线/404外)。所以每一道任务、每一次踩格都在攒赢面。\n"
    "⑦ ★开局把返回里的 active_limits(实际生效的红线/后庭/纯top)原样念给人类确认一遍——防「以为禁了其实没设上」。若跟ta刚说的不符,说明参数没传对,重开一局传对再玩。\n"
    "⑧ 跨局不重复(自动·你啥都不用记):引擎按【两个玩家的名字+性别】自动认这对玩家——同一对玩家用同样的名字开局,就自动躲开你们玩过的任务和身份(优先发最久没出过的·尽量不重样)(改天接着玩也一样,不用记 token)。返回里的 history_note 会告诉你「这对之前玩过几局」——念给人类听;★强烈建议开局就用你们【自己的独特名字】(别照抄示例里的 Alice/Bob——很多人用一样的名字会共享同一份去重记录、互相影响抽卡)。若他们说第一次玩却显示玩过=跟别人撞名了,让他们换个独特名字、或给个暗号(开局传 pair_code)就分开、原名能留。(player_token 只在删局/看局时用,去重不靠它)\n"
    "讲清楚、问好红线,就开始吧。"
)


@app.post("/new_game")
def new_game(req: NewGameRequest):
    """开局：创建新游戏，返回 game_id + player_token + 棋盘 + 状态。
    跨局记忆:带上次的 player_token → 这局自动躲开你最近10局出过的任务;不带则发个新令牌给你。"""
    dedup = _dedup_key(req.p1_name, req.p2_name, req.p1_sex, req.p2_sex, req.pair_code)   # 去重key按名字+性别[+暗号](AI不用记·忘token也接得上)
    token = req.player_token or uuid.uuid4().hex[:12]   # token只做鉴权(删局/看局)·去重不靠它
    rec = _load_token(dedup)
    if req.reset_blocklist:                   # ★洗白这对的永久黑名单(拉黑错了想恢复全部)
        rec["blocklist"] = []
        _save_token(dedup, rec)
    avoid = _close_prev_and_avoid(rec)        # 收上一局 + 取最近10局躲避集(任务) + 收身份
    prev_games = int(rec.get("game_count", 0))    # 透明化:折叠上一局后读=这对玩家之前玩了几局(含刚折进来的上局·同名混了人类能察觉)
    if req.identity_mode not in ("off", "mixed", "nsfw_only"):
        raise HTTPException(422, f"identity_mode 只能是 off/mixed/nsfw_only,收到 {req.identity_mode!r}")
    if req.redline:                            # redline 拼错=安全洞·别静默吞
        _bad = [r for r in req.redline if r not in _VALID_REDLINE]
        if _bad:
            raise HTTPException(422, f"redline 无法识别{_bad}——怕是拼错(安全项不能静默忽略)。合法开关:{sorted(REDLINE_SWITCHES)}；或中文标签/库kink标签")
    game_id = uuid.uuid4().hex[:8]
    g = Game(
        lineup=req.lineup, flavor=req.flavor,
        p1_name=req.p1_name, p1_sex=req.p1_sex, p1_role=req.p1_role,
        p2_name=req.p2_name, p2_sex=req.p2_sex, p2_role=req.p2_role,
        p1_color=req.p1_color, p2_color=req.p2_color,
        redline=req.redline, no_receive_anal=req.no_receive_anal, open_anal=req.open_anal, no_penetration=req.no_penetration, seed_theme=req.theme,
        reverse_chance=req.reverse_chance, recent_tasks=avoid, blocklist=rec.get("blocklist", []), player_token=token,
        dedup_key=dedup, identity_mode=req.identity_mode, game_length=req.game_length,
        avoid_identities=rec.get("identities", []),       # 身份跨局去重:躲最近玩过的
    )
    if req.first_player:                       # ★谁先掷(默认p1先)·想让AI/某人先手填ta名字
        if req.first_player not in (req.p1_name, req.p2_name):
            raise HTTPException(422, f"first_player 必须是 {req.p1_name!r} 或 {req.p2_name!r} 之一(想让谁先掷填谁的名字)")
        g.turn = req.first_player
    _save(game_id, g)
    rec["last_game_id"] = game_id
    opening_ids = [v.get("name") for v in g.identity.values() if v and v.get("name")]
    if opening_ids:                                        # 开局发出的身份当场记进躲避集
        rec["identities"] = list(dict.fromkeys(rec.get("identities", []) + opening_ids))[-IDENTITIES_KEPT:]
    _save_token(dedup, rec)
    return {"game_id": game_id, "player_token": token, "status": g.status(), "board": g.board_art(),
            "identity_reminder": g._identity_reminder(),   # 双方身份浓缩提醒(每轮 roll 也会带)
            "active_limits": g.safety_summary(),           # ★实际生效的安全设置回显·荷官开局念给人类确认(治「以为禁了其实没设上」)
            "history_note": ("这对玩家(按名字+性别自动认)之前记录了%d局·会自动躲开那些任务、不重复。★若你们其实是第一次玩、却显示玩过=可能跟别人撞名了·换个独特名字、或开局加个暗号(pair_code·比如「你俩的小名」)就能跟别人分开、原名照留。" % prev_games) if prev_games else "这对玩家第一次玩·开始记录(下次同样的名字会自动接上、不重复·不用记token)。",
            "blocked_count": len(rec.get("blocklist", [])),   # ★这对永久拉黑(swap换掉)了几张·撞名/新玩家=0·可念给人类
            "intro": _INTRO}


def _dedup_key(p1n, p2n, p1s, p2s, pair_code=""):
    # 去重key=「名字+性别[+暗号]」派生(AI没长期记忆·token会丢·改按名字自动认这对玩家)。
    # 排序(谁p1不影响)。性别进key=区分同名的女女/男女/男男对。pair_code=暗号:撞名了不用改名·加个暗号就分开。md5 hash=不暴露名字。
    pair = (tuple(sorted([(str(p1n), str(p1s)), (str(p2n), str(p2s))])), str(pair_code or ""))
    return "n_" + hashlib.md5(json.dumps(pair, ensure_ascii=False).encode()).hexdigest()[:14]


def _avoid_now(token: str) -> list:
    """这个令牌当前的躲避集(最近≤10局拍平·只读不动历史)。"""
    rec = _load_token(token)
    return list(rec.get("recency", []))


@app.post("/roll/{game_id}")
def roll(game_id: str, body: Optional[RollRequest] = None):
    """掷骰子：当前玩家掷骰，返回结果。
    ★lazy 结算:踩到任务/过路费/对决这轮【不结算】——念出来之后是玩的时间;
    下一次 /roll 开头把上一轮悬着的账一次结清。悬账决定用 body 一行带上(全可选):
      {"toll":"pay|serve", "task":"done|skip", "super_action":"done|buyout", "duel_winner":"名字"}
    不传 body = 全默认:过路费自动交钱、任务照做给币、超级任务照做+5。「下一次掷骰 = 上一题玩完了+账全清了」。"""
    g = _load(game_id)
    if g.player_token:               # 每次重新载入要按令牌补回躲避集+黑名单(存档不存它·令牌文件才是真相源)
        _dk = g.dedup_key or _dedup_key(g.p1, g.p2, g.sex.get(g.p1), g.sex.get(g.p2))
        g._set_recency(_avoid_now(_dk))
        g.blocklist = set(_load_token(_dk).get("blocklist", []))
    b = body or RollRequest()
    # 枚举校验:未知值别静默当默认(task拼错成banana会被当done白得币占地)·直接 400
    _ROLL_ENUMS = {"toll": (None, "pay", "serve"), "task": (None, "done", "skip"),
                   "super_action": (None, "done", "buyout"), "guess": (None, "大", "小")}
    for _f, _ok in _ROLL_ENUMS.items():
        _v = getattr(b, _f)
        if _v not in _ok:
            raise HTTPException(400, f"{_f} 只能是 {[x for x in _ok if x]}（或不传），收到 {_v!r}")
    settled = None
    def _add(res):
        nonlocal settled
        if res: settled = res if settled is None else settled + " ｜ " + res
    # ⓪ 悬着的对决必须先报赢家——赌注不许蒸发
    if g.pending_duel:
        if not b.duel_winner:
            raise HTTPException(400, f"上一轮的对决还没报赢家:body 里带 duel_winner(\"{g.p1}\"或\"{g.p2}\")再掷,或先调 POST /duel_result")
        _add(g.duel_result(b.duel_winner))
    # ① 悬着的过路费:默认自动交钱(白嫖之路封死);做了地主差遣的传 toll="serve" 抵扣
    _add(g.settle_pending_toll(mode=b.toll or "pay"))
    # ② 悬着的任务:默认照做给币;task="skip"跳过;super_action="buyout"花8币不做
    for pw in list(g.pending_task):
        is_super = g.pending_task[pw].get("super")
        if is_super and b.super_action == "buyout":
            _add(g.buyout(pw))
        elif (not is_super) and b.task == "skip":
            g.pending_task.pop(pw, None)
            _add(f"⏭️ {pw} 跳过上一道(不给币不占地)")
        else:
            _add(g.done(pw))
    # ③ 再掷这一轮(guess:🎰赌徒押大小一并带上·非赌徒忽略)
    r = g.roll(guess=b.guess, swap_identity=bool(b.swap_identity))
    who = r["who"]
    t = r.get("task")
    action_needed, hint = None, None
    if r.get("game_over"):
        hint = "游戏结束·调 GET /final_result/{game_id} 看赢家"
    elif r.get("duel"):
        action_needed = "duel"
        hint = "两人对撩商议出赢家·下一轮掷骰 body 带 {\"duel_winner\":\"名字\"} 一行结账(不带会拒掷)·或单独调 POST /duel_result"
    elif r.get("jailed"):
        hint = "被绑的人这轮被对方处置(不结算金币)·直接继续 /roll 下一轮"
    elif r.get("asleep"):
        hint = "😴睡美人沉睡:这轮被对方处置(需吻醒·不结算金币·醒来已自动+1)·直接继续 /roll"
    elif r.get("toll"):
        action_needed = "toll"
        hint = f"踩进对方地盘(过路费{r['toll']['fee']}币已挂账):下一轮 /roll 自动交钱·想用差遣抵扣(做地主那道·不扣钱)就 body 带 {{\"toll\":\"serve\"}}"
    elif t and "buyout" in t:
        action_needed = "super"
        hint = "超级任务:玩完下一轮 /roll 自动结算(+5币)·不想做下一轮 body 带 {\"super_action\":\"buyout\"}(花8币)"
    elif t:
        hint = "任务念给玩家·现在是玩的时间(你的任务你演·人类的任务人类做)·玩完再 /roll 自动结算(+币+占地)·不想做下一轮 body 带 {\"task\":\"skip\"}·嫌没意思/有毛病可 POST /swap/{game_id}/{名字} 当场换一道(赔对方1币·每局3次)"
    elif r.get("tile") == "truth":
        hint = "真心话念给玩家·答了就是做了·下一轮 /roll 自动按强度给币·不想答下一轮 body 带 {\"task\":\"skip\"}·嫌没意思/有毛病可 POST /swap/{game_id}/{名字} 当场换一道(赔对方1币·每局3次)"
    elif r.get("truth"):   # mystery「暴露」的强制真心话:惩罚·不给币(别照上面那条许愿)
        hint = "🎭暴露:对手指定的真心话·必须答(这是坏运惩罚·不给币)·答完直接 /roll"
    if r.get("tile") == "shop":
        hint = f"商店格:想花3币摸功能卡调 POST /buy_card/{game_id}/{who}"
    _save(game_id, g)
    return {
        "who": who,
        "dice": r.get("dice"),
        "tile": r.get("tile"),
        "say": r.get("say"),
        "task": t,                    # 动作任务(踩任务格/超级/羞耻/过路费差遣)
        "truth": r.get("truth"),      # 真心话格:{强度,内容} ← AI别自己编·照这个念
        "mystery": r.get("mystery"),  # 未知格好/坏运
        "card": r.get("card"),        # 机会格抽到的功能卡
        "toll": r.get("toll"),        # 踩进对方地盘
        "duel": r.get("duel"),        # 同格对决
        "jailed": bool(r.get("jailed")),   # 这一轮是狱中回合(掷骰人被绑·被对方处置)。原来恒null·程序化判断只能靠say文本
        "asleep": bool(r.get("asleep")),   # 😴睡美人沉睡轮(掷1/6·这轮被对方处置·醒来+1)
        "in_jail": dict(g.jailed),    # 当前还关在监狱里的人:{名字: 剩几轮}。刚踩进监狱这轮就能在这看到
        "game_over": r.get("game_over", False),
        "settled": settled,           # ★上一轮悬着的任务在本轮开头结算的结果(谁+几币+占哪格);None=上一轮没有悬着的。先把这个念给玩家,再念这一轮的
        "identity_reminder": r.get("identity_reminder"),  # 双方身份浓缩提醒——每轮照念一遍,别让人设掉线
        "action_needed": action_needed,  # None=这轮啥都不用做·直接下一轮 /roll;"duel"/"toll"/"super"=按 hint 调对应端点
        "hint": hint,                 # 一句话告诉 AI 下一步(没有就是直接 /roll)
        "board": g.board_art(),       # ★现算的棋盘·反映自动结算后的币/地盘(别用 roll 时抓的旧 board·否则币不更新)
        "next_turn": g.turn,
    }


@app.post("/done/{game_id}/{who}")
def done(game_id: str, who: str):
    """完成任务：领收集物 + 币"""
    g = _load(game_id)
    result = g.done(who)
    _save(game_id, g)
    return {"result": result, "board": g.board_art()}


@app.post("/buy/{game_id}/{who}")
def buy(game_id: str, who: str):
    """商店：花币买收集物(收集物默认下线·一般用不到)"""
    g = _load(game_id)
    result = g.buy(who)
    _save(game_id, g)
    return {"result": result, "board": g.board_art()}


@app.post("/pay_toll/{game_id}/{who}")
def pay_toll(game_id: str, who: str):
    """交过路费:踩进对方地盘·交3币免做地主差遣的任务"""
    g = _load(game_id)
    result = g.pay_toll(who)
    _save(game_id, g)
    return {"result": result, "board": g.board_art()}


@app.post("/reroll_identity/{game_id}/{who}")
def reroll_identity(game_id: str, who: str):
    """身份重抽:每人每局1次·抽到实在演不下去的身份可换一张(兔女郎条款)"""
    g = _load(game_id)
    result = g.reroll_identity(who)
    _save(game_id, g)
    return {"result": result, "status": g.status(), "identity_reminder": g._identity_reminder()}


@app.post("/reroll_task/{game_id}/{who}")
def reroll_task(game_id: str, who: str):
    """换任务:消费身份的 task_reroll 特权(猫猫/小丑有)·悬着的任务换一道·照常给币"""
    g = _load(game_id)
    r = g.reroll_task(who)
    _save(game_id, g)
    return {"result": r["result"], "task": r["task"], "board": g.board_art()}


@app.post("/swap/{game_id}/{who}")
def swap(game_id: str, who: str):
    """💱换任务(全民版):悬着的任务不喜欢/有毛病就换一道——赔对方1币(没币=换来的做完不给币);每人每局3次;超级任务不换(用买断)。服务器记日志=众包审卡。"""
    g = _load(game_id)
    r = g.swap_task(who, game_id=game_id)
    _save(game_id, g)
    if r.get("blocked"):                       # ★换掉的卡永久拉黑这对(写进 seen·以后永不再出)
        _dk = g.dedup_key or _dedup_key(g.p1, g.p2, g.sex.get(g.p1), g.sex.get(g.p2))
        rec = _load_token(_dk)
        if r["blocked"] not in rec["blocklist"]:
            rec["blocklist"].append(r["blocked"])
            _save_token(_dk, rec)
    return {"result": r["result"], "task": r["task"], "board": g.board_art()}


@app.post("/id_event/{game_id}/{who}/{event}")
def id_event(game_id: str, who: str, event: str):
    """人判记账:玩家判定发生了某事·引擎管身份校验+次数。event=
    first_climax(🫣处子首高潮+3·每局1次) / say_banned(🤐禁言者说了禁词·罚1给对方) / no_kiss_2turns(💋接吻魔连两轮没亲·扣1)。"""
    g = _load(game_id)
    result = g.id_event(who, event)
    _save(game_id, g)
    return {"result": result, "board": g.board_art()}


@app.post("/extra_task/{game_id}/{who}")
def extra_task(game_id: str, who: str):
    """➕不知餍足加餐:每局限额主动加抽一道任务(做完照常 /roll 或 /done 给币)。"""
    g = _load(game_id)
    r = g.extra_task(who)
    _save(game_id, g)
    return {"result": r["result"], "task": r["task"], "board": g.board_art()}


@app.post("/guess_mark/{game_id}/{who}/{spot}")
def guess_mark(game_id: str, who: str, spot: str):
    """🌀淫纹:who 猜对方持有者的一个部位·每轮限一猜·猜中 who+3(部位绝不外泄·只在这里验中不中)。"""
    g = _load(game_id)
    result = g.guess_mark(who, spot)
    _save(game_id, g)
    return {"result": result, "board": g.board_art()}


@app.post("/declare_persona/{game_id}/{who}")
def declare_persona(game_id: str, who: str, body: PersonaRequest):
    """🎭背德者:玩家自己宣布一个背德身份·之后每轮 identity_reminder 自动带上。"""
    g = _load(game_id)
    result = g.declare_persona(who, body.persona)
    _save(game_id, g)
    return {"result": result, "identity_reminder": g._identity_reminder(), "board": g.board_art()}


@app.post("/skip/{game_id}/{who}")
def skip(game_id: str, who: str):
    """跳过悬着的任务(软404):这道不玩了·不给币不占地·下一轮照常。任何人说不想做这道,调这个,不追问理由。"""
    g = _load(game_id)
    pend = g.pending_task.pop(who, None)
    _save(game_id, g)
    result = f"⏭️ {who} 跳过这道(不给币不占地)" if pend else f"({who} 没有悬着的任务)"
    return {"result": result, "board": g.board_art()}


@app.post("/buyout/{game_id}/{who}")
def buyout(game_id: str, who: str):
    """买断超级任务:不做·交8币"""
    g = _load(game_id)
    result = g.buyout(who)
    _save(game_id, g)
    return {"result": result, "board": g.board_art()}


@app.post("/buy_card/{game_id}/{who}")
def buy_card(game_id: str, who: str):
    """商店格:花3币摸一张功能卡"""
    g = _load(game_id)
    result = g.buy_card(who)
    _save(game_id, g)
    return {"result": result, "board": g.board_art()}


@app.post("/use_card/{game_id}/{who}/{index}")
def use_card(game_id: str, who: str, index: str):
    """用手牌里第 index 张功能卡(index 从 0 起)。也兼容直接传卡名(如 加速/🔒)。"""
    g = _load(game_id)
    hand = g.hand.get(who, [])
    idx = None
    if index.lstrip("-").isdigit():
        idx = int(index)                                  # 传的是序号
    else:
        for i, c in enumerate(hand):                      # 传的是卡名·模糊匹配(含 emoji 或纯名)
            if index in c.get("name", "") or index == c.get("name", ""):
                idx = i; break
        if idx is None:
            raise HTTPException(400, f"用卡要传手牌序号(0起)或卡名。{who} 现在手牌:{[c.get('name') for c in hand] or '空'}")
    result = g.use_card(who, idx)
    _save(game_id, g)
    return {"result": result, "board": g.board_art()}


@app.post("/discard/{game_id}/{who}/{index}")
def discard(game_id: str, who: str, index: int):
    """手牌满时弃掉第 index 张(index 从 0 起)"""
    g = _load(game_id)
    result = g.discard(who, index)
    _save(game_id, g)
    return {"result": result, "board": g.board_art()}


@app.post("/duel_result/{game_id}/{winner}")
def duel_result(game_id: str, winner: str):
    """色色对决:两人商议后报赢家名字(输家给赢家3币·可再受一道差遣)"""
    g = _load(game_id)
    result = g.duel_result(winner)
    _save(game_id, g)
    return {"result": result, "board": g.board_art()}


@app.get("/final_result/{game_id}")
def final_result(game_id: str):
    """终局:满回合后看赢家(比金币)+ 赢家终极指令。★终局收益(🎩年上/🐤年下转账·🌀淫纹守住)在这里结算·须 _save 落盘(幂等只算一次)。"""
    g = _load(game_id)
    result = g.final_result()
    _save(game_id, g)
    if g.dedup_key:                                    # 终局立即折进去重池(不依赖下一局开局·删局也不丢历史)
        rec = _load_token(g.dedup_key)
        _fold_game_into(rec, g, game_id)
        _save_token(g.dedup_key, rec)
    return {"result": result, "board": g.board_art()}


@app.get("/state/{game_id}")
def state(game_id: str):
    """查看当前全局状态"""
    g = _load(game_id)
    # theme/items 不返回——主题+收集物玩法已隐形,存档字段仍保留但 output 不暴露
    return {
        "status": g.status(),
        "board": g.board_art(),
        "turn": g.turn,
        "positions": g.pos,
        "coins": g.coins,
        "laps": g.lap,
    }


@app.get("/shop/{game_id}")
def shop(game_id: str):
    """查看收集物池(收集物玩法已搁置·下线时返回提示;翻 COLLECTIBLES_ENABLED 复活)"""
    g = _load(game_id)
    from monopoly_play import THEMES, COLLECTIBLES_ENABLED
    if not COLLECTIBLES_ENABLED:
        return {"status": "🚫 收集物玩法已下线(现用纯金币系统)", "items": []}
    pool = THEMES.get(g.theme, [])
    return {
        "theme": g.theme,
        "price": 8,
        "items": pool,
        "p1_owned": g.items[g.p1],
        "p2_owned": g.items[g.p2],
    }


@app.delete("/game/{game_id}")
def delete_game(game_id: str, token: Optional[str] = None):
    """删除游戏(开放加固:要带这局的 player_token 才能删——只能删自己的局·防拿到链接的人删别人打到一半的局)"""
    p = _path(game_id)
    if not p.exists():
        return {"ok": True}
    owner_token = None
    try:
        owner_token = Game.load(str(p)).player_token
    except Exception:
        pass                                   # 档案坏了→放行删除(清理路径)
    if owner_token and token != owner_token:
        raise HTTPException(403, "删局要带这局开局时返回的 player_token(?token=...)——只能删自己的局")
    p.unlink()
    return {"ok": True}


@app.get("/games")
def list_games(token: Optional[str] = None):
    """列出【自己】进行中的游戏(按 player_token 隔离·不带令牌返回空·防内测者互见)。"""
    # ↑ gamesfilter 租户隔离改动·合并保留
    games = []
    if not token:
        return {"games": games}
    for f in GAMES_DIR.glob("*.json"):
        try:
            g = Game.load(str(f))
            if g.player_token != token:
                continue
            games.append({
                "game_id": f.stem,
                "players": f"{g.p1} vs {g.p2}",
                "turn": g.turn,
                "flavor": g.flavor,
            })
        except Exception:
            pass
    return {"games": games}


@app.get("/seen/{token}")
def peek_history(token: str):
    """看这个玩家记着多少局、多少条任务(跨局记忆)。
    ★注意:在玩的这局要等【下一局开局】才折进 games 池(读它的存档·掉线的局也照折)——
    所以 tasks_remembered 是【已折进池的往局】·当前这局单列 current_game_tasks·别误读成没记。"""
    rec = _load_token(token)
    recency = rec.get("recency", [])
    cur_tasks, cur_id = 0, rec.get("last_game_id")
    if cur_id and _path(cur_id).exists():
        try:
            cur_tasks = len(set(Game.load(str(_path(cur_id))).history))
        except Exception:
            pass
    return {"games_played": int(rec.get("game_count", 0)), "tasks_remembered": len(recency),
            "current_game_tasks": cur_tasks, "dedup": "LRU·最久没出优先(不再按固定局数截断)"}


@app.delete("/seen/{token}")
def clear_history(token: str):
    """手动清空这个玩家的跨局历史(洗牌重来·只清这个令牌·不影响别人)。"""
    _save_token(token, {"recency": [], "game_count": 0, "last_game_id": None, "identities": [], "folded": []})
    return {"ok": True, "msg": f"令牌 {token} 的跨局历史已清空"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8069)   # 只本地·对外只走 nginx 密钥路由(别绑0.0.0.0裸奔)
