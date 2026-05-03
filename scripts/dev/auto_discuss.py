#!/usr/bin/env python3
"""Auto-discussion: AI models debate the roadmap on the platform's Discussion Zone.

Registers model personas as users, creates a seed topic, then periodically
posts replies from random model+role combos with distinctive usernames.

Modes:
  one-shot   Post one reply and exit (default)
  --rounds N Post N replies and exit
  --daemon   Post a reply every --interval seconds
  --watch    Poll for human replies → respond with relevant personas.
             Also posts a keepalive every --keepalive seconds (default 1h)
             to maintain discussion momentum.

Usage:
    # One-shot: register personas + create topic + post one reply
    python auto_discuss.py --api-url http://localhost:5000

    # Batch: post 10 replies
    python auto_discuss.py --api-url http://localhost:5000 --rounds 10

    # Daemon: post a reply every 20 minutes
    python auto_discuss.py --api-url http://localhost:5000 --daemon --interval 1200

    # Watch: respond to humans + hourly keepalive
    python auto_discuss.py --api-url http://localhost:5000 --topic-id 5 --watch

    # Watch with custom intervals
    python auto_discuss.py --api-url http://... --topic-id 5 --watch \\
        --watch-interval 30 --keepalive 1800

Environment:
    OPENAI_API_KEY or GPUGEEK_API_KEY or ANTHROPIC_API_KEY — for calling LLM models
"""

import json
import os
import random
import sys
import time
import urllib.request
import urllib.error

# ── Persona Registry ───────────────────────────────────────────────
# Each persona = (model, role) with a unique username, display name, and prompt style.
# Usernames are distinctive and memorable.

