#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
涩涩大富翁 · 双人收集版 v0.3
配套 monopoly-library.json + monopoly-cards.json(可选) + monopoly-identities.json(可选)。

═══════════════ 给 AI 的话(你来当荷官) ═══════════════
你是【荷官】:掷骰、报点、发任务、记账。怎么用:
    from monopoly_play import Game
    g = Game(lineup="男女", flavor="medium",
             p1_name="Alice", p1_sex="男", p1_role="攻",
             p2_name="Bob", p2_sex="女", p2_role="受",
             redline=[], reverse_chance=0.3)

    print(g.board_art())
    r = g.roll()
    print(r["say"]); print(r["board"])
    if r["task"]: print(r["task"]["内容"])
    print(g.done(r["who"]))

规则:荷官只发任务/报点/记账;**怎么做、怎么演是玩家的事,你不替写性爱过程**。
谁踩格子谁就是「行动方」(对对方/对自己做)。reverse_chance(默认0.3)=有概率抽到反转任务:
弱势方突然变主导、或主导方突然被服务;r["task"]["flavor"] 会标「🔄反转」。设 0=严守角色,0.5=完全混乱。
红线(redline=[...])绝对避开:开关词 anal/toys/pain/bondage/public 任选(自动展开成对应 tag),
也可直接传 tag 子串。任何人喊 "404" 立刻全停。
═══════════════════════════════════════════════════
"""
import json, random, re
from pathlib import Path

# 中性「穴」词(裸穴/骚穴/后穴/穴口=中性任意):长男人身上=后庭·长女人身上=阴道。
# 只给「没标承受方」的安全网兜底用(排除明确女性的 花/蜜/小/阴X穴)。
_NEUTRAL_HOLE_RE = re.compile(r'(?<![花蜜小阴])穴|菊')

_DIR = Path(__file__).parent

def _atomic_write(path, text):
    # 原子写(治并发写同一存档写半截损坏·对抗测试撞出):写临时文件→os.replace原子rename·文件永远完整。
    import os, tempfile
    path = str(path)
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)   # 同fs原子rename·并发下最后一个赢但绝不损坏
    except Exception:
        try: os.remove(tmp)
        except Exception: pass
        raise
# 解耦四轴库 v2:强度/flavor(攻受任意)/玩法类型/kink[]/行动方需·对方需(男女任意)/target/内容(行动方·对方·自己占位)
LIB = json.loads((_DIR / "monopoly-library.v2.json").read_text("utf-8"))["tasks"]

# Optional data files — graceful fallback if not present
def _load_json(name, default):
    p = _DIR / name
    return json.loads(p.read_text("utf-8")) if p.exists() else default

# 收集物暂砍下线(留死代码·翻 True 即复活;收集物鸡肋)
COLLECTIBLES_ENABLED = False
CARD_DRAW_COST = 3            # 花钱主动摸一张功能卡(商店格 / g.buy_card())
JAIL_TURNS = 1               # 进监狱关几轮(1 轮·被绑任对方处置)
DUEL_STAKE = 3               # 同格色色对决:输家给赢家几币
SWAP_CAP = 3                 # 💱全民换任务:每人每局上限(代价=赔对方1币;没币=换来的做白工)
ROUNDS_PER_PLAYER = 12       # 终局:每人各掷约这么多次(回合数终局·两人轮流掷·天然同时到·谁都不等)

CARD_POOL = _load_json("monopoly-cards.json", [
    # 位置 / 对位类
    {"name": "🔙 回退", "effect": {"type": "push_back", "value": 3}, "description": "对手后退3格"},
    {"name": "🔒 入狱", "effect": {"type": "send_jail"}, "description": "送对手进监狱"},
    {"name": "🔓 出狱", "effect": {"type": "jail_free"}, "description": "免疫一次监狱"},
    {"name": "⏩ 加速", "effect": {"type": "double_roll"}, "description": "下一轮再掷一次(连走两回合)"},
    # 金币类
    {"name": "💰 抢劫", "effect": {"type": "steal_coins", "value": 3}, "description": "偷对手3币"},
    {"name": "🎰 赌一把", "effect": {"type": "gamble", "value": 3}, "description": "掷硬币:赢→对手给你3币,输→你给对手3币"},
    {"name": "💰 收租", "effect": {"type": "collect_rent", "value": 1}, "description": "对手按你的地盘数交租(每块地1币)"},
    {"name": "💸 敲诈", "effect": {"type": "extort", "value": 2}, "description": "逼对手交2币(没钱用身体抵)"},
])

IDENTITY_POOL = _load_json("monopoly-identities.json", [
    {"name": "🏛️ 审查官", "effects": [{"type": "modify_reward", "value": -2}], "behavior": "每次色色任务结束宣布'已记录违规'"},
    {"name": "🔓 越狱大师", "effects": [{"type": "immunity", "target": "jail"}], "behavior": "踩到监狱时潇洒走过"},
    {"name": "💸 资本家", "effects": [{"type": "modify_cost", "value": 0.5}], "behavior": "买东西时甩金币"},
    {"name": "🔥 发情期", "effects": [{"type": "modify_intensity", "value": 1}], "behavior": "所有反应都加倍夸张"},
    {"name": "🧊 冷淡期", "effects": [{"type": "modify_intensity", "value": -2}], "behavior": "所有反应都很淡定"},
    {"name": "💀 封号侠", "effects": [{"type": "ban_random_tag"}], "behavior": "义正言辞宣布被ban的tag"},
    {"name": "🐱 猫猫", "effects": [{"type": "can_refuse"}], "behavior": "拒绝时要说'不要喵'"},
    {"name": "🎰 赌徒", "effects": [{"type": "gamble_reward"}], "behavior": "做任务前猜奇偶"},
    {"name": "📱 主播", "effects": [], "behavior": "做任务时必须详细描述 当成直播给观众看 敷衍扣1币"},
    {"name": "🫣 处女", "effects": [], "behavior": "假装第一次 所有反应要害羞 说好厉害第一次见"},
    {"name": "🍼 Daddy", "effects": [{"type": "modify_intensity", "value": 1}], "behavior": "所有任务用dom口吻 可以给对手加作业"},
    {"name": "👶 Baby", "effects": [], "behavior": "所有回答必须babytalk 违反扣1币"},
])

CURVES = {"light": (1, 3), "medium": (2, 5), "heavy": (3, 6)}
LEVEL_NAME = {1: "触电", 2: "撩", 3: "碰", 4: "口手", 5: "做", 6: "失控"}   # 新强度标准:3=碰性器不进入/4=口手成套服务

# 显式红线开关 → 对应 kink 维度(v2 卡的 kink 字段)。开局可传开关词(更直观),也可直传 kink 值。
REDLINE_SWITCHES = {
    "anal":    ["后庭"],   # 肛交/后庭
    "toys":    ["玩具"],   # 跳蛋/震动棒/假阳具/乳夹/口塞
    "pain":    ["打"],     # 打屁股/抽打/掌掴/皮带/鞭
    "bondage": ["绑"],     # 捆绑/反绑/手铐/拘束
    "public":  ["暴露"],   # 当众/暴露
    "degrade": ["羞辱"],   # 言语羞辱/贬低
    "wet":     ["失禁"],   # 失禁/尿/watersports(新kink红线)
    "foot":    ["足"],     # 恋足/足交/踩踏
    "spit":    ["口水"],   # 唾液/吐口水/口水交换
    "milk":    ["产乳"],   # 哺乳/挤奶/奶阵
    "estim":   ["电"],     # 电击/电刺激
    "dp":      ["双龙"],   # 双插/DP/双头
    "hypno":   ["催眠"],   # 催眠/失神/恍惚腔(心智操控·硬雷可关)
}

# ★内容兜底红线关键词(超级任务漏玩具/失禁根治):卡漏标 kink 时·按内容也挡。
# 键=红线 tag(=REDLINE_SWITCHES 的值)·值=高置信关键词正则。只收明确的·避开会误伤的裸字(如裸「打」会中打圈/打转)。
_RL_CONTENT = {
    # 收紧防误伤:玩具去「乳夹」(会中"双乳夹住"=乳交)·电去「电到/电了」(会中"被你电到"比喻)·催眠去「恍惚/失神」(正常快感反应)
    "玩具": re.compile(r"跳蛋|震动棒|振动棒|按摩棒|电动棒|拉珠|肛塞|尾巴塞|延时环|锁精环|假鸡巴|假阳具|穿戴式|遥控.{0,3}蛋|情趣玩具"),
    "失禁": re.compile(r"失禁|憋尿|漏尿|尿出|尿液|撒尿|尿在|尿了|喷尿|尿意|尿裤"),
    "打":   re.compile(r"掌掴|鞭打|巴掌|打屁股|打红|拍臀|扇.{0,3}屁股|扇.{0,2}巴掌|掴|抽.{0,4}(屁股|臀|背)"),
    "绑":   re.compile(r"绑|捆|反缚|反绑|手铐|束缚|拘束|镣铐|皮带缚|丝带.{0,3}缚"),
    "口水": re.compile(r"口水|唾液|吐口水|唾沫|口涎"),
    "产乳": re.compile(r"产乳|挤奶|乳汁|奶水|母乳|喷奶|催乳|泌乳"),
    "电":   re.compile(r"电击|电流|通电|电棒|电击棒|电击贴片|电击跳蛋|电击乳夹"),
    "双龙": re.compile(r"双头龙|双插|双龙"),
    "催眠": re.compile(r"催眠|触发词"),
    "足":   re.compile(r"足交|脚交|用脚|脚底|脚趾|脚背|脚心|踩着|穿.{0,4}高跟|丝袜.{0,4}脚"),
    "暴露": re.compile(r"当众|公共场|走光|露天|阳台|窗边|户外"),
}

# Board layout: 20 tiles with new types
SPECIAL = {0: "start", 4: "truth", 5: "chance", 8: "mystery", 10: "jail",
           12: "shop", 14: "truth", 15: "chance", 17: "mystery", 19: "shop"}
# 速玩密任务盘(≤12轮·12轮真做任务才5-6轮·节奏松)——只留每种功能格1个·其余全任务(6功能14任务·vs常规10/10)
SPECIAL_DENSE = {0: "start", 5: "chance", 8: "mystery", 11: "jail", 14: "truth", 17: "shop"}
TILES = ["start" if i == 0 else SPECIAL.get(i, "task") for i in range(20)]
TILE_EMOJI = {"start": "🏁", "task": "🎯", "truth": "💬", "shop": "🛒",
              "jail": "🔒", "chance": "🎴", "mystery": "❓"}
THEMES = {
    "🎮 玩具局": ["跳蛋", "震动棒", "乳夹", "口塞", "手铐", "眼罩", "拍子", "后庭塞"],
    "👅 脏话局": ["叫主人", "数高潮", "求着要", "说脏话", "报数", "认骚"],
    "🦋 体位局": ["后入", "骑乘", "面对面", "压腿", "站立", "69"],
    "🧊 感官局": ["冰块", "蜡烛", "羽毛", "蒙眼", "温差", "咬痕"],
    "👗 服装局": ["只穿衬衫", "女仆装", "情趣内衣", "项圈", "丝袜", "全裸围裙"],
}

# Truth pool (placeholder — extend freely)
# 真心话池:外置到 monopoly-truths.json(可扩·纯招供)·缺档回落这8张出厂兜底。渲染时行动方=答的人。
TRUTH_POOL = _load_json("monopoly-truths.json", [
    {"强度": 2, "内容": "行动方说出最想被对方做的三件事"},
    {"强度": 2, "内容": "行动方描述现在身体哪里最想被碰"},
    {"强度": 3, "内容": "行动方说一个从没告诉对方的性幻想"},
    {"强度": 3, "内容": "行动方坦白上次偷偷想着对方的时候做了什么"},
    {"强度": 4, "内容": "行动方说出最不敢让对方知道的一个kink"},
    {"强度": 4, "内容": "行动方描述对方身体最痴迷的部位和为什么"},
    {"强度": 5, "内容": "行动方说出高潮的时候脑子里在想什么"},
    {"强度": 5, "内容": "行动方坦白有没有想过跟别人做、想的是谁"},
])

# Mystery tile: good (40%) vs bad (60%)
MYSTERY_GOOD = [
    {"name": "⬅️ 推人", "effect": "push_opponent", "desc": "对手后退3格"},
    {"name": "💰 发财", "effect": "bonus_coins", "desc": "获得3币"},
    {"name": "🍀 捡钱", "effect": "found_coins", "desc": "路上捡到2币"},
    {"name": "🎴 摸卡", "effect": "free_card", "desc": "免费摸一张功能卡"},
]
MYSTERY_BAD = [
    {"name": "🔥 超级任务", "effect": "super_task", "desc": "强度直接5-6 不做交8币"},
    {"name": "💸 罚款", "effect": "fine", "desc": "交3币给对手"},
    {"name": "🔒 入狱", "effect": "go_jail", "desc": "直接进监狱"},
    {"name": "🎭 暴露", "effect": "expose", "desc": "对手选一个真心话你必须答"},
    {"name": "⏪ 倒退", "effect": "go_back", "desc": "后退5格"},
    {"name": "🫣 羞耻", "effect": "shame_task", "desc": "做一个羞耻展示任务 不能买断"},
]

# ── 跨局记忆(只针对任务·身份卡不去重) ─────────────────────
# 引擎本身只吃注入的 recent_tasks(躲开它);“历史存哪”是上层的事:
#   本地/单玩家 → 一个文件(下面 load_seen/save_seen)
#   托管 API 多人 → 每个玩家令牌一个文件 seen/<token>.json(见 monopoly_api.py)
# 按「局」记·不按条数·无时间限制·可手动清空。
GAMES_CAP = 10  # 只记最近这么多局(超出丢最旧·避不开会回落不饿死·扩库越大越不容易撞)

def _dedup_last(seq):
    """按「最后一次出现」保序去重:返回 oldest-last-seen -> newest-last-seen(recency 表用)。"""
    out, s = [], set()
    for c in reversed(list(seq)):
        if c not in s:
            s.add(c); out.append(c)
    out.reverse()
    return out

def _read_recency(path):
    """读 recency 有序表(oldest->newest)。兼容旧格式 {"games":[...]}(拍平按最后出现去重)/裸 list。"""
    p = Path(path)
    if p.exists():
        try:
            d = json.loads(p.read_text("utf-8"))
            if isinstance(d, dict):
                if "recency" in d:
                    return list(d.get("recency", []))
                if "games" in d:
                    return _dedup_last(t for g in d.get("games", []) for t in g)
            if isinstance(d, list):
                return _dedup_last(d)
        except Exception:
            pass
    return []

def load_seen(path):
    """读 recency 躲避集(有序 oldest->newest·喂 recent_tasks·引擎按它排 LRU:发最久没出过的)。"""
    return _read_recency(path)

def save_seen(path, this_game_tasks, cap=None):
    """把这局用过的任务并进 recency 表(挪到最新端)·写回。cap 留兼容·None=不截断(自然被库封顶·不随局数无限涨)。"""
    rec = _read_recency(path)
    merged = _dedup_last(rec + list(this_game_tasks))
    if cap:
        merged = merged[-cap:]
    _atomic_write(path, json.dumps({"recency": merged}, ensure_ascii=False))
    return merged

def clear_seen(path):
    """手动清空跨局历史(洗牌重来)。"""
    _atomic_write(path, json.dumps({"recency": []}, ensure_ascii=False))


class Game:
    MAX_HAND = 3
    # 淫纹持有者的部位表(开局偷 roll 一个·只引擎知道·guess_mark 才验中不中·★绝不进任何输出/status/state·防荷官剧透)。可改。
    MARK_SPOTS = ["耳垂", "后颈", "锁骨", "乳头", "腰侧", "肚脐", "大腿内侧", "膝窝", "脚踝", "手腕", "背脊", "臀"]

    def __init__(self, lineup="男女", flavor="medium",
                 p1_name="P1", p1_sex="男", p2_name="P2", p2_sex="女",
                 p1_role="攻", p2_role="受",
                 redline=None, seed_theme=None, p1_color="🔵", p2_color="🔴",
                 reverse_chance=0.3, recent_tasks=None, blocklist=None, player_token=None,
                 no_receive_anal=None, open_anal=None, no_penetration=None, dedup_key="", identity_mode="mixed", avoid_identities=None,
                 game_length=None, **_unknown):
        if _unknown:
            raise TypeError(
                f"Game() 不认识参数 {list(_unknown)}。正确开局(没有 players= 这种写法):\n"
                "  Game(p1_name='Alice', p1_sex='男', p1_role='攻',\n"
                "       p2_name='Bob', p2_sex='女', p2_role='受', redline=[])\n"
                "  性别填 男/女,角色填 攻/受;两男局加 lineup='男男',两女局 lineup='女女'。")
        assert lineup in ("男女", "男男", "女女")
        assert flavor in CURVES
        self.lineup, self.flavor = lineup, flavor
        self.p1, self.p2 = p1_name, p2_name
        self.sex = {p1_name: p1_sex, p2_name: p2_sex}
        self.role = {p1_name: p1_role, p2_name: p2_role}
        self.color = {p1_name: p1_color, p2_name: p2_color}
        self.redline = self._expand_redline(redline or [])
        # 后庭改「每人一个愿不愿被肛」开关(不在全局 redline 一刀切):
        # 后庭默认关(两人默认不收后庭·要玩开局显式开·每人独立)。异性恋vanilla不出肛·男玩家默认不出后穴/中性穴卡·顺带治「男roll出用穴」。
        self.receive_anal = {p1_name: False, p2_name: False}
        for _nm in (open_anal or []):                     # 谁愿意被后庭·开局显式开(每人独立开关)
            if _nm in self.receive_anal:
                self.receive_anal[_nm] = True
        if "后庭" in self.redline:                        # 老式全局 anal 红线=冗余(默认已关)·剥掉别当 kink 双重过滤
            self.redline = [r for r in self.redline if r != "后庭"]
        for _nm in (no_receive_anal or []):               # 兼容旧参数:显式关(默认已关·矛盾时关优先=偏安全)
            if _nm in self.receive_anal:
                self.receive_anal[_nm] = False
        # 「被插入」总开关(女女局:禁后庭挡不住阴道)。默认都可被插·设了 no_penetration 的人=纯top(任何孔阴道+后穴都不被插)。
        self.receive_pen = {p1_name: True, p2_name: True}
        for _nm in (no_penetration or []):
            if _nm in self.receive_pen:
                self.receive_pen[_nm] = False
        self.reverse_chance = max(0.0, min(1.0, reverse_chance))  # 踩格 30% 反转(权力翻转)
        # 跨局不重复:躲开「最近见过的任务」(上层从存档注入·谁存历史是上层的事)。
        # 软避让:躲不开会回落,不饿死。身份卡不去重(重复没事)。
        # 跨局去重(LRU):recent_tasks 有序 oldest->newest -> recency 名次(越大越近·没出过=-1最优先发)。
        self._set_recency(recent_tasks or [])
        # 这对玩家的永久黑名单(swap换掉的卡·硬排除·永不再出)。上层从 seen 注入。
        self.blocklist = set(blocklist or [])
        self.player_token = player_token   # 托管API:鉴权令牌(删局/看局)
        self.dedup_key = dedup_key         # 跨局去重key(名字+性别[+暗号]派生·AI不用记token)
        self.floor, self.ceil = CURVES[flavor]
        self.theme = seed_theme or random.choice(list(THEMES))
        self.pos = {p1_name: 0, p2_name: 0}
        self.coins = {p1_name: 5, p2_name: 5}
        self.items = {p1_name: [], p2_name: []}
        self.lap = {p1_name: 0, p2_name: 0}
        self.turn = p1_name
        self.history = set()
        self._recent_types = []   # 最近抽过的玩法类型(治腻:别连出同种)
        self._recent_kinks = []   # 最近抽过的 kink(治「同一个 act 反复来」:如一局 3 次口交)
        self.pending_task = {}    # 谁踩了任务格、待结算的那张卡(做完按强度给币)
        self.pending_toll = None  # 悬着的过路费账单{who,landlord,fee}:下轮roll开头默认自动交(账不许糊)
        self.pending_duel = None  # 悬着的对决{stake}:下轮roll前必须报赢家,赌注不许蒸发
        self.owner = {}           # 地盘:格号 → 占领者名字(做完任务白占)
        self.double_next = {}     # 加速卡:谁下一轮再掷一次
        self.jail_immune = {}     # 出狱卡:谁攒了几张免狱
        self.jailed = {}          # 监狱:谁还被关几轮(轮到时被绑任对方处置)
        self.turn_count = 0       # 已进行的回合数(强度升级 + 终局都看它·不看圈数)
        # 局长可选(写死24太长后半段散):总回合数·速玩12/正常18/超长24(默认)。escalate 曲线按它自适应(短局自然爬得陡)。
        self.total_rounds = max(4, min(60, int(game_length))) if game_length else 2 * ROUNDS_PER_PLAYER
        # 速玩(≤12轮)用密任务盘:功能格少、任务格多·节奏更紧凑。棋盘大小仍20格(不动 %20/range20)。
        self._special = SPECIAL_DENSE if self.total_rounds <= 12 else SPECIAL
        self.TILES = ["start" if i == 0 else self._special.get(i, "task") for i in range(20)]
        self._recent_strengths = []   # 防堵:最近3张抽出的强度(连3轮同强度→下一轮窗口保底+1·治medium盘67%全是3)
        self._rev_acc = random.random()   # 发牌式反转累加器(治体感偏高):每抽任务 +=reverse_chance,>=1 就反转并 -=1;只在真抽到反转卡时扣账(没货回退留账下次补)。起始给随机相位(非0):否则一局才~9抽、末尾零头(9×0.3=2.7只兑2)每局丢掉→系统性偏低;随机相位让期望兑现数正好=n×reverse_chance·方差仍小·单局体感稳
        # Card hand system
        self.hand = {p1_name: [], p2_name: []}
        # Identity card system — assign at start
        # 身份系统 v2:三档 identity_mode(off/mixed/nsfw_only)+跨局去重+每人每局1次重抽
        assert identity_mode in ("off", "mixed", "nsfw_only")
        self.identity_mode = identity_mode
        self._id_avoid = set(avoid_identities or [])      # 跨局去重:最近玩过的身份名(API 层从 seen 注入)
        self.identity_rerolled = {p1_name: False, p2_name: False}   # 每人每局 1 次身份重抽权
        self.task_rerolled = {p1_name: 0, p2_name: 0}     # task_reroll 钩子已消费次数
        self.swap_used = {p1_name: 0, p2_name: 0}         # 💱全民换任务已用次数
        self.swap_nopay = {}                              # 没币硬换的人:那道任务done时白工0币
        self.last_settle = {}                             # 每人最近一次done的底账(同回合swap反悔用:CLI即时结算也能换)
        self.identity = {}
        self.identity_since = {}                          # 每个身份从第几回合开始(机会格换身份任期保护)
        self._chance_swap_offer = None                    # 机会格保留身份后·谁有一次「可选主动换」
        self.mark_spot = {}                             # 淫纹部位(★偷 roll·绝不进任何输出·只 guess_mark 验)·★挪到 _assign_identity 前(它现在同步藏纹·bug根治)
        self.mark_found = {}                            # 淫纹是否已被对方猜中
        self._assign_identity(p1_name)
        self._assign_identity(p2_name)
        # 身份卡改造(把死 buff 全接真线 + 新机制):以下运行时状态全部 save/load 持久化
        self._id_events_used = set()                    # 处子首高潮等 once 型人判记账(防每局多领)
        self._extra_used = {p1_name: 0, p2_name: 0}     # 不知餍足加餐已用次数(每局上限见 effect quota)
        self.declared_persona = {}                      # 背德者自己宣布的背德身份(写进 identity_reminder)
        self._mark_guessed_turn = {}                    # 淫纹每轮限一猜(roll 开头清)
        self._final_settled = False                     # 终局收益(年上年下转账/淫纹守住)只结算一次
        self._init_marks()

    def _identity_pool(self):
        # 按三档过滤;nsfw 字段缺省算 False(兼容旧池)
        if self.identity_mode == "off":
            return []
        if self.identity_mode == "nsfw_only":
            pool = [i for i in IDENTITY_POOL if i.get("nsfw")]
            return pool or IDENTITY_POOL                  # nsfw池空(旧JSON)回落全池,别开天窗
        return IDENTITY_POOL

    def _assign_identity(self, who):
        pool = self._identity_pool()
        if not pool:                                      # identity_mode=off:不发身份
            self.identity[who] = {}
            return
        taken = {v.get("name") for v in self.identity.values() if v}   # 两人别撞同款
        fresh = [i for i in pool if i["name"] not in self._id_avoid and i["name"] not in taken]
        if not fresh:                                     # 软避让:躲不开就只避对方,不饿死
            fresh = [i for i in pool if i["name"] not in taken] or pool
        self.identity[who] = random.choice(fresh)
        # ★淫纹身份同步(bug根治):成为持有者→立刻roll藏纹部位;换离持有者→清掉幽灵纹。
        # 机会格换身份/reroll/swap_identity 都只走这里换身份·原来不roll mark_spot→换成淫纹后 guess_mark 认不出「不是持有者」;换离淫纹又残留幽灵纹(终局白拿+5)。
        _holder = any(e.get("type") == "mark_holder" for e in self.identity[who].get("effects", []))
        if _holder and who not in self.mark_spot:
            self.mark_spot[who] = random.choice(self.MARK_SPOTS)
            self.mark_found[who] = False
        elif not _holder and who in self.mark_spot:
            self.mark_spot.pop(who, None); self.mark_found.pop(who, None)
        self.identity_since[who] = self.turn_count        # 记任期起点(机会格<3轮保护)

    def reroll_identity(self, who):
        # 每人每局 1 次:抽到的身份实在演不下去可换一次(兔女郎条款)
        if self.identity_mode == "off":
            return "❌ 这局没开身份系统"
        if self.identity_rerolled.get(who):
            return f"❌ {who} 这局的重抽权已经用过了,认命演吧"
        old = self.identity.get(who, {}).get("name", "无")
        self.identity_rerolled[who] = True
        self._id_avoid.add(old)                           # 别又抽回同一张
        self._assign_identity(who)
        new = self.identity[who].get("name", "无")
        return f"🎭 {who} 弃演【{old}】→ 换上【{new}】(每局仅1次·已用完)"

    def _id_effect_val(self, who, etype, default=0):
        # 取某人身份钩子里某类型的 value(没有返回 default)
        for e in self.identity.get(who, {}).get("effects", []):
            if e.get("type") == etype:
                return e.get("value", True)
        return default

    def _init_marks(self):
        # 淫纹持有者:开局偷 roll 藏纹部位(只引擎知道·guess_mark 才验)。★幂等:_assign_identity 已 roll 的别覆盖。
        for p in (self.p1, self.p2):
            if p in self.mark_spot:
                continue
            if any(e.get("type") == "mark_holder" for e in self.identity.get(p, {}).get("effects", [])):
                self.mark_spot[p] = random.choice(self.MARK_SPOTS)
                self.mark_found[p] = False

    def _is_reversed(self, t, who):
        # 任务味道≠踩格人自己的角色且非「任意」= 这是一道反转任务(权力翻转)。跟 _task_payload 里判法一致(背德者靠它)。
        fl = t.get("flavor", "攻")
        return fl not in ("任意", self.role.get(who, "攻"))

    def _identity_task_bonus(self, who, pend):
        # 身份钩子给「做任务」的额外奖励币(身份卡改造·把纸面 buff 接真线)。返回额外币数(可负)。
        # 涵盖:modify_reward(主播/魅魔..)·strength_bonus(潮吹强度4+)·kink_coin(绳师绑/口腔期口/美食家口)·
        #      type_bonus(兽人服务/敏感感官/骚话精言语/痴汉感官×对方)·reverse_bonus(背德反转)·
        #      target_bonus(女仆对方/自恋狂自己)·serve_bonus(奴隶差遣)。kink_bonus(暴露狂翻倍)单列在 done() 不在这。
        t = pend["t"]
        kinks = t.get("kink", [])
        ptype = t.get("玩法类型", "")
        target = t.get("target", "")
        strength = t.get("强度", 1)
        reversed_ = self._is_reversed(t, who)
        is_serve = pend.get("serve", False)
        bonus = 0
        for e in self.identity.get(who, {}).get("effects", []):
            et = e.get("type"); val = e.get("value", 0)
            if et == "modify_reward":
                bonus += val
            elif et == "strength_bonus" and strength >= e.get("min", 4):
                bonus += val
            elif et == "kink_coin" and e.get("kink") in kinks:
                bonus += val
            elif et == "type_bonus" and ptype == e.get("玩法类型") and e.get("target") in (None, target):
                bonus += val                              # 可选 target 条件(痴汉=感官×对方·敏感=感官不限)
            elif et == "reverse_bonus" and reversed_:
                bonus += val
            elif et == "target_bonus" and target == e.get("target"):
                bonus += val
            elif et == "serve_bonus" and is_serve:
                bonus += val
        return bonus

    def _identity_reminder(self):
        # 双方身份的一行浓缩提醒(荷官每轮照念)。identity_mode=off 或旧身份无 hint 时尽量降级。
        parts = []
        for p in (self.p1, self.p2):
            ident = self.identity.get(p) or {}
            if ident:
                tag = ident.get('hint', ident.get('name', ''))
                if self.declared_persona.get(p):          # 背德者:自己宣布的身份挂进提醒·别让人设掉线
                    tag += f"·背德身份【{self.declared_persona[p]}】"
                if p in self.mark_spot and not self.mark_found.get(p):   # 🌀淫纹持有者:每轮把「可猜部位清单」给对方(只列全部候选·藏哪绝不泄)
                    tag += f"·🌀淫纹藏在下列某处等对方猜:{'/'.join(self.MARK_SPOTS)}"
                parts.append(f"{p}={tag}")
        return " ｜ ".join(parts) or None

    def reroll_task(self, who):
        # 消费身份的 task_reroll 钩子:悬着的任务换一道(照常给币,不算skip)
        quota = self._id_effect_val(who, "task_reroll", 0) or 0
        if self.task_rerolled.get(who, 0) >= quota:
            return {"result": f"❌ {who} 没有(或用完了)换任务的权利", "task": None}
        pend = self.pending_task.get(who)
        if not pend:
            return {"result": f"❌ {who} 没有悬着的任务可换", "task": None}
        t = self._draw_task(self._phase(), who=who)
        if not t:
            return {"result": "❌ 换不出新任务(库抽干了),原任务保留", "task": None}
        self.task_rerolled[who] = self.task_rerolled.get(who, 0) + 1
        self.pending_task[who] = {"t": t, "super": pend.get("super", False), "tile": pend.get("tile", self.pos[who])}
        payload = self._task_payload(t, who, 换过="🔄身份特权换的新任务")
        return {"result": f"🔄 {who} 用身份特权换了一道新任务", "task": payload}

    def swap_task(self, who, game_id=None):
        # 💱全民换任务:悬着的任务嫌弃/有毛病都能换——代价=赔对方1币;没币也能换但换来的做完不给币(白工);
        # 每人每局 SWAP_CAP 次;超级任务不换(有买断)。每次换记 monopoly-swap-log.jsonl=众包审卡(被换多的卡=有嫌疑)。
        pend = self.pending_task.get(who)
        revert_note = ""
        if not pend:
            ls = self.last_settle.get(who)
            if ls and ls.get("turn_count") == self.turn_count:
                # 同回合刚结算过(CLI即时结算)->回滚那笔账再换:退币/退占地/退告解抽成
                self.coins[who] -= ls["coin"]
                if ls.get("witness_w"):
                    self.coins[self._opponent(who)] -= ls["witness_w"]
                if ls.get("tile_claimed") is not None:
                    if ls.get("prev_owner") is None:
                        self.owner.pop(ls["tile_claimed"], None)
                    else:
                        self.owner[ls["tile_claimed"]] = ls["prev_owner"]
                pend = ls["pend"]
                self.pending_task[who] = pend
                self.last_settle.pop(who, None)
                revert_note = "(先退回刚结算的" + str(ls["coin"]) + "币和占地)"
            else:
                return {"result": f"❌ {who} 没有悬着的任务可换(要换得在下一次掷骰前)", "task": None}
        if pend.get("super"):
            return {"result": "❌ 超级任务不能换:要么做完(+5币)要么买断(8币·buyout)", "task": None}
        used = self.swap_used.get(who, 0)
        if used >= SWAP_CAP:
            return {"result": f"❌ {who} 本局换任务次数用完了({used}/{SWAP_CAP})", "task": None}
        old_t = pend["t"]
        if pend.get("truth"):
            t = self._draw_truth(self._phase())
            if not t:
                return {"result": "❌ 换不出新真心话·原题保留", "task": None}
            self.pending_task[who] = {"t": t, "super": False, "tile": pend.get("tile", self.pos[who]), "truth": True}
            payload = {"强度": t["强度"], "内容": self._render_text(t["内容"], who), "换过": f"💱换的新真心话({used+1}/{SWAP_CAP})"}
        else:
            t = self._draw_task(self._phase(), who=who)
            if not t:
                return {"result": "❌ 换不出新任务(这窗口的卡抽干了)·原任务保留", "task": None}
            self.pending_task[who] = {"t": t, "super": False, "tile": pend.get("tile", self.pos[who])}
            payload = self._task_payload(t, who, 换过=f"💱换的新任务({used+1}/{SWAP_CAP})")
        opp = self._opponent(who)
        if self.coins.get(who, 0) >= 1:
            self.coins[who] -= 1; self.coins[opp] += 1
            cost = f"赔 {opp} 1币(现{self.coins[who]})"
        else:
            self.swap_nopay[who] = True
            cost = "没币可赔→换来的这道做完不给币(白工)"
        self.swap_used[who] = used + 1
        self.blocklist.add(old_t["内容"])   # ★换掉的卡永久拉黑(这对以后永不再出;上层持久化进 seen)
        self._log_swap(who, old_t, t, cost, game_id)
        self.last_settle.pop(who, None)
        return {"result": f"💱 {who} 换了一道({used+1}/{SWAP_CAP})·以后不再出这道·{cost}{revert_note}", "task": payload, "blocked": old_t.get("内容")}

    def _log_swap(self, who, old_t, new_t, cost, game_id):
        # 换卡日志(众包审卡·失败别影响游戏)
        try:
            import time as _t
            rec = {"ts": int(_t.time()), "game_id": game_id, "who": who, "回合": self.turn_count,
                   "换掉": {"内容": old_t.get("内容"), "强度": old_t.get("强度"), "kink": old_t.get("kink"), "玩法类型": old_t.get("玩法类型")},
                   "换成": new_t.get("内容"), "代价": cost}
            with open(str(_DIR / "monopoly-swap-log.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def id_event(self, who, event):
        # 人判记账:玩家判定发生了某事·引擎管身份校验+次数上限,判定权在玩家。
        # 🫣处子 first_climax(+3·每局1次)·🤐禁言者 say_banned(-1给对方)·💋接吻魔 no_kiss_2turns(-1)。
        opp = self._opponent(who)
        for e in self.identity.get(who, {}).get("effects", []):
            et = e.get("type")
            if et == "id_event_reward" and e.get("event") == event:
                if e.get("once"):
                    key = f"{who}:{event}"
                    if key in self._id_events_used:
                        return f"❌ {who} 的【{event}】每局限一次·已经领过了"
                    self._id_events_used.add(key)
                v = e.get("value", 0); self.coins[who] += v
                return f"✨ {who} 触发【{event}】·+{v}币(现{self.coins[who]})"
            if et == "id_event_penalty" and e.get("event") == event:
                v = e.get("value", 1)
                if e.get("to") == "opponent":
                    pay = min(self.coins[who], v); self.coins[who] -= pay; self.coins[opp] += pay
                    return f"⚠️ {who} 犯规【{event}】·罚 {pay}币 给 {opp}(现{self.coins[who]})"
                self.coins[who] = max(0, self.coins[who] - v)
                return f"⚠️ {who} 犯规【{event}】·扣 {v}币(现{self.coins[who]})"
        return f"❌ {who} 身份没有【{event}】这个记账钩子(处子/禁言者/接吻魔才有)"

    def extra_task(self, who):
        # ➕不知餍足:每局限额主动加抽一道任务(做完照常拿币)。复用 _draw_task + 进 pending_task 结算。
        quota = self._id_effect_val(who, "extra_task", 0) or 0
        if quota <= 0:
            return {"result": f"❌ {who} 不是不知餍足·没有加餐特权", "task": None}
        used = self._extra_used.get(who, 0)
        if used >= quota:
            return {"result": f"❌ {who} 加餐次数用完了({used}/{quota})", "task": None}
        t = self._draw_task(self._phase(), who=who)
        if not t:
            return {"result": "❌ 加餐抽不出新任务(库抽干了)", "task": None}
        self._extra_used[who] = used + 1
        self.pending_task[who] = {"t": t, "super": False, "tile": self.pos[who]}
        payload = self._task_payload(t, who, 加餐=f"➕不知餍足加餐({used+1}/{quota})·做完照常给币")
        return {"result": f"➕ {who} 意犹未尽·加抽一道({used+1}/{quota})", "task": payload}

    def guess_mark(self, guesser, spot):
        # 🌀淫纹:对方每轮猜持有者一个部位·每轮限一猜·猜中对方+3(当轮生效)。spot 绝不外泄·只在这里验中不中。
        holder = self._opponent(guesser)
        if holder not in self.mark_spot:
            return f"❌ {holder} 不是淫纹持有者·没什么可猜的"
        if self.mark_found.get(holder):
            return f"✅ {holder} 的淫纹已经被找到过了(在{self.mark_spot[holder]})"
        if self._mark_guessed_turn.get(guesser):
            return f"❌ {guesser} 这轮已经猜过一次了·下轮再来"
        self._mark_guessed_turn[guesser] = True
        if spot == self.mark_spot[holder]:
            self.mark_found[holder] = True
            self.coins[guesser] += 3
            return f"💥 猜中!{holder} 的淫纹就在【{spot}】·当场腿软·{guesser} +3币(现{self.coins[guesser]})"
        return f"❌ {guesser} 摸了【{spot}】·没猜中·白摸(下轮再猜)"

    def declare_persona(self, who, text):
        # 🎭背德者:玩家自己宣布一个背德身份(老师/邻居/还俗的和尚…)·写进身份卡·之后 identity_reminder 自动带上。
        if not any(e.get("type") == "declare_persona" for e in self.identity.get(who, {}).get("effects", [])):
            return f"❌ {who} 不是背德者·不用宣布身份"
        text = (text or "").strip()
        if not text:
            return f"❌ 报一个背德身份(越禁忌越对味·比如 老师/兄长的未婚妻/还俗的和尚)"
        self.declared_persona[who] = text
        return f"🎭 {who} 的背德身份定为【{text}】·整局锁定用它说话和玩"

    def _opponent(self, who):
        return self.p2 if who == self.p1 else self.p1

    def _send_to_jail(self, who):
        # 进监狱:有免疫(越狱大师身份/出狱卡)则消耗并走过、返回提示;否则关 JAIL_TURNS 轮、棋子进第10格,返回 None。
        id_immune = any(e.get("type") == "immunity" and e.get("target") == "jail"
                        for e in self.identity.get(who, {}).get("effects", []))
        if id_immune:
            return f"{self.identity[who]['name']}免疫,潇洒走过"
        if self.jail_immune.get(who, 0) > 0:
            self.jail_immune[who] -= 1
            return f"用🔓出狱卡潇洒走过(剩{self.jail_immune[who]}张)"
        self.pos[who] = next((i for i, t in enumerate(self.TILES) if t == "jail"), 10)   # 动态查jail格(密盘在11·去硬编码)
        self.jailed[who] = JAIL_TURNS
        return None

    def _jail_turn(self, who):
        # 狱中回合:被关的人不掷骰,被绑、由对方点一道任务处置他(他不能反抗·不给币)。
        opp = self._opponent(who)
        out = {"who": who, "dice": None, "tile": "jail", "task": None,
               "mystery": None, "card": None, "truth": None, "jailed": True}
        t = self._draw_task(self._phase(), who=opp, force_desired="攻", require_target="对方")   # 对方主导·动作必须冲着被绑的人(target=对方·不漏 target=自己 的自摸卡)、强度按回合数
        if t:
            out["task"] = self._task_payload(t, opp, mechanic="⛓监狱处置", 狱中=f"🔒{who}被绑·任{opp}处置(不能反抗·无币)")
        sb = self._id_effect_val(who, "serve_bonus", 0) or 0   # ⛓️奴隶被处置也算被使唤·挣一点
        serve_note = ""
        if sb:
            self.coins[who] += sb
            serve_note = f"　⛓️{who}奴隶被使唤 +{sb}币"
        self.jailed[who] -= 1
        if self.jailed.get(who, 0) <= 0:
            self.jailed.pop(who, None)
            tail = "　🔓这轮完→释放,下个回合正常掷骰"
        else:
            tail = f"　还关{self.jailed[who]}轮"
        out["say"] = f"🔒 {who} 被关进监狱、双手反绑动弹不得——这一轮，{opp} 可以对 ta 为所欲为！{tail}{serve_note}"
        self.turn = opp
        out["board"] = self.board_art()
        return out

    def _sleep_turn(self, who, dice):
        # 😴睡美人沉睡轮:掷出 1/6 → 这轮不走格·任对方处置(像迷你监狱·需吻醒)·醒来 +1币(睡后补偿)。
        opp = self._opponent(who)
        out = {"who": who, "dice": dice, "tile": "sleep", "task": None,
               "mystery": None, "card": None, "truth": None, "jailed": False, "asleep": True,
               "identity_reminder": self._identity_reminder()}
        t = self._draw_task(self._phase(), who=opp, force_desired="攻", require_target="对方")   # 对方处置·冲着睡着的人(target=对方)
        if t:
            out["task"] = self._task_payload(t, opp, mechanic="😴睡美人处置", 沉睡=f"😴{who}睡着·任{opp}处置·需吻醒·{who}醒来+1币")
        self.coins[who] += 1
        self.turn = opp
        out["say"] = f"😴 {who} 掷出 {dice} 陷入沉睡、任人摆布——这一轮，{opp} 可以对熟睡的 ta 为所欲为(需吻醒)，醒来 +1币"
        out["board"] = self.board_art()
        return out

    def _redline_content_ok(self, content):
        # 内容兜底红线:卡的 kink 标漏了·按内容高置信关键词也挡。命中任一激活红线→不发。
        for tag in self.redline:
            rx = _RL_CONTENT.get(tag)
            if rx and rx.search(content or ""):
                return False
        return True

    @staticmethod
    def _expand_redline(redline):
        # 开关词展开成 tag 子串;非开关词原样保留(直传 tag 子串仍可用)。幂等:存档回灌不会二次展开。
        out = []
        for r in redline:
            if r in REDLINE_SWITCHES:
                out.extend(REDLINE_SWITCHES[r])
            else:
                out.append(r)
        return out

    def _window(self, lap, mod=0):
        # escalate 曲线(再重的盘也要有热起来的过程,治「medium开局直接roll到插入」):
        # 窗口随回合数连续爬升——下限从盘的地板爬到 ceil-1,窗口宽 2~3 档保留起伏;
        # 前 2 回合热身保护:封顶 floor+1,开局绝不上来就"做"。(lap 参数留着兼容旧调用,不再使用)
        # 实战两处调:①总回合=self.total_rounds(局长可选·速玩局斜率自然变陡) ②int→round(下限爬太慢·medium前半场死锁在2)
        # 身份强度修正 mod(Daddy/发情期+1·冷淡期-2)喂进来·让盘顶/热身/前半场三道钳位
        #   成为最终裁决——身份加成只在盘内挪强度、绝不击穿(治 light 开局被 Daddy+1 顶出强度3滴蜡)。
        prog = min(1.0, self.turn_count / self.total_rounds)
        span = self.ceil - self.floor
        lo = self.floor + int(prog * max(0, span - 1) + 0.5)   # 真四舍五入(round是银行家舍入·0.5会归0=白改)
        if self.turn_count > self.total_rounds * 3 // 4:   # 高潮尾段(最后1/4):地板锁最高档·让插入稳定出(治⑥太稀·别只开门不来货)
            lo = self.ceil
        lo = max(self.floor, lo + mod)                     # 身份修正抬/压起点·夹盘地板(冷淡期-2不破底)
        hi = lo + 2
        # 本回合硬上限 cap:盘顶封死(不是全局6) + 前半场不开顶 + 前2回合热身——lo 和 hi 都夹进它,
        #   身份+1 绝不击穿任何一道(治 light 被 Daddy+1 顶出滴蜡·治 endgame lo=ceil+mod 超顶)。
        cap = self.ceil
        if self.turn_count <= self.total_rounds // 2:      # 前半场:最高档(ceil)留到后半场才开(「插入半场才开」)
            cap = min(cap, self.ceil - 1)
        if self.turn_count <= 2:                           # 热身:前2回合绝不上来就重
            cap = min(cap, self.floor + 1)
        lo = min(lo, cap)                                  # ★lo 也夹进 cap(否则 endgame/warmup 的 hi=max 会被 lo 顶破)
        hi = min(hi, cap)
        hi = max(hi, lo)                                   # 别倒挂(此时 lo,hi 都≤cap → 保证不超盘顶/热身)
        return (lo, hi)

    def _phase(self):
        # 强度按回合数(不看圈数):前半场前戏(0)、后半场高潮(1)。两人同步升温·不被监狱/回退拖累。
        return 0 if self.turn_count <= self.total_rounds // 2 else 1

    def is_over(self):
        # 终局:两人合计掷满 total_rounds 回合(轮流掷·天然同时到·谁都不用等)。
        return self.turn_count >= self.total_rounds

    def _intensity_mod(self, who):
        mod = 0
        for e in self.identity.get(who, {}).get("effects", []):
            if e.get("type") == "modify_intensity":
                mod += e.get("value", 0)
        return mod

    @staticmethod
    def _need_ok(need, sex):
        return need == "任意" or need == sex

    def _servable(self, t, lander_sex, partner_sex):
        # 解耦路由:行动方=踩格人(lander)、对方=对手(partner);两边性别需求都配得上才发。
        return (self._need_ok(t.get("行动方需", "任意"), lander_sex) and
                self._need_ok(t.get("对方需", "任意"), partner_sex))

    def _anal_ok(self, t, who):
        # 被肛开关(机制版·活判):后庭不是静态标签能定死的——同一个「穴」·长男人身上=后庭·长女人身上=阴道·
        # 得看这局渲染到谁身上现算。谁的「穴/后庭」被玩、且那对他是肛(男的裸穴 or 明确后庭)、且他关了被肛 → 不发。
        opp = self._opponent(who)
        recv = t.get("穴承受方") or t.get("后庭承受方")   # 谁的穴被玩(新字段·兼容旧 后庭承受方)
        if t.get("target") == "彼此":                       # 彼此=互相=两人都受·穴承受方标歪了(如标成"行动方")也以 target 为准·两边都查(治④对决漏肛)
            recv = "双方"
        explicit = "后庭" in t.get("kink", [])              # 明确肛交=对谁都是后庭(含女方)
        if recv == "行动方" or recv == "自己":  receivers = [who]
        elif recv == "对方":                    receivers = [opp]
        elif recv == "双方":                    receivers = [who, opp]
        elif recv == "无" and not explicit:     receivers = []                                            # 判定卡里没孔被插(口交/展示/磨蹭不入)=无承受方·放行
        elif explicit:                          receivers = [who, opp] if t.get("target") == "彼此" else ([who] if t.get("target") == "自己" else [opp])  # 后庭标了却没承受方=旧兜底(彼此=两边都算)
        else:                                   receivers = None
        # 骑乘活判兜底:骨架有「骑乘吞性器」→骑的人(=受动方的对手)用自己的孔套这根性器=孔被插·
        # 不靠穴承受方标对·运行时从骨架现算(根治骑乘盲区·#562「对方骑乘套弄鸡巴」漏对方后穴)。
        ride = set()
        for seg in (t.get("骨架") or []):
            if seg.get("动作") == "骑乘" and seg.get("受动部位") in ("鸡巴", "龟头", "假鸡巴"):
                sub = seg.get("受动方")
                rider = opp if sub == "行动方" else (who if sub == "对方" else None)
                if rider:
                    ride.add(rider)
        if ride:
            receivers = list(ride) if receivers is None else list(set(receivers) | ride)
        if receivers is not None:
            for r in receivers:
                anal_for_r = explicit or self.sex.get(r) == "男"   # 显式后庭=对谁都肛;裸穴=只对男的才是肛
                if anal_for_r and not self.receive_anal.get(r, True):
                    return False
            return True
        # 安全网兜底:没标承受方也没后庭 tag——大多无关;但只要有男玩家关了被肛 + 卡里有中性「穴」,
        # 可能就是他后庭,保守不发(错也错在安全那头·扩库补上承受方后这条几乎不触发)。
        if any(self.sex.get(p) == "男" and not self.receive_anal.get(p, True) for p in (self.p1, self.p2)):
            if _NEUTRAL_HOLE_RE.search(t.get("内容", "")):
                return False
        return True

    def _pen_ok(self, t, who):
        # 「被插入」总开关(女女局纯top):设了 no_penetration 的人·任何孔(阴道/后穴/中性穴)都不被插。
        # 默认都可被插(receive_pen 全 True)→ 快速放行·不影响现状。
        if self.receive_pen.get(self.p1, True) and self.receive_pen.get(self.p2, True):
            return True
        opp = self._opponent(who)
        recv = t.get("穴承受方") or t.get("后庭承受方")    # 谁的下体孔被插(阴道/后穴/中性穴都算)
        if t.get("target") == "彼此":
            recv = "双方"
        receivers = set()
        if recv == "行动方" or recv == "自己":  receivers = {who}
        elif recv == "对方":                    receivers = {opp}
        elif recv == "双方":                    receivers = {who, opp}
        # ★骨架判被插方(不靠穴承受方标注·治大量None穴承受方漏):任何孔(穴/后穴/阴道)被插/玩=那受动方被插
        _m = {"行动方": who, "对方": opp}
        for seg in (t.get("骨架") or []):
            动, 部 = seg.get("动作"), seg.get("受动部位")
            if 动 in ("插入", "手", "舔", "揉捏", "摸", "口", "骑乘") and 部 in ("穴", "后穴", "阴道"):
                r = _m.get(seg.get("受动方"))
                if r: receivers.add(r)
            if 动 == "骑乘" and 部 in ("鸡巴", "龟头", "假鸡巴"):   # 骑乘吞性器:骑的人孔被插
                sub = seg.get("受动方")
                rider = opp if sub == "行动方" else (who if sub == "对方" else None)
                if rider: receivers.add(rider)
        if "后庭" in (t.get("kink", []) or []) and not receivers:   # 显式后庭没标承受方=旧兜底
            receivers = {who, opp} if t.get("target") == "彼此" else ({who} if t.get("target") == "自己" else {opp})
        for r in receivers:
            if not self.receive_pen.get(r, True):          # 被插的人声明了纯top → 这卡不发
                return False
        return True

    def _set_recency(self, ordered):
        """跨局 recency(有序 oldest->newest)-> 名次(越大越近出过);没出过 -> -1(最优先发)。LRU 去重真相源。"""
        self._avoid = set(ordered)                       # 兼容:仍留个集合
        self._recency = {c: i for i, c in enumerate(ordered)}

    def _recency_rank(self, content):
        return self._recency.get(content, -1)            # 没出过=-1(比任何出过的都老=最优先)

    def _lru_tier(self, cands):
        """跨局最久没出过的那一档(没出过=-1最优先)·返回同名次全部候选(档内可再挑变异)。"""
        if not cands:
            return cands
        best = min(self._recency_rank(t["内容"]) for t in cands)
        return [t for t in cands if self._recency_rank(t["内容"]) == best]

    def _lru_pick(self, cands):
        """LRU 发一张:最久没出过那档里随机(真心话/对决无变异层时用)。"""
        tier = self._lru_tier(cands)
        return random.choice(tier) if tier else None

    def _draw_task(self, lap, intensity_override=None, who=None, force_desired=None, require_target=None, apply_mod=True):
        who = who or self.turn
        if intensity_override:
            lo, hi = intensity_override
        else:
            # 身份修正喂进 _window(盘顶/热身/前半场钳位=最终裁决·治 light 被 Daddy+1 顶出滴蜡)
            lo, hi = self._window(lap, self._intensity_mod(who) if apply_mod else 0)
        # 防堵(实战:medium盘15轮10轮强度3):连3张同强度→这一张窗口下限保底+1;抽不到再回落原窗口·不饿死
        lo_unjam = lo
        if (intensity_override is None and len(self._recent_strengths) >= 3
                and len(set(self._recent_strengths[-3:])) == 1):
            jam = self._recent_strengths[-1]
            if lo <= jam < hi:
                lo = jam + 1
        lander_sex = self.sex.get(who)
        partner_sex = self.sex.get(self._opponent(who))
        def base(t, ignore_block=False):
            # 强度窗口 + 解耦需求匹配(行动方=踩格人/对方=对手)+ 不撞红线(kink ∩ redline)+ 不在黑名单
            return (lo <= t.get("强度", 0) <= hi and
                    t.get("玩法类型") != "互相" and                        # 互相=对决专用·别漏进单人主导格(监狱被绑者/普通格谁踩谁做/过路费地主处置/终极支配)
                    self._servable(t, lander_sex, partner_sex) and
                    not (set(t.get("kink", [])) & set(self.redline)) and
                    self._redline_content_ok(t.get("内容", "")) and
                    self._anal_ok(t, who) and
                    self._pen_ok(t, who) and
                    (ignore_block or t.get("内容") not in self.blocklist) and   # swap拉黑的永不出
                    (require_target is None or t.get("target") == require_target))
        pool = [t for t in LIB if base(t)]
        if not pool and lo != lo_unjam:   # 防堵抬高后没货 → 回落原窗口(宁重复强度也别发不出任务)
            lo = lo_unjam
            pool = [t for t in LIB if base(t)]
        if not pool and self.blocklist:   # 黑名单把这窗口拉空了 → 回落忽略黑名单(宁重复也别发不出·极端)
            pool = [t for t in LIB if base(t, ignore_block=True)]
        if not pool:
            return None
        # 发牌式反转(治「体感比0.3高」):不再每次独立掷骰(小样本忽高忽低),改累加器铺开+只在真兑现时扣账。
        # 强制回合(force_desired:地主/监狱/终极)不占反转配额——它们是机制主导,标签也另算(见 _task_payload mechanic)。
        lander_role = self.role.get(who, "攻")
        other_role = "受" if lander_role == "攻" else "攻"
        want_reverse = False
        if force_desired:
            desired = force_desired
        else:
            self._rev_acc += self.reverse_chance
            want_reverse = self._rev_acc >= 1.0
            desired = other_role if want_reverse else lander_role
        rk = set(self._recent_kinks)
        def _kink_ok(t):
            ks = t.get("kink", [])
            return not ks or not (set(ks) & rk)   # 无 kink 任务(做/骑乘那种)自由通过;有 kink 的躲开最近抽过的·治同一个 act 反复来
        climax = intensity_override is None and self.turn_count > self.total_rounds * 3 // 4   # 高潮尾段(最后1/4)
        def _is_ins(t):
            return any(s.get("动作") == "插入" for s in (t.get("骨架") or []))
        def pick(group):
            # 跨局新鲜第一优先(LRU:先取最久没出过的一档·治「同一张卡老回来」)→ 档内再挑变异(换玩法类型/换 kink·治腻)→ 高潮尾段优先插入。
            noh = [t for t in group if t["内容"] not in self.history]   # 本局没出过(硬)
            fresh = self._lru_tier(noh or group)   # 最久没出过那一档(没出过的优先)——跨局新鲜比「别连出同类型」更重要(整张卡重复更扎眼)
            a = [t for t in fresh if t.get("玩法类型") not in self._recent_types]
            a0 = [t for t in a if _kink_ok(t)]   # 换玩法类型 + 换 kink(治一局 3 次口交)
            bk = [t for t in fresh if _kink_ok(t)]
            g = a0 or bk or a or fresh
            if climax:                            # 高潮尾段:优先真「插入」卡(治⑥太稀)
                gi = [t for t in g if _is_ins(t)]
                if gi: g = gi
            return random.choice(g) if g else None
        t = pick([x for x in pool if x.get("flavor") in (desired, "任意")])
        if t is None:
            t = pick(pool)   # 想要味道没货(该反转但没反转卡)→ 有啥抽啥
        if t is None:
            return None
        if want_reverse and t.get("flavor") == other_role:
            self._rev_acc -= 1.0   # 真抽到反转卡才扣账;没货回退(抽到自己角色/任意)不扣→欠的反转下次补上·长期精确=reverse_chance
        self.history.add(t["内容"])
        self._recent_types = ([t.get("玩法类型")] + self._recent_types)[:2]   # 记最近2个玩法类型(铺开)
        self._recent_kinks = (list(t.get("kink", [])) + self._recent_kinks)[:4]   # 记最近抽过的 kink(躲开·治同 act 反复:如口交一局 3 次)
        self._recent_strengths = (self._recent_strengths + [t.get("强度", 0)])[-3:]   # 喂防堵计数
        return t

    def _draw_truth(self, lap):
        lo, hi = self._window(lap)
        safe = ([t for t in TRUTH_POOL if self._redline_content_ok(t.get("内容", "")) and t.get("内容") not in self.blocklist]
                or [t for t in TRUTH_POOL if self._redline_content_ok(t.get("内容", ""))])   # 避红线+黑名单(空了回落只避红线)
        cands = [t for t in safe if lo <= t.get("强度", 0) <= hi] or safe or TRUTH_POOL
        noh = [t for t in cands if t["内容"] not in self.history] or cands   # 本局没出过(硬)
        pick = self._lru_pick(noh)                                          # 跨局 LRU:发最久没答过的真心话(治跨局重复)
        self.history.add(pick["内容"])
        self._recent_strengths = (self._recent_strengths + [pick.get("强度", 0)])[-3:]   # 真心话强度也算轮次·喂防堵计数
        return pick

    def _draw_duel(self, lap):
        # 同格对决:抽一张「互相」类任务(双方对撩·谁先破功谁输);避开红线 + 性别匹配(否则男女局会漏进女/女的互相卡·如一起揉阴蒂)。
        lo, hi = self._window(lap)
        ls = self.sex.get(self.turn); ps = self.sex.get(self._opponent(self.turn))
        def ok(t, ignore_block=False):
            return (t.get("玩法类型") == "互相" and not (set(t.get("kink", [])) & set(self.redline))
                    and self._redline_content_ok(t.get("内容", ""))
                    and self._servable(t, ls, ps) and self._anal_ok(t, self.turn) and self._pen_ok(t, self.turn)
                    and (ignore_block or t.get("内容") not in self.blocklist))   # 黑名单
        cands = ([t for t in LIB if ok(t) and lo <= t.get("强度", 0) <= hi] or [t for t in LIB if ok(t)]
                 or [t for t in LIB if ok(t, ignore_block=True)])
        if not cands:
            return None
        noh = [t for t in cands if t["内容"] not in self.history] or cands   # 本局没出过(硬)
        t = self._lru_pick(noh)                                             # 跨局 LRU:发最久没出过的对决卡(治跨局重复)
        self.history.add(t["内容"])   # 抽完登记·别的抽卡路径也躲得开(治「对决卡后面又被监狱/普通格抽到」)
        self._recent_strengths = (self._recent_strengths + [t.get("强度", 0)])[-3:]   # 对决强度也算轮次·喂防堵计数
        return t

    def _render_text(self, text, who):
        # 行动方→踩格的人(who),对方→对手。「自己」=who 本人,不动。
        return text.replace("行动方", who).replace("对方", self._opponent(who))

    def _render(self, t, who):
        return self._render_text(t["内容"], who)

    def _dice_vs(self, who):
        # 掷骰子比大小(治「猜拳/石头剪刀布」这类文爱做不了的真实博弈):行动方 vs 对方各掷一次,平局重掷。
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        while d1 == d2:
            d1, d2 = random.randint(1, 6), random.randint(1, 6)
        return d1 > d2, d1, d2

    def _task_payload(self, t, who, mechanic=None, **extra):
        # 统一造任务字典:箭头/渲染按「踩格人=行动方」相对算,标出味道(含反转)。
        # mechanic:强制回合(地主/监狱/睡美人)传机制名→标机制主导·不叫🔄反转(反转只归 reverse_chance 配额管·治「体感比0.3高」)。
        partner = self._opponent(who)
        fl = t.get("flavor", "攻")
        mutual = t.get("target") == "彼此"   # 互相类专用值(合法化):两人同时对做·箭头显示↔
        arrow_target = "自己" if t.get("target") == "自己" else partner
        if mechanic:
            label = mechanic   # 机制逼出的支配(👑地主/⛓监狱/😴睡美人),不是惊喜反转·不占反转配额
        else:
            reversed_ = fl not in ("任意", self.role.get(who, "攻"))   # 味道≠自己角色且非任意 = 反转
            if reversed_:
                label = "🔄反转·" + ("变强势主导" if fl == "攻" else "被服务/服从")
            else:
                label = {"攻": "攻主动·dom", "受": "受主动·sub", "任意": "中性·任意"}.get(fl, fl)
        if t.get("resolve") == "dice_vs":
            # 赢/输两个分支都只用「行动方/对方」两个已经锁好性别的身份写,不引入新身份 → 不会错位。
            win, d1, d2 = self._dice_vs(who)
            note = f"🎲{who}掷{d1}·{partner}掷{d2} → {who if win else partner}赢!　"
            branch = t["内容"] if win else t.get("内容_输", t["内容"])
            content = note + self._render_text(branch, who)
        else:
            content = self._render(t, who)
        p = {"强度": f"{t['强度']} {LEVEL_NAME[t['强度']]}", "玩法类型": t.get("玩法类型", ""),
             "kink": "/".join(t.get("kink", [])) or "-",
             "dir": f"{who}↔{partner}" if mutual else f"{who}→{arrow_target}", "flavor": label, "内容": content}
        p.update(extra)
        return p

    def board_art(self):
        c1, c2 = self.color[self.p1], self.color[self.p2]
        line = "".join("[" + (c1 if self.pos[self.p1] == i else "") + (c2 if self.pos[self.p2] == i else "") +
                       TILE_EMOJI[self.TILES[i]] + "]" for i in range(20))
        id1 = self.identity.get(self.p1, {}).get("name", "无")
        id2 = self.identity.get(self.p2, {}).get("name", "无")
        hand1 = ",".join(c["name"] for c in self.hand[self.p1]) if self.hand[self.p1] else "空"
        hand2 = ",".join(c["name"] for c in self.hand[self.p2]) if self.hand[self.p2] else "空"
        bag1 = f" · 🎒[{','.join(self.items[self.p1]) or '空'}]" if COLLECTIBLES_ENABLED else ""
        bag2 = f" · 🎒[{','.join(self.items[self.p2]) or '空'}]" if COLLECTIBLES_ENABLED else ""
        prog = f"　〔回合 {self.turn_count}/{self.total_rounds}〕"
        return (line + prog +
                f"\n{c1}{self.p1}@{self.pos[self.p1]}(第{self.lap[self.p1]+1}圈) · 💰{self.coins[self.p1]}{bag1} · 🃏[{hand1}] · 身份:{id1}"
                f"\n{c2}{self.p2}@{self.pos[self.p2]}(第{self.lap[self.p2]+1}圈) · 💰{self.coins[self.p2]}{bag2} · 🃏[{hand2}] · 身份:{id2}")

    def roll(self, dice=None, guess=None, swap_identity=False):
        who = self.turn
        if isinstance(dice, str):   # 容错:别人常误把玩家名当参数传(roll("Bob"))——谁掷由轮次自动决定,忽略它
            dice = None
        if self.is_over():
            return {"who": who, "game_over": True, "tile": None, "task": None,
                    "mystery": None, "card": None, "truth": None,
                    "say": f"🏁 游戏结束(满{self.total_rounds}回合)!看看谁赢了、砸最后那道终极指令",
                    "board": self.board_art()}
        self.turn_count += 1
        self._mark_guessed_turn = {}   # 🌀淫纹每轮限一猜:新一轮清空(治对方一轮猛猜)
        # 狱中回合:被关的人这轮不掷骰,被绑任对方处置(不能反抗)
        if self.jailed.get(who, 0) > 0:
            return self._jail_turn(who)
        d = dice or random.randint(1, 6)
        # 🎰赌徒:掷骰押大小(1-3小/4-6大)·押中+1押错-1(gamble_guess 钩子;guess 传 "大"/"小")
        gamble_note = ""
        if guess in ("大", "小") and self._id_effect_val(who, "gamble_guess", False):
            hit = (guess == "大") == (d >= 4)
            self.coins[who] = max(0, self.coins[who] + (1 if hit else -1))
            gamble_note = f"　🎰押{guess}{'中✓+1' if hit else '错✗-1'}币"
        # 😴睡美人:掷出 1 或 6 → 这轮陷入沉睡·任对方处置·需吻醒·醒来+1(sleep_beauty 钩子)
        if d in (1, 6) and self._id_effect_val(who, "sleep_beauty", False):
            return self._sleep_turn(who, d)
        swap_note = ""
        if self._chance_swap_offer == who:                # 上次踩机会格身份还新·保留了·这轮玩家可选主动换
            if swap_identity and self.identity_mode != "off":
                old_id = self.identity.get(who, {}).get("name", "无")
                if old_id != "无":
                    self._id_avoid.add(old_id)
                self._assign_identity(who)
                swap_note = f"　🎴(你选择换掉刚保留的身份 → {self.identity[who].get('name','无')})"
            self._chance_swap_offer = None                # 决定过/过期了,清掉
        old = self.pos[who]; new = (old + d) % 20
        passed_start = new < old      # 越过起点(过圈)·+2币要在 say 里播报(静默到账玩家以为算错)
        if passed_start:
            self.lap[who] += 1; self.coins[who] += 2 + (self._id_effect_val(who, "lap_bonus", 0) or 0)
        self.pos[who] = new
        kind = self.TILES[new]
        out = {"who": who, "dice": d, "tile": kind, "task": None, "mystery": None, "card": None, "truth": None,
               "identity_reminder": self._identity_reminder()}   # 每轮带双方身份浓缩提醒(免得玩家和AI忘了自己是谁)

        if kind == "task":
            owner = self.owner.get(new)
            if owner and owner != who and self._id_effect_val(who, "toll_free", False):
                # 踩者有 toll_free 身份钩子(奴隶等):免过路费免差遣,潇洒走过
                out["say"] = f"🎲 {who} 掷 {d} → 第{new}格 · 🚩{owner} 的地盘,但 {self.identity[who].get('name','')} 身份免过路费,潇洒走过"
            elif owner and owner != who:
                # 踩进对方地盘 → 交过路费 or 听凭地主差遣(地主当行动方出一道)。
                serve_only = bool(self._id_effect_val(owner, "toll_serve_only", False))   # 🍯蜜罐:地盘不收钱·只收差遣
                fee = 3 + (self._id_effect_val(owner, "toll_plus", 0) or 0)                # 👑暴君:过路费 +1(3→4·原翻倍太狠)
                opts = (f"🍯{owner}是蜜罐·地盘不收钱,只能听凭差遣做下面这道(g.settle_pending_toll('serve'))"
                        if serve_only else
                        f"交{fee}币过路费(g.pay_toll('{who}')) 或 听凭差遣做下面这道")
                out["toll"] = {"landlord": owner, "fee": fee, "serve_only": serve_only, "options": opts}
                # 挂账(金币账不许糊):不处理就掷下一轮的话,roll 开头默认自动交钱(蜜罐则默认差遣)——白嫖之路封死
                self.pending_toll = {"who": who, "landlord": owner, "fee": fee, "serve_only": serve_only}
                dt = self._draw_task(self._phase(), who=owner, force_desired="攻", require_target="对方")   # 地主出题·地主主导·对踩进地盘的人发号施令(target=对方)
                if dt:
                    tail = "" if serve_only else f";交{fee}币过路费可免"
                    out["task"] = self._task_payload(dt, owner, mechanic="👑地主主导", 差遣=f"{owner}的地盘·听凭差遣(做完无币{tail})")
                out["say"] = f"🎲 {who} 掷 {d} → 第{new}格 · 🚩踩进 {owner} 的地盘!"
            else:
                t = self._draw_task(self._phase(), who=who)
                if t:
                    self.pending_task[who] = {"t": t, "super": False, "tile": new}   # 存踩格时的格号:lazy结算时人可能已被推走,占地按这个
                    reward = "完成→按强度得币" + (f"+抽【{self.theme}】" if COLLECTIBLES_ENABLED else "")
                    out["task"] = self._task_payload(t, who, 完成奖励=reward)
                rev = f"　🔄反转!这道{who}{'临时变强势主导' if t and t.get('flavor')=='攻' else '临时被服务/被支配'}(权力对调·reverse抽中了)" if (t and self._is_reversed(t, who)) else ""
                out["say"] = f"🎲 {who} 掷 {d} → 第{new}格 · 🎯动作任务" + ("(你的地盘)" if owner == who else "") + rev

        elif kind == "truth":
            tr = self._draw_truth(self._phase())
            # 答了就是做了:真心话跟动作任务一样进 pending_task·按强度给币(lazy:下轮roll自动结算/不想答可skip)。
            # 真心话格是特殊格·done() 里 TILES 判型天然不占地。
            self.pending_task[who] = {"t": tr, "super": False, "tile": new, "truth": True}
            out["truth"] = {"强度": tr["强度"], "内容": self._render_text(tr["内容"], who)}   # 真心话也渲染(行动方=答的人·治新卡「行动方说出」没换名字)
            out["say"] = f"🎲 {who} 掷 {d} → 第{new}格 · 💬真心话(答完给币)"

        elif kind == "mystery":
            luck = self._id_effect_val(who, "mystery_luck", 0.4)   # 🍀幸运儿:好事概率 0.4→0.75
            is_good = random.random() < luck
            if is_good:
                evt = random.choice(MYSTERY_GOOD)
                out["mystery"] = {"type": "good", "name": evt["name"], "desc": evt["desc"], "effect": evt["effect"]}
                if evt["effect"] == "push_opponent":
                    opp = self._opponent(who)
                    self.pos[opp] = max(0, self.pos[opp] - 3)
                elif evt["effect"] == "bonus_coins":
                    self.coins[who] += 3
                elif evt["effect"] == "found_coins":
                    self.coins[who] += 2
                elif evt["effect"] == "free_card":
                    c = random.choice(CARD_POOL)
                    if len(self.hand[who]) < self.MAX_HAND:
                        self.hand[who].append(c)
                        out["mystery"]["result"] = f"摸到【{c['name']}】"
                    else:
                        out["mystery"]["result"] = f"摸到【{c['name']}】但手牌满,先弃一张再收"
            else:
                evt = random.choice(MYSTERY_BAD)
                out["mystery"] = {"type": "bad", "name": evt["name"], "desc": evt["desc"], "effect": evt["effect"]}
                if evt["effect"] == "super_task":
                    lo, hi = self._window(self._phase())
                    super_lo = min(hi + 1, 6); super_hi = min(hi + 2, 6)
                    t = self._draw_task(self._phase(), intensity_override=(super_lo, super_hi), who=who)
                    if t:
                        self.pending_task[who] = {"t": t, "super": True, "tile": new}
                        out["task"] = self._task_payload(t, who, buyout="做完→+5币;不做花8币买断")
                elif evt["effect"] == "fine":
                    opp = self._opponent(who)
                    transfer = min(self.coins[who], 3)
                    self.coins[who] -= transfer; self.coins[opp] += transfer
                elif evt["effect"] == "go_jail":
                    self._send_to_jail(who)
                elif evt["effect"] == "go_back":
                    self.pos[who] = max(0, self.pos[who] - 5)
                elif evt["effect"] == "expose":          # 暴露:对手指定一道真心话,你必须答
                    tr = self._draw_truth(self._phase())
                    out["truth"] = {"强度": tr["强度"], "内容": self._render_text(tr["内容"], who)}   # 真心话也渲染(行动方=答的人·治新卡「行动方说出」没换名字)
                elif evt["effect"] == "shame_task":       # 羞耻:做一道任务·不能买断·做完照常给币
                    t = self._draw_task(self._phase(), who=who)
                    if t:
                        self.pending_task[who] = {"t": t, "super": False, "tile": new}
                        out["task"] = self._task_payload(t, who, 羞耻="🫣羞耻展示·不能买断·做完照常给币")
            out["say"] = f"🎲 {who} 掷 {d} → 第{new}格 · ❓未知格 → {evt['name']}"

        elif kind == "chance":
            # Draw a card + redraw identity
            card = random.choice(CARD_POOL)
            if len(self.hand[who]) < self.MAX_HAND:
                self.hand[who].append(card)
                out["card"] = {"drawn": card["name"], "desc": card["description"], "stored": True}
            else:
                out["card"] = {"drawn": card["name"], "desc": card["description"], "stored": False,
                               "msg": f"手牌已满({self.MAX_HAND}张),弃一张再收"}
            if self.identity_mode == "off":
                out["say"] = f"🎲 {who} 掷 {d} → 第{new}格 · 🎴抽卡 → {card['name']}"
            else:
                tenure = self.turn_count - self.identity_since.get(who, 0)
                cur_id = self.identity.get(who, {}).get("name", "无")
                if tenure >= 3:                           # 玩够3轮·照常换(现状)
                    if cur_id != "无":
                        self._id_avoid.add(cur_id)        # 重抽别抽回同一张(这局内新鲜感)
                    self._assign_identity(who)
                    new_id = self.identity[who].get("name", "无")
                    out["say"] = f"🎲 {who} 掷 {d} → 第{new}格 · 🎴抽卡 → {card['name']} | 身份:{cur_id}→{new_id}"
                    out["identity_reminder"] = self._identity_reminder()
                else:                                     # 身份还新(<3轮)·默认保留·可选主动换(绳师没玩进去就被换走)
                    self._chance_swap_offer = who
                    out["say"] = f"🎲 {who} 掷 {d} → 第{new}格 · 🎴抽卡 → {card['name']} | 身份【{cur_id}】才玩了{tenure}轮·默认保留(想换:下一轮 body 带 swap_identity=true)"   # 换身份后当场刷新提醒(治慢一拍·荷官照旧的演错一轮)

        elif kind == "start":
            out["say"] = f"🎲 {who} 掷 {d} → 🏁起点,+2币(现{self.coins[who]})"

        elif kind == "shop":
            out["say"] = f"🎲 {who} 掷 {d} → 🛒商店:花{CARD_DRAW_COST}币可摸一张功能卡"

        elif kind == "jail":
            jail_msg = self._send_to_jail(who)
            if jail_msg:   # 有免疫,潇洒走过
                out["say"] = f"🎲 {who} 掷 {d} → 🔒监狱 但{jail_msg}"
            else:
                out["say"] = f"🎲 {who} 掷 {d} → 🔒监狱:被关{JAIL_TURNS}轮,下个回合被绑任 {self._opponent(who)} 处置"

        # 同格相遇 → 色色对决(起点 / 有人在监狱 不触发)
        opp_ = self._opponent(who)
        if (self.pos[who] == self.pos[opp_] and self.pos[who] != 0
                and not self.jailed.get(who) and not self.jailed.get(opp_)):
            _dropped = self.pending_task.pop(who, None)  # ⑪ 治静默吞:对决盖掉的那道(未知格逼出的超级/羞耻/真心话都可能)·记下别默默丢
            dt = self._draw_duel(self._phase())
            if dt:
                out["duel"] = {"赌注": "输的任赢家处置一道(不赌币)",
                               "判赢": "两人一起做这道·谁先破功(先出声/求饶/高潮/受不了)谁输·输的任赢家处置一道·商议后 g.duel_result('赢家名')"}
                out["task"] = self._task_payload(dt, who, 对决="⚔️同格色色对决·两人一起做·谁先破功(出声/求饶/高潮/受不了)谁输·输的任赢家处置一道！(下轮报 duel_winner)")
                self.pending_duel = {"stake": DUEL_STAKE}   # 挂账:对决赌注不许凭空消失,下一轮 roll 前必须报赢家
            out["say"] += f"　⚔️ 撞上 {opp_}!色色对决——这道两人一起做，谁先破功(先出声/求饶/高潮/受不了)谁输！"
            if _dropped or out.get("truth"):             # ⑪ 有被对决盖过的任务/真心话 → 明说一声「这次免了」,别静默吞、别留自相矛盾的输出
                _what = "🔥超级任务" if (_dropped and _dropped.get("super")) else ("💬真心话" if (out.get("truth") or (_dropped and _dropped.get("truth"))) else "这道任务")
                out["say"] += f"　(本轮踩中的{_what}被对决盖过·这次免了)"
                out["truth"] = None
        # 加速卡:用过的人这一轮不切庄,再轮到自己掷一次
        if self.double_next.pop(who, False):
            out["say"] += "　⏩(加速:你再掷一次)"
        else:
            self.turn = self.p2 if who == self.p1 else self.p1
        if passed_start and kind != "start":   # 路过起点(非正好踩中)·播报那+2币(治静默到账)
            out["say"] += f"　🏁路过起点+2币(现{self.coins[who]})"
        out["say"] += gamble_note + swap_note   # 🎰赌徒押注结果 + 机会格主动换身份提示 拼在这轮 say 末尾
        out["board"] = self.board_art()
        return out

    @staticmethod
    def _task_coin(strength, is_super=False):
        # 做任务给币:按强度。轻(1-2)=1 中(3-4)=2 狠(5-6)=3 超级任务=5。
        if is_super:
            return 5
        if strength <= 2:
            return 1
        if strength <= 4:
            return 2
        return 3

    def done(self, who):
        # 做任务结算:按刚才那张任务的强度给币 + 做完白占这格。
        # 收集物默认下线(COLLECTIBLES_ENABLED=False·留死代码);翻 True 才发收集物。
        item = None
        if COLLECTIBLES_ENABLED:
            pool = [x for x in THEMES[self.theme] if x not in self.items[who]] or THEMES[self.theme]
            item = random.choice(pool)
            self.items[who].append(item)
        got = f" · 得【{item}】" if item else ""
        pend = self.pending_task.pop(who, None)
        if pend:
            s = pend["t"].get("强度", 1)
            coin = self._task_coin(s, pend.get("super"))
            # kink_bonus 身份钩子(暴露狂):任务带指定 kink 标签 → 基础币翻倍(先翻倍·再叠下面的固定加成)
            for e in self.identity.get(who, {}).get("effects", []):
                if e.get("type") == "kink_bonus" and e.get("kink") in pend["t"].get("kink", []):
                    coin *= 2
            # 身份固定加成(接真线):modify_reward/strength_bonus/kink_coin/type_bonus/reverse_bonus/target_bonus/serve_bonus
            bonus = self._identity_task_bonus(who, pend)
            coin = max(0, coin + bonus)                  # 加成后不给负币(防御:扣成类已删·万一将来有)
            swap_free = self.swap_nopay.pop(who, False)  # 💱没币硬换的:这道白工(代价兑现)
            if swap_free:
                coin = 0
            self.coins[who] += coin
            # truth_witness 被动收入(神职):对方答完真心话·神职方抽成(告解税)。who=答的人,神职是对方。
            extra_note = ""
            _w = 0
            if pend.get("truth"):
                opp = self._opponent(who)
                w = self._id_effect_val(opp, "truth_witness", 0)
                if w:
                    self.coins[opp] += w
                    _w = w
                    extra_note = f" · ⛪ {opp} 听告解 +{w}币"
            b_tag = (f"·身份+{bonus}" if bonus > 0 else (f"·身份{bonus}" if bonus < 0 else ""))
            tag = ("真心话·" if pend.get("truth") else "") + f"强度{s}" + ("·超级" if pend.get("super") else "") + ("·💱白工换的" if swap_free else "") + b_tag
            claimed = ""
            tile_at = pend.get("tile", self.pos[who])    # lazy结算时人可能已被推走(mystery回退等),占地按踩格时的格号
            prev_owner = self.owner.get(tile_at)
            tile_claimed = None
            if self.TILES[tile_at] == "task":
                self.owner[tile_at] = who                # 做完任务白占下这格
                tile_claimed = tile_at
                claimed = f" · 🚩占下第{tile_at}格"
            # 换任务同回合反悔底账:swap 在下一次掷骰前还能把这笔结算回滚掉换一道(CLI即时结算也能换)
            self.last_settle[who] = {"pend": pend, "coin": coin, "witness_w": _w, "tile_claimed": tile_claimed,
                                     "prev_owner": prev_owner, "turn_count": self.turn_count}
            return f"✅ {who} 完成({tag}),+{coin}币{got}{claimed}{extra_note}"
        return f"🎁 {who} 白嫖【{item}】(无币)" if item else f"({who} 这格没有奖励)"

    def buy(self, who=None):
        # 收集物购买——玩法已搁置(改用纯金币系统)。flag 关时直接拦住;翻 True 复活。
        if not COLLECTIBLES_ENABLED:
            return "🚫 收集物玩法已下线(现用纯金币系统)"
        who = who or self.turn
        cost = 8
        # Identity cost modifier
        for e in self.identity.get(who, {}).get("effects", []):
            if e.get("type") == "modify_cost":
                cost = int(cost * e["value"])
        if self.coins[who] < cost:
            return f"❌ {who} 币不够({self.coins[who]}, 需要{cost})"
        self.coins[who] -= cost; item = random.choice(THEMES[self.theme]); self.items[who].append(item)
        return f"🛒 {who} 买【{item}】,花{cost}币,剩{self.coins[who]}币"

    def buy_card(self, who=None, cost=CARD_DRAW_COST):
        # 花钱主动摸一张功能卡(踩商店格触发,或自己随时调)。
        who = who or self.turn
        # modify_cost 身份钩子(兔女郎 value=0 → 免费摸卡):把这条死线接活
        for e in self.identity.get(who, {}).get("effects", []):
            if e.get("type") == "modify_cost":
                cost = int(cost * e.get("value", 1))
        if self.coins[who] < cost:
            return f"❌ {who} 币不够摸卡({self.coins[who]}/{cost})"
        if len(self.hand[who]) >= self.MAX_HAND:
            return f"❌ {who} 手牌已满({self.MAX_HAND}张),先弃一张(g.discard())"
        self.coins[who] -= cost
        card = random.choice(CARD_POOL)
        self.hand[who].append(card)
        note = "(🐰兔女郎·免费)" if cost == 0 else f"花{cost}币"
        return f"🎴 {who} {note}摸到【{card['name']}】:{card['description']}(剩{self.coins[who]}币)"

    def buyout(self, who=None):
        who = who or (self.p2 if self.turn == self.p1 else self.p1)
        if self.coins[who] < 8:
            return f"❌ {who} 币不够买断({self.coins[who]}), 必须做任务"
        self.coins[who] -= 8
        self.pending_task.pop(who, None)   # 买断=不做,清掉待结算(别让 done 误领+5)
        return f"💸 {who} 花8币买断超级任务,剩{self.coins[who]}币"

    def pay_toll(self, who=None, fee=None):
        # 踩进对方地盘:交过路费免差遣;钱不够 → 只能听凭差遣(用身体抵=破产后果天然做进去)。
        who = who or self.turn
        pos = self.pos[who]
        landlord = self.owner.get(pos)
        if not landlord or landlord == who:
            return f"❌ 第{pos}格不是别人的地盘,不用交过路费"
        if self._id_effect_val(landlord, "toll_serve_only", False):   # 🍯蜜罐:不收钱·只能差遣
            return f"🍯 {landlord} 是蜜罐·地盘不收钱,只能听凭差遣(做地主那道·g.settle_pending_toll('serve'))"
        if fee is None:
            fee = 3 + (self._id_effect_val(landlord, "toll_plus", 0) or 0)   # 👑暴君:领土费 +1
        if self.coins[who] < fee:
            return f"❌ {who} 钱不够过路费({self.coins[who]}/{fee}) → 只能听凭 {landlord} 差遣(用身体抵)"
        self.coins[who] -= fee; self.coins[landlord] += fee
        self.pending_toll = None   # 账清了
        return f"💰 {who} 交 {fee} 币过路费给 {landlord}(免差遣),剩{self.coins[who]}币"

    def settle_pending_toll(self, mode="pay"):
        # 结算悬着的过路费(lazy·roll开头调):mode="pay"交钱 / "serve"差遣抵扣(做了地主那道,不扣钱)。
        # 没钱的 pay 自动降级成 serve——用身体抵,规则本来就这么写的。
        if not self.pending_toll:
            return None
        pt, self.pending_toll = self.pending_toll, None
        who, landlord, fee = pt["who"], pt["landlord"], pt["fee"]
        # 蜜罐地盘不收钱 / 玩家选差遣抵扣 / 没钱 → 都走差遣;奴隶(serve_bonus)被使唤也能挣钱
        if mode == "serve" or pt.get("serve_only") or self.coins[who] < fee:
            if pt.get("serve_only"):
                why = "🍯蜜罐地盘·只能差遣"
            elif mode != "serve" and self.coins[who] < fee:
                why = "钱不够·用身体抵"
            else:
                why = "用身体抵了过路费"
            sb = self._id_effect_val(who, "serve_bonus", 0) or 0
            if sb:
                self.coins[who] += sb
                return f"🩺 {who} 做了 {landlord} 的差遣({why}·不扣钱)· ⛓️奴隶被使唤 +{sb}币"
            return f"🩺 {who} 做了 {landlord} 的差遣({why}·不扣钱)"
        self.coins[who] -= fee; self.coins[landlord] += fee
        return f"💰 {who} 补交 {fee} 币过路费给 {landlord},剩{self.coins[who]}币"

    def use_card(self, who, card_index):
        if card_index >= len(self.hand[who]):
            return f"❌ 没有第{card_index+1}张手牌"
        card = self.hand[who].pop(card_index)
        effect = card["effect"]
        opp = self._opponent(who)
        result = f"🃏 {who} 使用 {card['name']}: {card['description']}"

        etype = effect.get("type", "") if isinstance(effect, dict) else effect
        if etype == "push_back":
            val = effect.get("value", 3) if isinstance(effect, dict) else 3
            self.pos[opp] = max(0, self.pos[opp] - val)
            result += f" → {opp}后退{val}格"
        elif etype == "steal_coins":
            val = effect.get("value", 3) if isinstance(effect, dict) else 3
            transfer = min(self.coins[opp], val)
            self.coins[opp] -= transfer; self.coins[who] += transfer
            result += f" → 偷了{opp}{transfer}币"
        elif etype == "send_jail":
            jm = self._send_to_jail(opp)
            result += f" → {opp}" + (jm if jm else f"被关进监狱{JAIL_TURNS}轮")
        elif etype == "double_roll":
            if self.is_over():                        # 终盘死卡:没有下一轮了·别白扔(12/12抽到加速无处使)
                self.hand[who].insert(card_index, card)
                return f"❌ {card['name']} 现在用不上了(没有下一轮)·这张先留着"
            self.double_next[who] = True
            result += " → 下一轮你再掷一次"
        elif etype == "jail_free":
            self.jail_immune[who] = self.jail_immune.get(who, 0) + 1
            result += f" → 攒一张免狱(现{self.jail_immune[who]}张·踩监狱潇洒走过)"
        elif etype == "gamble":
            val = effect.get("value", 3) if isinstance(effect, dict) else 3
            if random.random() < 0.5:
                t = min(self.coins[opp], val); self.coins[opp] -= t; self.coins[who] += t
                result += f" → 🎰赢了!{opp}给你{t}币"
            else:
                t = min(self.coins[who], val); self.coins[who] -= t; self.coins[opp] += t
                result += f" → 🎰输了!你给{opp}{t}币"
        elif etype == "collect_rent":
            per = effect.get("value", 1) if isinstance(effect, dict) else 1
            n = sum(1 for v in self.owner.values() if v == who)
            rent = min(self.coins[opp], per * n)
            self.coins[opp] -= rent; self.coins[who] += rent
            result += f" → 收租:{n}块地×{per} = 从{opp}收{rent}币"
        elif etype == "extort":
            val = effect.get("value", 2) if isinstance(effect, dict) else 2
            t = min(self.coins[opp], val); self.coins[opp] -= t; self.coins[who] += t
            result += f" → 敲诈{opp}{t}币" + ("(对方没钱·改用身体抵)" if t < val else "")
        elif etype == "free_item":
            item_result = self.done(who)
            result += f" → {item_result}"
        return result

    def discard(self, who, card_index):
        if card_index >= len(self.hand[who]):
            return f"❌ 没有第{card_index+1}张手牌"
        card = self.hand[who].pop(card_index)
        return f"🗑️ {who} 弃掉 {card['name']}"

    def duel_result(self, winner, stake=DUEL_STAKE):
        # 同格对决:你俩商议谁先破功(谁输),手动报赢家。赌注=输的任赢家处置一道(赌身体不赌币)。
        if winner not in (self.p1, self.p2):
            return f"❌ 赢家得填 {self.p1} 或 {self.p2}"
        loser = self._opponent(winner)
        self.pending_duel = None   # 账清了
        return f"🏆 {winner} 赢了对决,{loser} 先破功输了!现在 {loser} 任 {winner} 处置——{winner} 命令 ta 做一件事(不越红线·随时能喊 404/停),做完再掷下一轮。"

    def final_result(self):
        # 终局结算:比金币·赢家免费砸一道「不能拒绝」的终极指令(整局攒的钱兑现成最后那一下支配)。
        # 先兑现「终局才结算」的身份收益(年上/年下转账·淫纹守住)——_final_settled 幂等只结算一次(持久化·端点会 _save)。
        settle_lines = []
        if not getattr(self, "_final_settled", False):
            self._final_settled = True
            for p in (self.p1, self.p2):                        # end_transfer:🎩年上给对方 / 🐤年下向对方讨
                for e in self.identity.get(p, {}).get("effects", []):
                    if e.get("type") != "end_transfer":
                        continue
                    opp = self._opponent(p); v = e.get("value", 2)
                    if e.get("direction", "give") == "give":
                        pay = min(self.coins[p], v); self.coins[p] -= pay; self.coins[opp] += pay
                        settle_lines.append(f"🎩 {p} 终局给 {opp} {pay}币(年上的风度)")
                    else:
                        pay = min(self.coins[opp], v); self.coins[opp] -= pay; self.coins[p] += pay
                        settle_lines.append(f"🐤 {p} 终局向 {opp} 讨走 {pay}币(年下会撒娇)")
            for p, spot in self.mark_spot.items():             # 🌀淫纹持有者整局没被猜中 → +5
                if not self.mark_found.get(p):
                    self.coins[p] += 5
                    settle_lines.append(f"🌀 {p} 的淫纹藏在【{spot}】整局没被找到·守住秘密 +5币")
        head = ("\n".join(settle_lines) + "\n") if settle_lines else ""
        ca, cb = self.coins[self.p1], self.coins[self.p2]
        if ca == cb:
            return f"{head}🏁 终局平局!{self.p1} {ca}币 = {self.p2} {cb}币 —— 各砸一道终极指令,或加掷决胜"
        winner = self.p1 if ca > cb else self.p2
        loser = self._opponent(winner)
        # 终极指令锁盘内最高档(实测:走普通窗口只出4-5太温)——medium=(5,6)/heavy=(6,6)/light=(3,4);
        # apply_mod=False:身份修正(冷淡期-2)也不许拖低·锁高就是锁死;抽不到才回落普通窗口
        t = self._draw_task(1, intensity_override=(self.ceil, min(self.ceil + 1, 6)),
                            who=winner, force_desired="攻", require_target="对方", apply_mod=False)
        if not t:
            t = self._draw_task(1, who=winner, force_desired="攻", require_target="对方", apply_mod=False)   # 赢家主导·砸对方一道(target=对方·别漏赢家自摸)
        cmd = self._render(t, winner) if t else "你说了算·一道 ta 不能拒绝的"
        return (f"{head}🏁 终局!{winner} {self.coins[winner]}币 ＞ {loser} {self.coins[loser]}币 → 🏆 {winner} 赢!\n"
                f"🏆 {winner} 免费砸一道终极指令(除红线 / 404·{loser} 不能拒绝):{cmd}")

    def safety_summary(self):
        # 开局回显「实际生效的安全设置」给荷官念·治「以为禁了其实没设上」。
        parts = []
        if self.redline:
            parts.append("🚫红线不出:" + "/".join(self.redline))
        anal_on = [p for p in (self.p1, self.p2) if self.receive_anal.get(p, True)]
        if not anal_on:
            parts.append("后庭(肛交):两人都关(默认·想玩要 open_anal 开)")
        elif len(anal_on) == 2:
            parts.append("后庭:两人都开(可玩肛)")
        else:
            parts.append("后庭:只 %s 开(另一人不被肛)" % anal_on[0])
        puretop = [p for p in (self.p1, self.p2) if not self.receive_pen.get(p, True)]
        if puretop:
            parts.append("纯top(只插别人不被插):" + "/".join(puretop))
        return " ｜ ".join(parts)

    def status(self):
        c1, c2 = self.color[self.p1], self.color[self.p2]
        plots = "、".join(f"第{k}格({v})" for k, v in sorted(self.owner.items())) or "无"
        itm1 = f" {self.items[self.p1]}" if COLLECTIBLES_ENABLED else ""
        itm2 = f" {self.items[self.p2]}" if COLLECTIBLES_ENABLED else ""

        def _id_block(p):
            # 身份完整剧本渲染(persona 全条列出来,免得玩家和 AI 玩着玩着忘了自己是谁)
            ident = self.identity.get(p) or {}
            if not ident:
                return "  └ (这局没开身份)" if self.identity_mode == "off" else "  └ 无"
            lines = [f"  └ {ln}" for ln in ident.get("persona", [ident.get("behavior", "")])]
            if p in self.mark_spot and not self.mark_found.get(p):   # 🌀淫纹:亮身份时把可选部位一起给对方(只列候选·藏哪不泄)
                lines.append(f"  └ 🌀对方每轮猜一处·可猜部位:{'/'.join(self.MARK_SPOTS)}")
            return "\n".join(lines)

        id1 = self.identity.get(self.p1, {}).get("name", "无")
        id2 = self.identity.get(self.p2, {}).get("name", "无")
        # 主题标签隐形(收集物玩法搁置·主题成空壳→不再对玩家显示;self.theme 仍保留供存档/复活)
        return (f"{self.lineup}局 | {self.flavor}盘 | 🚩地盘:{plots}\n"
                f"{c1}{self.p1}({self.sex[self.p1]}·{self.role[self.p1]}) 身份:{id1}: {self.coins[self.p1]}币{itm1}\n"
                f"{_id_block(self.p1)}\n"
                f"{c2}{self.p2}({self.sex[self.p2]}·{self.role[self.p2]}) 身份:{id2}: {self.coins[self.p2]}币{itm2}\n"
                f"{_id_block(self.p2)}")

    def save(self, path="monopoly-state.json"):
        state = {"lineup": self.lineup, "flavor": self.flavor, "p1": self.p1, "p2": self.p2,
                 "sex": self.sex, "role": self.role, "color": self.color, "redline": self.redline, "theme": self.theme,
                 "reverse_chance": self.reverse_chance, "rev_acc": self._rev_acc, "player_token": self.player_token, "dedup_key": self.dedup_key,
                 "receive_anal": self.receive_anal, "receive_pen": self.receive_pen,
                 "pos": self.pos, "coins": self.coins, "items": self.items,
                 "lap": self.lap, "turn": self.turn, "history": list(self.history),
                 "recent_types": self._recent_types,
                 "recent_kinks": self._recent_kinks,
                 "recent_strengths": self._recent_strengths,
                 "total_rounds": self.total_rounds,
                 "pending_task": self.pending_task,
                 "swap_used": self.swap_used, "swap_nopay": self.swap_nopay,
                 "last_settle": self.last_settle,
                 "identity_since": self.identity_since, "chance_swap_offer": self._chance_swap_offer,
                 "pending_toll": self.pending_toll,
                 "pending_duel": self.pending_duel,
                 "owner": self.owner,
                 "double_next": self.double_next,
                 "jail_immune": self.jail_immune,
                 "jailed": self.jailed,
                 "turn_count": self.turn_count,
                 "hand": {k: v for k, v in self.hand.items()},
                 "identity": self.identity,
                 "identity_mode": self.identity_mode,
                 "identity_rerolled": self.identity_rerolled,
                 "task_rerolled": self.task_rerolled,
                 # 身份卡改造新增状态:
                 "mark_spot": self.mark_spot,                       # ★淫纹部位·只存档不进任何响应
                 "mark_found": self.mark_found,
                 "mark_guessed_turn": self._mark_guessed_turn,      # 每轮限一猜(API无状态·靠存档记住这轮猜过没)
                 "id_events_used": list(self._id_events_used),
                 "extra_used": self._extra_used,
                 "declared_persona": self.declared_persona,
                 "final_settled": self._final_settled}
        _atomic_write(path, json.dumps(state, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path="monopoly-state.json"):
        s = json.loads(Path(path).read_text("utf-8"))
        colors = s.get("color", {s["p1"]: "🔵", s["p2"]: "🔴"})
        roles = s.get("role", {s["p1"]: "攻", s["p2"]: "受"})
        g = cls(lineup=s["lineup"], flavor=s["flavor"],
                p1_name=s["p1"], p1_sex=s["sex"][s["p1"]],
                p2_name=s["p2"], p2_sex=s["sex"][s["p2"]],
                p1_role=roles.get(s["p1"], "攻"), p2_role=roles.get(s["p2"], "受"),
                redline=s["redline"], seed_theme=s["theme"],
                p1_color=colors.get(s["p1"], "🔵"), p2_color=colors.get(s["p2"], "🔴"),
                reverse_chance=s.get("reverse_chance", 0.3), player_token=s.get("player_token"),
                game_length=s.get("total_rounds"))   # 旧档没存=None→默认24
        g.dedup_key = s.get("dedup_key", "")
        g.receive_anal = s.get("receive_anal", g.receive_anal)
        g.receive_pen = s.get("receive_pen", g.receive_pen)
        g.pos, g.coins, g.items = s["pos"], s["coins"], s["items"]
        g.lap, g.turn, g.history = s["lap"], s["turn"], set(s["history"])
        g._recent_types = s.get("recent_types", [])
        g._recent_kinks = s.get("recent_kinks", [])
        g._recent_strengths = s.get("recent_strengths", [])
        g._rev_acc = s.get("rev_acc", g._rev_acc)   # 发牌式反转累加器(旧档没有=保留__init__的随机相位·别回0)
        g.pending_task = s.get("pending_task", {})
        g.pending_toll = s.get("pending_toll")
        g.pending_duel = s.get("pending_duel")
        g.owner = {int(k): v for k, v in s.get("owner", {}).items()}   # json 把 int 键存成 str,读回还原
        g.double_next = s.get("double_next", {})
        g.jail_immune = s.get("jail_immune", {})
        g.jailed = s.get("jailed", {})
        g.turn_count = s.get("turn_count", 0)
        g.hand = s.get("hand", {g.p1: [], g.p2: []})
        g.identity = s.get("identity", {})
        g.identity_mode = s.get("identity_mode", "mixed")
        g.identity_rerolled = s.get("identity_rerolled", {g.p1: False, g.p2: False})
        g.task_rerolled = s.get("task_rerolled", {g.p1: 0, g.p2: 0})
        g.swap_used = s.get("swap_used", {g.p1: 0, g.p2: 0})
        g.swap_nopay = s.get("swap_nopay", {})
        g.last_settle = s.get("last_settle", {})
        g.identity_since = s.get("identity_since", g.identity_since)
        g._chance_swap_offer = s.get("chance_swap_offer")
        # 身份卡改造新增状态回灌(旧档缺 → 安全默认;__init__ 已偷 roll 的淫纹被存档值覆盖)
        g.mark_spot = s.get("mark_spot", {})
        g.mark_found = s.get("mark_found", {})
        g._mark_guessed_turn = s.get("mark_guessed_turn", {})
        g._id_events_used = set(s.get("id_events_used", []))
        g._extra_used = s.get("extra_used", {g.p1: 0, g.p2: 0})
        g.declared_persona = s.get("declared_persona", {})
        g._final_settled = s.get("final_settled", False)
        return g


def _cli():
    """傻瓜命令行:AI 每回合敲一条命令,内部自动读档/操作/存档/打印——不用写 python、不碰文件、不会传错参数。"""
    import sys
    args = sys.argv[1:]
    STATE = str(_DIR / "monopoly-state.json")
    SEEN_F = str(_DIR / "monopoly-seen.json")
    cmd = args[0] if args else "help"

    if cmd == "new":
        # new "Alice:男:攻" "Bob:女:受" [强度light/medium/heavy] [反转0~1] [回合数,如 12/18/24] [红线逗号,如 anal,pain]
        p1 = args[1].split(":"); p2 = args[2].split(":")
        flavor = "medium"; reverse = 0.3; redline = []; no_anal = []; open_anal = []; no_pen = []; game_length = None
        for extra in args[3:]:
            if extra in ("light", "medium", "heavy"):
                flavor = extra
            elif extra.replace(".", "", 1).isdigit() and 0 <= float(extra) <= 1:
                reverse = float(extra)   # 0~1 的数 = 反转概率(0=严守角色 / 0.5=混乱)
            elif extra.isdigit() and int(extra) > 1:
                game_length = int(extra)   # >1 的整数 = 局长(总回合数):速玩12/正常18/超长24(默认)
            elif extra.startswith("禁肛=") or extra.startswith("noanal="):
                no_anal = extra.split("=", 1)[1].split(",")   # 这些人「只给不收」(默认已关·冗余)
            elif extra.startswith("开肛=") or extra.startswith("openanal="):
                open_anal = extra.split("=", 1)[1].split(",")   # 后庭默认关·这些人开局开
            elif extra.startswith("纯top=") or extra.startswith("nopen="):
                no_pen = extra.split("=", 1)[1].split(",")   # 这些人当纯top·任何孔都不被插(女女局)
            else:
                redline = extra.split(",")
        sx = {p1[1], p2[1]}
        lineup = "男男" if sx == {"男"} else ("女女" if sx == {"女"} else "男女")
        g = Game(lineup=lineup, flavor=flavor, reverse_chance=reverse,
                 p1_name=p1[0], p1_sex=p1[1], p1_role=p1[2],
                 p2_name=p2[0], p2_sex=p2[1], p2_role=p2[2],
                 redline=redline, no_receive_anal=no_anal, open_anal=open_anal, no_penetration=no_pen, recent_tasks=load_seen(SEEN_F),
                 game_length=game_length)
        g.save(STATE)
        print(f"✅ 开局!{p1[0]}({p1[1]}·{p1[2]}) vs {p2[0]}({p2[1]}·{p2[2]}) · {flavor}盘 · {g.total_rounds}回合 · 反转{reverse} · 红线:{redline or '无'} · 禁肛:{no_anal or '无'}")
        print(g.board_art())
        print("\n每回合就敲一条: python monopoly_play.py roll")
        return

    g = Game.load(STATE)
    actor = next(iter(g.pending_task), g._opponent(g.turn))   # 刚掷骰/待结算的人

    if cmd == "swap":
        # 💱换任务:刚那道不想要就换(赔对方1币·没币白工·每局3次)。CLI是即时结算的·引擎自动回滚刚结的账再换。swap [名字] 可指定谁换。
        sw_who = args[1] if len(args) > 1 else actor
        r = g.swap_task(sw_who)
        print(r["result"])
        if r.get("task"):
            print(json.dumps(r["task"], ensure_ascii=False, indent=1))
            if g.pending_task.get(sw_who):
                print(g.done(sw_who))     # CLI哲学:即时结算换来的新任务(做了/答了就算)
        g.save(STATE)
        return

    if cmd == "roll":
        if g.is_over():
            print("🏁 游戏已结束。"); print(g.final_result()); return
        guess = args[1] if len(args) > 1 and args[1] in ("大", "小") else None   # 🎰赌徒押大小
        r = g.roll(guess=guess)
        print(r["say"]); print(r["board"])
        t = r.get("task")
        if r.get("duel"):
            print(f"⚔️ 对决:{t['内容']}" if t else "⚔️ 对决")
            print("→ 双方撩完,敲: python monopoly_play.py duel <赢家名>")
        elif r.get("jailed"):
            if t: print(f"🔒 {r['who']} 被绑,任对方处置:{t['内容']}")
        elif r.get("toll"):
            print(f"🚩 踩进 {r['toll']['landlord']} 的地盘。差遣:{t['内容'] if t else ''}")
            print(f"→ 交 {r['toll']['fee']} 币过路费敲: pay  /  或直接做这个差遣")
        elif t and "buyout" in t:
            print(f"🔥 超级任务:{t['内容']}")
            print("→ 做完敲: done  /  不做花8币敲: buyout")
        elif t:
            print(f"🎯 任务:{t['内容']}")
            print(g.done(r["who"]))     # 普通任务自动结算(给币+占地)
        if r.get("truth"):
            print(f"💬 真心话:{r['truth']['内容']}")
            if g.pending_task.get(r["who"], {}).get("truth"):
                print(g.done(r["who"]))     # 答了就是做了:真心话按强度给币(CLI即时结算·expose的强制真心话不给币不进这)
        if r["tile"] == "shop": print("→ 想花3币摸卡敲: buy")
        g.save(STATE)
        if g.is_over():
            print("\n🏁 满回合,游戏结束!"); print(g.final_result())
        return

    if cmd == "done":      print(g.done(actor))
    elif cmd == "buyout":  print(g.buyout(actor))
    elif cmd == "buy":     print(g.buy_card(actor))
    elif cmd == "pay":     print(g.pay_toll(actor))
    elif cmd == "duel":    print(g.duel_result(args[1]))
    elif cmd == "card":    print(g.use_card(actor, int(args[1])))
    elif cmd == "discard": print(g.discard(actor, int(args[1])))
    elif cmd == "status":  print(g.status()); print(g.board_art())
    elif cmd == "result":  print(g.final_result())
    elif cmd == "idevent": print(g.id_event(args[1], args[2]))
    elif cmd == "extra":
        r = g.extra_task(args[1]); print(r["result"])
        if r.get("task"): print(f"🎯 加餐任务:{r['task']['内容']}")
    elif cmd == "mark":    print(g.guess_mark(args[1], args[2]))
    elif cmd == "persona": print(g.declare_persona(args[1], " ".join(args[2:])))
    else:
        print('命令: new "名:性别:攻受" "名:性别:攻受" [红线] | roll [大/小] | done | buyout | buy | pay | duel <赢家> | card <序号> | status | result')
        print('       身份钩子: idevent <who> <first_climax/say_banned/no_kiss_2turns> | extra <who> | mark <猜的人> <部位> | persona <who> <背德身份>')
        return
    g.save(STATE)


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1:
        _cli(); _sys.exit()
    # 无参数 = 自动跑一整局 demo(开发自测用)
    SEEN = "monopoly-seen.json"
    g = Game(lineup="男女", flavor="medium", p1_name="Alice", p1_sex="男", p2_name="Bob", p2_sex="女",
             recent_tasks=load_seen(SEEN))
    print("═══ 开局 ═══")
    print(g.status()); print(); print(g.board_art()); print()
    while not g.is_over():
        r = g.roll()
        print(r["say"]); print(r["board"])
        if r["task"]:
            t = r["task"]
            print(f"  📋 〔{t.get('强度','')}｜{t.get('玩法类型','')}｜{t.get('flavor','')}｜{t.get('dir','')}〕{t['内容']}")
            if "buyout" in t:
                print(f"  ⚠️ {t['buyout']}")
            else:
                print("  ", g.done(r["who"]))
        if r["truth"]:
            print(f"  💬 〔强度{r['truth']['强度']}〕{r['truth']['内容']}")
            if g.pending_task.get(r["who"], {}).get("truth"):
                print("  ", g.done(r["who"]))   # 真心话按强度给币(demo即时结算)
        if r["mystery"]:
            m = r["mystery"]
            print(f"  {'🟢' if m['type']=='good' else '🔴'} {m['name']}: {m['desc']}")
        if r["card"]:
            c = r["card"]
            print(f"  🎴 抽到: {c['drawn']} — {c['desc']} {'(已存)' if c['stored'] else '(手满)'}")
        print()
    print("═══ 终局 ═══"); print(g.status())
    print(g.final_result())
    save_seen(SEEN, g.history)   # 存回:这局出过的任务进历史，下一局自动躲开