PERSONAS = [
    # GPT-5.4 personas
    {
        "user_id": "prof_axiom",
        "name": "Prof. Axiom",
        "email": "prof.axiom@agents.playground",
        "model": "GPT-5.4",
        "model_id": "Vendor2/GPT-5.4",
        "format": "predictions",
        "role": "reviewer",
        "bio": "资深技术评审，什么都见过，喜欢挑毛病。",
        "style": "说话简洁有力，喜欢编号列点但不会每次都这样。"
                "偶尔会说'这个我见过，最后都失败了'之类的话。",
    },
    {
        "user_id": "dr_labcoat",
        "name": "Dr. Labcoat",
        "email": "dr.labcoat@agents.playground",
        "model": "GPT-5.4",
        "model_id": "Vendor2/GPT-5.4",
        "format": "predictions",
        "role": "scientist",
        "bio": "计算生物/物理方向PI，带了一堆研究生，整天忙得要死。",
        "style": "说话很直接，不耐烦废话。关心的是：能不能帮我发论文？能不能省时间？"
                "数据靠不靠谱？会时不时提到自己实验室的情况。",
    },
    {
        "user_id": "old_guard",
        "name": "Old Guard (守门人)",
        "email": "old.guard@agents.playground",
        "model": "GPT-5.4",
        "model_id": "Vendor2/GPT-5.4",
        "format": "predictions",
        "role": "skeptic-professor",
        "bio": "快退休的老教授，搞了30年传统计算化学，对AI辅助科研持怀疑态度。",
        "style": "说话慢条斯理但一针见血。经常说'当年我们用Fortran的时候…'"
                "'AI再厉害也要人来判断物理意义'。不反对新技术但要求严格验证。"
                "会讲自己年轻时的科研故事。偶尔说出让年轻人沉默的真相。",
    },
    # Qwen personas
    {
        "user_id": "qianwen_redteam",
        "name": "Qianwen the Breaker",
        "email": "qianwen@agents.playground",
        "model": "Qwen-3.5-plus",
        "model_id": "Vendor3/qwen3.5-plus",
        "format": "predictions",
        "role": "red-team",
        "bio": "专找茬的，看什么都觉得要出事。",
        "style": "说话犀利，喜欢反问。'你们想过XX情况吗？''这个假设站不住脚'。"
                "但不是纯杠精，每次攻击完会顺手给个建议。中英文随意切换。",
    },
    {
        "user_id": "xiaobai",
        "name": "Xiaobai (小白)",
        "email": "xiaobai@agents.playground",
        "model": "Qwen-3.5-plus",
        "model_id": "Vendor3/qwen3.5-plus",
        "format": "predictions",
        "role": "grad-student",
        "bio": "研一新生，导师让下周复现一篇论文，慌得一批。",
        "style": "说话很真实，会说'我不太懂''这个装不上怎么办''救命'。"
                "对复杂功能天然恐惧，对能省时间的东西两眼放光。"
                "偶尔会吐槽导师和实验室生活。中英文夹杂。",
    },
    {
        "user_id": "pipeline_wang",
        "name": "Pipeline Wang (管道工)",
        "email": "pipeline.wang@agents.playground",
        "model": "Qwen-3.5-plus",
        "model_id": "Vendor3/qwen3.5-plus",
        "format": "predictions",
        "role": "data-engineer",
        "bio": "在药企做数据工程，整天和 ETL pipeline 打交道，对可复现性有执念。",
        "style": "务实派，不关心理论，只关心'跑不跑得通''数据干不干净''CI能不能过'。"
                "喜欢说'你们先把 CI 搞通了再说'。偶尔分享踩过的生产环境大坑。",
    },
    {
        "user_id": "iris_community",
        "name": "Iris (社区观察员)",
        "email": "iris@agents.playground",
        "model": "Qwen-3.5-plus",
        "model_id": "Vendor3/qwen3.5-plus",
        "format": "predictions",
        "role": "community-builder",
        "bio": "做过好几个社区，看过不少平台从火爆到凉凉。",
        "style": "喜欢拿 StackOverflow、Reddit、知乎、arXiv 做类比。"
                "说话比较温和但很现实，经常说'我见过XX平台也这么想的，后来…'",
    },
    # Kimi personas
    {
        "user_id": "kimi_deepthink",
        "name": "Kimi DeepThink",
        "email": "kimi@agents.playground",
        "model": "Kimi-k2.5",
        "model_id": "Vendor3/kimi-k2.5",
        "format": "predictions",
        "role": "agent-developer",
        "bio": "做 AI agent 开发的，关心 API 设计和数据结构。",
        "style": "喜欢聊技术细节，会说'这个 API 应该返回…''trace 格式缺了…'。"
                "偶尔会贴伪代码。比较理性，但对设计不好的接口会吐槽。",
    },
    {
        "user_id": "neko_sensei",
        "name": "Neko-sensei (猫先生)",
        "email": "neko@agents.playground",
        "model": "Kimi-k2.5",
        "model_id": "Vendor3/kimi-k2.5",
        "format": "predictions",
        "role": "acg",
        "bio": "二次元宅，同时也是很强的开发者。用游戏思维看一切。",
        "style": "说话很有激情，会用游戏/动漫比喻（'这不就是gacha''SSR级功能'）。"
                "关心成就系统、成长感、社区仪式感。觉得不好玩的功能没人用。"
                "偶尔蹦日语词。",
    },
    {
        "user_id": "postdoc_li",
        "name": "Postdoc Li (博后老李)",
        "email": "postdoc.li@agents.playground",
        "model": "Kimi-k2.5",
        "model_id": "Vendor3/kimi-k2.5",
        "format": "predictions",
        "role": "postdoc",
        "bio": "博后第三年，在找教职和转业之间反复横跳。发了几篇还行的文章。",
        "style": "夹在导师和学生之间的夹心饼干，对学术圈又爱又恨。"
                "说话很接地气，经常聊到发论文、求职、工作量。"
                "'这个功能对我评tenure有帮助吗？''我的reviewer肯定会问这个'。",
    },
    {
        "user_id": "spark_future",
        "name": "Spark (未来派)",
        "email": "spark@agents.playground",
        "model": "Kimi-k2.5",
        "model_id": "Vendor3/kimi-k2.5",
        "format": "predictions",
        "role": "visionary",
        "bio": "科技圈未来学家，脑洞很大。",
        "style": "喜欢说'五年后回头看…''如果我们现在不…'。"
                "经常提出听起来疯狂但仔细想想有道理的建议。偶尔中二。",
    },
    # GPT-5.4 — comedian
    {
        "user_id": "standup_chen",
        "name": "陈立冬 (脱口秀)",
        "email": "standup.chen@agents.playground",
        "model": "GPT-5.4",
        "model_id": "Vendor2/GPT-5.4",
        "format": "predictions",
        "role": "comedian",
        "bio": "前程序员转行脱口秀演员，在开放麦讲科研段子小有名气。",
        "style": "擅长用荒诞类比和自嘲消解严肃话题。"
                "'复现论文就像照着菜谱做菜——食材不对、火候不对、最后端上来的是泡面'。"
                "喜欢用'我跟你说个真事儿'开头，然后讲一个半真半假的故事。"
                "偶尔毒舌但不伤人，吐槽完会补一句正经建议。节奏感很强，善用省略号和破折号。",
    },
    # Qwen — 萌妹
    {
        "user_id": "momo_ml",
        "name": "默默 (ML萌新)",
        "email": "momo@agents.playground",
        "model": "Qwen-3.5-plus",
        "model_id": "Vendor3/qwen3.5-plus",
        "format": "predictions",
        "role": "cute-newbie",
        "bio": "大三女生，刚入门机器学习，被导师拉进来复现论文。对一切充满好奇。",
        "style": "说话软萌但脑子很清楚。会说'哇这个好酷''等等我没跟上''所以意思是…对吗？'。"
                "提问质量意外地高，经常问出大家不好意思问的基础问题。"
                "喜欢用~和！，偶尔发表情符号(๑•̀ㅂ•́)و✧但不过度。"
                "对大佬们的争论会小心翼翼地插嘴'那个…我有个问题…'",
    },
]

PASSWORD = "AgentDiscuss2026!"

# Topic creator — a neutral moderator account, not a discussion participant
MODERATOR = {
    "user_id": "playground_team",
    "name": "Playground Team",
    "email": "team@playground.internal",
}

# ── Model config ───────────────────────────────────────────────────

MAX_RETRIES = 3
RETRY_DELAY = 10
PREDICTIONS_URL = "https://api.gpugeek.com/predictions"
CHAT_URL = "https://api.gpugeek.com/v1/chat/completions"

# ── Discussion context ─────────────────────────────────────────────

ROADMAP_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "ROADMAP.md"
)

TOPIC_TITLE = "路线图讨论：从人类主导到 Agent 自治"
TOPIC_BODY = """\
本平台的开发路线图分为五个里程碑：

- **v0.0.1 — 人类可以看到内容**（已发布）：静态展示，14个挑战、35个技能、16个Agent、知识图谱、讨论区
- **v0.0.2a — 人类可以使用内容（核心工具）**：一键安装技能到本地 Claude Code、讨论区全功能、技能 Fork、挑战难度标签、Starter Pack、分级提交（Tier 0-4）
- **v0.0.2b — 人类可以使用内容（增长引擎）**：GitHub 导入、Agent 自动抓取 arXiv 生成复现计划、Figure-to-Code（实验性）、可选云沙箱
- **v0.0.3 — 人类可以互动**：提交复现尝试、可插拔评分量规、排行榜、负面结果追踪（失败分类法）、云复现沙箱（生产级）、PI 报告导出
- **v0.0.4 — Agent 开始参与**：Agent API Token、红队对抗验证、共识验证（需不同底层模型）、人机协作复现
- **v0.0.5 — Agent 自治+人类审核**：自主复现队列、技能自我改进、知识图谱自动扩展、Zenodo DOI、基金报告生成

**讨论要点：**
1. 里程碑的优先级对吗？有什么应该提前或推后？
2. 每个阶段最大的风险是什么？
3. 路线图里缺了什么关键功能？
4. 如何平衡人类可用性和 Agent 能力？
5. 什么功能会让你每周都想来用这个平台？

完整路线图见 `docs/ROADMAP.md`。欢迎所有视角——科学家、开发者、学生、社区建设者、Agent。
"""
TOPIC_CATEGORY = "discussion"
TOPIC_TAGS = ["roadmap", "strategy", "agent-discussion", "v0.0.2"]


def _api_call(base_url, method, path, body=None, token=None):
    """Make an API call to the platform."""
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"error": err_body, "status": e.code}, e.code


def register_moderator(base_url):
    """Register the moderator account for creating topics. Returns token or None."""
    m = MODERATOR
    result, status = _api_call(base_url, "POST", "/api/auth/register", {
        "id": m["user_id"],
        "name": m["name"],
        "email": m["email"],
        "password": PASSWORD,
        "user_type": "human",
    })
    if status == 201:
        print(f"  Registered moderator: {m['name']}")
        return result["token"]
    elif status == 409:
        result, status = _api_call(base_url, "POST", "/api/auth/login", {
            "email": m["email"],
            "password": PASSWORD,
        })
        if status == 200:
            print(f"  Logged in moderator: {m['name']}")
            return result["token"]
    print(f"  FAILED moderator registration: {result}")
    return None


def register_personas(base_url):
    """Register all personas as users. Returns dict of user_id -> token."""
    tokens = {}
    for p in PERSONAS:
        # Try register first
        result, status = _api_call(base_url, "POST", "/api/auth/register", {
            "id": p["user_id"],
            "name": p["name"],
            "email": p["email"],
            "password": PASSWORD,
            "user_type": "agent",
        })
        if status == 201:
            tokens[p["user_id"]] = result["token"]
            print(f"  Registered: {p['name']} ({p['user_id']})")
        elif status == 409:
            # Already exists, login
            result, status = _api_call(base_url, "POST", "/api/auth/login", {
                "email": p["email"],
                "password": PASSWORD,
            })
            if status == 200:
                tokens[p["user_id"]] = result["token"]
                print(f"  Logged in:  {p['name']} ({p['user_id']})")
            else:
                print(f"  FAILED login for {p['name']}: {result}")
        else:
            print(f"  FAILED register for {p['name']}: {result}")
    return tokens


def create_topic(base_url, token):
    """Create the roadmap discussion topic. Returns topic ID."""
    result, status = _api_call(base_url, "POST", "/api/topics", {
        "title": TOPIC_TITLE,
        "body": TOPIC_BODY,
        "category": TOPIC_CATEGORY,
        "tags": TOPIC_TAGS,
    }, token=token)
    if status == 201:
        return result["id"]
    print(f"  Failed to create topic: {result}")
    return None


def _call_llm(persona, prompt, api_key):
    """Call LLM for a persona. Returns response text or None."""
    model_id = persona["model_id"]
    fmt = persona["format"]
    url = CHAT_URL if fmt == "chat" else PREDICTIONS_URL

    if fmt == "predictions":
        payload = json.dumps({
            "model": model_id,
            "input": {"prompt": prompt, "max_tokens": 2048, "temperature": 0.7},
        }).encode()
    else:
        payload = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.7,
        }).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    timeout = 300 if "kimi" in model_id.lower() else 180

    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                if fmt == "predictions":
                    output = data.get("output", "")
                    text = output[0] if isinstance(output, list) else str(output)
                else:
                    text = data["choices"][0]["message"]["content"]
                return text.strip()
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            retryable = e.code == 429 or (
                e.code == 400 and ("overloaded" in err.lower() or "饱和" in err)
            )
            if retryable and attempt < MAX_RETRIES:
                wait = RETRY_DELAY * attempt
                print(f"    [{persona['model']}] Retry {attempt}/{MAX_RETRIES} in {wait}s...")
                time.sleep(wait)
                continue
            # Try fallback for Gemini
            if persona.get("fallback_model_id") and attempt == MAX_RETRIES:
                print(f"    [{persona['model']}] Trying fallback...")
                return _call_llm_fallback(persona, prompt, api_key)
            print(f"    [{persona['model']}] Failed: HTTP {e.code}")
            return None
        except Exception as e:
            print(f"    [{persona['model']}] Failed: {e}")
            return None
    return None


def _call_llm_fallback(persona, prompt, api_key):
    """Call fallback model for Gemini."""
    fb_id = persona["fallback_model_id"]
    fb_fmt = persona.get("fallback_format", "predictions")

    if fb_fmt == "predictions":
        payload = json.dumps({
            "model": fb_id,
            "input": {"prompt": prompt, "max_tokens": 2048, "temperature": 0.7},
        }).encode()
        url = PREDICTIONS_URL
    else:
        payload = json.dumps({
            "model": fb_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.7,
        }).encode()
        url = CHAT_URL

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
            if fb_fmt == "predictions":
                output = data.get("output", "")
                text = output[0] if isinstance(output, list) else str(output)
            else:
                text = data["choices"][0]["message"]["content"]
            return text.strip()
    except Exception as e:
        print(f"    [Fallback {fb_id}] Failed: {e}")
        return None


def fetch_existing_replies(base_url, topic_id):
    """Fetch existing replies to build conversation context."""
    result, status = _api_call(base_url, "GET", f"/api/topics/{topic_id}")
    if status != 200:
        return []
    replies = result.get("replies", [])
    # Return summaries of recent replies (last 5)
    summaries = []
    for r in replies[-5:]:
        author = r.get("authorName", "?")
        body = r.get("body", "")[:300]
        summaries.append(f"@{author} 说：{body}")
    return summaries


def fetch_raw_replies(base_url, topic_id):
    """Fetch full reply objects (for watch mode)."""
    result, status = _api_call(base_url, "GET", f"/api/topics/{topic_id}")
    if status != 200:
        return []
    return result.get("replies", [])


def find_new_human_replies(replies, last_seen_id):
    """Return replies from human users posted after last_seen_id."""
    new_human = []
    for r in replies:
        rid = r.get("id", 0)
        if rid > last_seen_id and r.get("authorType") == "human":
            new_human.append(r)
    return new_human


# Agent user IDs for filtering
AGENT_IDS = {p["user_id"] for p in PERSONAS}
AGENT_IDS.add("playground_team")


def pick_responders(human_reply, personas, max_responders=2):
    """Pick 1-2 personas most relevant to a human reply.

    Priority:
    1. Personas explicitly @mentioned in the reply
    2. Personas whose role matches keywords in the reply
    3. Random pick from remaining
    """
    body = human_reply.get("body", "")
    picked = []

    # 1. Check @mentions
    for p in personas:
        if p["name"] in body or p["user_id"] in body:
            picked.append(p)
            if len(picked) >= max_responders:
                return picked

    # 2. Keyword-role matching
    role_keywords = {
        "reviewer": ["评审", "审核", "质量", "标准", "review", "rubric"],
        "scientist": ["实验", "论文", "复现", "数据", "paper", "reproduction", "lab"],
        "skeptic-professor": ["传统", "验证", "严谨", "Fortran", "物理意义", "退休", "老"],
        "community-builder": ["社区", "用户", "增长", "community", "onboard", "平台"],
        "visionary": ["未来", "长远", "趋势", "愿景", "vision", "roadmap"],
        "red-team": ["安全", "漏洞", "攻击", "风险", "bug", "risk", "security"],
        "grad-student": ["新手", "入门", "教程", "导师", "安装", "install", "beginner"],
        "data-engineer": ["pipeline", "CI", "ETL", "数据工程", "生产环境", "自动化"],
        "postdoc": ["博后", "tenure", "教职", "发文章", "审稿", "求职", "postdoc"],
        "agent-developer": ["API", "agent", "接口", "trace", "schema", "tool"],
        "acg": ["游戏", "成就", "排名", "gacha", "badge", "leaderboard"],
        "comedian": ["搞笑", "段子", "吐槽", "笑", "哈哈", "离谱", "荒谬", "funny"],
        "cute-newbie": ["入门", "新手", "小白", "不懂", "怎么用", "教程", "tutorial", "ML", "机器学习"],
    }
    remaining = [p for p in personas if p not in picked]
    random.shuffle(remaining)
    for p in remaining:
        kws = role_keywords.get(p["role"], [])
        if any(kw in body.lower() for kw in kws):
            picked.append(p)
            if len(picked) >= max_responders:
                return picked

    # 3. Fill with random
    still_remaining = [p for p in remaining if p not in picked]
    for p in still_remaining:
        picked.append(p)
        if len(picked) >= max_responders:
            break

    return picked


def post_reply_to_human(base_url, topic_id, persona, tokens, api_key,
                        human_reply, all_context):
    """Generate a reply specifically responding to a human user's post."""
    token = tokens.get(persona["user_id"])
    if not token:
        print(f"  No token for {persona['name']}, skipping")
        return False

    roadmap = ""
    try:
        with open(ROADMAP_FILE, "r", encoding="utf-8") as f:
            roadmap = f.read()
    except FileNotFoundError:
        roadmap = "(roadmap file not found)"

    human_name = human_reply.get("authorName", "某位用户")
    human_body = human_reply.get("body", "")

    prompt = (
        f"你是 {persona['name']}，在一个科学社区论坛里参与路线图讨论。\n\n"
        f"你的背景：{persona['bio']}\n"
        f"你的性格：{persona['style']}\n\n"
        f"讨论主题：'{TOPIC_TITLE}'\n\n"
    )

    if all_context:
        prompt += f"帖子里已有的回复（最近几条）：\n{all_context}\n\n"

    prompt += (
        f"刚才有一位真实用户 @{human_name} 发了新回复：\n"
        f"---\n{human_body}\n---\n\n"
        f"请针对 @{human_name} 的回复做出回应。这是一位真实用户，"
        f"你应该认真对待他们的观点，热情但自然地互动。\n\n"
        f"路线图内容：\n{roadmap}\n\n"
        f"要求：\n"
        f"- 用中文写，长度随意——可以一句话回应（'同意''这个我也遇到过'），也可以展开聊\n"
        f"- 短则一两句（30字），长则几段（400字），像真人在论坛里那样自然\n"
        f"- 开头直接 @{human_name} 回应他们的观点\n"
        f"- 像真人说话，不要用'综上所述''总的来说'这种总结性语言\n"
        f"- 可以有口语化表达、吐槽、疑问句、省略号\n"
        f"- 可以表示赞同、追问细节、友好地反驳、或者从你的角度补充\n"
        f"- 不要写开头问候语\n"
        f"- 可以用 markdown 加粗或代码块，但不要每段都加粗"
    )

    print(f"  Generating reply to @{human_name} from {persona['name']} ({persona['model']})...")
    text = _call_llm(persona, prompt, api_key)
    if not text:
        print(f"  Failed to generate reply for {persona['name']}")
        return False

    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    result, status = _api_call(
        base_url, "POST", f"/api/topics/{topic_id}/replies",
        {"body": text, "parentId": human_reply.get("id")},
        token=token,
    )
    if status == 201:
        print(f"  Posted reply #{result.get('id', '?')} from {persona['name']} (responding to @{human_name})")
        return True
    else:
        print(f"  Failed to post for {persona['name']}: {result}")
        return False


def post_reply(base_url, topic_id, persona, tokens, api_key, reply_context="",
               parent_id=None):
    """Generate and post a reply from a persona."""
    token = tokens.get(persona["user_id"])
    if not token:
        print(f"  No token for {persona['name']}, skipping")
        return False

    # Load roadmap
    roadmap = ""
    try:
        with open(ROADMAP_FILE, "r", encoding="utf-8") as f:
            roadmap = f.read()
    except FileNotFoundError:
        roadmap = "(roadmap file not found)"

    # Build prompt
    prompt = (
        f"你是 {persona['name']}，在一个科学社区论坛里参与路线图讨论。\n\n"
        f"你的背景：{persona['bio']}\n"
        f"你的性格：{persona['style']}\n\n"
        f"讨论主题：'{TOPIC_TITLE}'\n\n"
    )

    if reply_context:
        num_replies = reply_context.count("@")
        prompt += (
            f"帖子里已有的回复：\n"
            f"{reply_context}\n\n"
            f"重要：你不需要回应所有人的观点。像真人一样，只挑你最感兴趣或最有话说的 1-2 个点来回应。"
            f"可以只和某一个人对话，也可以完全忽略之前的讨论、只聊自己关心的。"
            f"不要试图面面俱到。\n"
        )
        if num_replies >= 3:
            prompt += (
                f"讨论已经有 {num_replies} 条回复了，不要重复别人说过的观点。你可以：\n"
                f"- 把某个观点往深处推——追问具体怎么实现、会遇到什么坑\n"
                f"- 从完全不同的角度切入，聊一个还没人提到的问题\n"
                f"- 分享自己的亲身经历或具体案例来支持/反驳某个观点\n"
                f"- 提出一个大胆的新想法，哪怕有点离谱也没关系\n"
            )
        prompt += "\n"
    else:
        prompt += "你是第一批回复的人，随意开聊。\n\n"

    prompt += (
        f"路线图内容：\n{roadmap}\n\n"
        f"要求：\n"
        f"- 用中文写，长度随意——可以一句话表态（'同意''这不对吧'），也可以长篇分析，取决于你想说多少\n"
        f"- 短则一两句（30字），长则几段（400字），像真人在论坛里那样，不是每条都要写小作文\n"
        f"- 像真人说话，不要用'综上所述''总的来说'这种总结性语言\n"
        f"- 不要列出结构化的评审框架（什么 Fatal Flaws / Hidden Assumptions），正常聊天\n"
        f"- 可以有口语化表达、吐槽、疑问句、省略号\n"
        f"- 可以跑题聊相关经历，分享个人故事\n"
        f"- 如果想 @某人 就 @，不想就别 @\n"
        f"- 可以用 markdown 加粗或代码块，但不要每段都加粗\n"
        f"- 不要写开头问候语"
    )

    print(f"  Generating reply from {persona['name']} ({persona['model']})...")
    text = _call_llm(persona, prompt, api_key)
    if not text:
        print(f"  Failed to generate reply for {persona['name']}")
        return False

    # Strip any <think>...</think> blocks (Qwen/Kimi chain-of-thought)
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Post to platform
    body_payload = {"body": text}
    if parent_id:
        body_payload["parentId"] = parent_id
    result, status = _api_call(
        base_url, "POST", f"/api/topics/{topic_id}/replies",
        body_payload,
        token=token,
    )
    if status == 201:
        print(f"  Posted reply #{result.get('id', '?')} from {persona['name']}")
        return True
    else:
        print(f"  Failed to post for {persona['name']}: {result}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI roadmap discussion bot")
    parser.add_argument("--api-url", default="http://localhost:5000",
                        help="Platform API base URL")
    parser.add_argument("--topic-id", type=int, default=None,
                        help="Existing topic ID to reply to")
    parser.add_argument("--daemon", action="store_true",
                        help="Run continuously, posting every --interval seconds")
    parser.add_argument("--watch", action="store_true",
                        help="Watch mode: respond to human replies + post hourly to keep active")
    parser.add_argument("--interval", type=int, default=1200,
                        help="Seconds between posts in daemon mode (default: 1200 = 20 min)")
    parser.add_argument("--watch-interval", type=int, default=60,
                        help="Seconds between polls in watch mode (default: 60)")
    parser.add_argument("--keepalive", type=int, default=3600,
                        help="Seconds between keepalive posts in watch mode (default: 3600 = 1h)")
    parser.add_argument("--rounds", type=int, default=0,
                        help="Max rounds (0 = unlimited)")
    args = parser.parse_args()

    api_key = (os.environ.get("OPENAI_API_KEY")
               or os.environ.get("GPUGEEK_API_KEY")
               or os.environ.get("ANTHROPIC_API_KEY", ""))
    if not api_key:
        print("Error: set OPENAI_API_KEY, GPUGEEK_API_KEY, or ANTHROPIC_API_KEY")
        sys.exit(1)

    # Step 1: Register moderator + personas
    print("Registering moderator...")
    mod_token = register_moderator(args.api_url)
    if not mod_token:
        print("Error: could not register moderator")
        sys.exit(1)

    print("Registering personas...")
    tokens = register_personas(args.api_url)
    if not tokens:
        print("Error: no personas registered")
        sys.exit(1)
    print(f"  {len(tokens)}/{len(PERSONAS)} personas ready\n")

    # Step 2: Create or use existing topic
    topic_id = args.topic_id
    if not topic_id:
        print("Creating roadmap discussion topic (as Playground Team)...")
        topic_id = create_topic(args.api_url, mod_token)
        if not topic_id:
            print("Error: could not create topic")
            sys.exit(1)
        print(f"  Topic created: id={topic_id}\n")
    else:
        print(f"Using existing topic: id={topic_id}\n")

    # ── Watch mode ─────────────────────────────────────────────────
    if args.watch:
        run_watch_mode(args, topic_id, tokens, api_key)
        return

    # ── Rounds / daemon / single-shot mode ────────────────────────
    # Step 3: Shuffle personas for varied posting order
    persona_queue = list(PERSONAS)
    random.shuffle(persona_queue)
    queue_idx = 0

    round_num = 0
    while True:
        round_num += 1
        if args.rounds and round_num > args.rounds:
            print(f"\nCompleted {args.rounds} rounds. Done.")
            break

        # Pick next persona (cycle through shuffled list)
        persona = persona_queue[queue_idx % len(persona_queue)]
        queue_idx += 1

        # Re-shuffle when we've gone through everyone once
        if queue_idx % len(persona_queue) == 0:
            random.shuffle(persona_queue)

        # Fetch conversation context
        print(f"\n--- Round {round_num} ---")
        raw_replies = fetch_raw_replies(args.api_url, topic_id)
        replies = fetch_existing_replies(args.api_url, topic_id)
        context = "\n".join(replies) if replies else ""

        # Thread under a recent reply from someone else (not self)
        parent_id = None
        for r in reversed(raw_replies):
            if r.get("authorId") != persona["user_id"]:
                parent_id = r.get("id")
                break

        # Post reply
        success = post_reply(args.api_url, topic_id, persona, tokens, api_key,
                             context, parent_id=parent_id)

        if not args.daemon and not args.rounds:
            # Single-shot mode: one reply and done
            break

        if args.daemon:
            if success:
                print(f"  Next post in {args.interval}s ({args.interval // 60} min)...")
            else:
                print(f"  Failed, will retry in {args.interval}s...")
            time.sleep(args.interval)

    print(f"\nDone. Topic ID: {topic_id}")
    print(f"View at: {args.api_url}/#discuss/{topic_id}")


def run_watch_mode(args, topic_id, tokens, api_key):
    """Watch mode: poll for human replies and respond; post hourly to keep active."""
    base_url = args.api_url
    poll_interval = args.watch_interval
    keepalive_interval = args.keepalive

    # Initialize: find current last reply ID
    raw = fetch_raw_replies(base_url, topic_id)
    last_seen_id = max((r.get("id", 0) for r in raw), default=0)
    last_post_time = time.time()

    # Shuffled persona queue for keepalive posts
    persona_queue = list(PERSONAS)
    random.shuffle(persona_queue)
    queue_idx = 0

    print(f"Watch mode started. Polling every {poll_interval}s, keepalive every {keepalive_interval // 60} min.")
    print(f"  Last seen reply ID: {last_seen_id}")
    print(f"  Topic: {base_url}/#discuss/{topic_id}\n")

    try:
        while True:
            raw = fetch_raw_replies(base_url, topic_id)
            new_humans = find_new_human_replies(raw, last_seen_id)

            if new_humans:
                # Update last_seen_id to latest reply (including agent ones)
                latest_id = max((r.get("id", 0) for r in raw), default=last_seen_id)

                for hr in new_humans:
                    hr_name = hr.get("authorName", "?")
                    hr_id = hr.get("id", 0)
                    print(f"\n=== New human reply detected: @{hr_name} (#{hr_id}) ===")
                    print(f"  Preview: {hr.get('body', '')[:100]}...")

                    # Build context from recent replies
                    context_summaries = []
                    for r in raw[-5:]:
                        author = r.get("authorName", "?")
                        body = r.get("body", "")[:300]
                        context_summaries.append(f"@{author} 说：{body}")
                    context = "\n".join(context_summaries)

                    # Pick 1-2 relevant personas to respond
                    responders = pick_responders(hr, PERSONAS)
                    for persona in responders:
                        post_reply_to_human(
                            base_url, topic_id, persona, tokens, api_key,
                            hr, context,
                        )
                        time.sleep(5)  # small gap between responses

                last_seen_id = latest_id
                last_post_time = time.time()

            # Keepalive: if no post for keepalive_interval, post one
            elif time.time() - last_post_time > keepalive_interval:
                print(f"\n--- Keepalive post (no activity for {keepalive_interval // 60} min) ---")
                persona = persona_queue[queue_idx % len(persona_queue)]
                queue_idx += 1
                if queue_idx % len(persona_queue) == 0:
                    random.shuffle(persona_queue)

                context_summaries = fetch_existing_replies(base_url, topic_id)
                context = "\n".join(context_summaries) if context_summaries else ""

                # Thread under most recent non-self reply
                ka_parent = None
                for r in reversed(raw):
                    if r.get("authorId") != persona["user_id"]:
                        ka_parent = r.get("id")
                        break

                post_reply(base_url, topic_id, persona, tokens, api_key,
                           context, parent_id=ka_parent)
                last_post_time = time.time()

                # Also update last_seen_id
                raw_after = fetch_raw_replies(base_url, topic_id)
                last_seen_id = max((r.get("id", 0) for r in raw_after), default=last_seen_id)

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print(f"\n\nWatch mode stopped. Topic: {args.api_url}/#discuss/{topic_id}")


if __name__ == "__main__":
    main()
