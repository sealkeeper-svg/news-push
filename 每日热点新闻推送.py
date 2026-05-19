"""
路透社 & 彭博社 每日热点新闻 微信推送
数据源: the-news API (美国28家主流媒体) + 华尔街见闻
推送: Server酱 (https://sct.ftqq.com/)
"""
import json
import os
import re
import sys
import difflib
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.parse import quote


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
TZ_BEIJING = timezone(timedelta(hours=8))

TOPICS = [
    {"key": "tech",      "emoji": "💻", "name": "Tech", "keywords": [
        "spacex", "openai", "apple", "nvidia", "ai chip",
        "semiconductor", "tsmc", "chip", "asml", "hbm",
        "芯片", "半导体", "台积电", "英伟达", "阿斯麦", "人工智能", "太空探索",
    ]},
    {"key": "us_market", "emoji": "📈", "name": "US Market", "keywords": [
        "stock market", "s&p", "nasdaq", "treasury", "bond yield", "dow jones", "ipo",
        "股市", "美股", "标普", "纳斯达克", "国债", "道琼斯",
    ]},
    {"key": "energy",    "emoji": "🛢️", "name": "Energy", "keywords": [
        "oil", "crude", "brent", "energy", "natural gas", "opec",
        "battery", "lithium", "solar", "nuclear",
        "石油", "原油", "能源", "天然气", "欧佩克", "电池", "锂", "太阳能", "核能",
    ]},
    {"key": "macro",     "emoji": "📊", "name": "Macro", "keywords": [
        "fed chair", "warsh", "inflation", "rate hike", "cpi", "recession", "gdp",
        "美联储", "通胀", "加息", "衰退",
    ]},
    {"key": "us_politics","emoji": "🇺🇸", "name": "US Politics", "keywords": [
        "trump", "biden", "congress",
        "特朗普", "拜登", "国会",
    ]},
    {"key": "mideast",   "emoji": "🌍", "name": "Mid-East / Geo", "keywords": [
        "iran war", "hormuz", "israel", "hamas", "october 7", "gaza",
        "ceasefire", "russia", "ukraine", "nato",
        "伊朗", "以色列", "哈马斯", "加沙", "停火", "俄罗斯", "乌克兰", "北约",
    ]},
    {"key": "china",     "emoji": "🇨🇳", "name": "US-China", "keywords": [
        "xi jinping", "china summit", "trade war", "tariff", "decouple", "sanction",
        "习近平", "贸易战", "关税", "脱钩", "制裁",
    ]},
    {"key": "health",    "emoji": "🧠", "name": "Health & Science", "keywords": [
        "neuroscience", "brain", "sleep", "focus", "attention", "longevity",
        "神经科学", "大脑", "睡眠", "专注", "长寿",
    ]},
    {"key": "other",     "emoji": "📌", "name": "Other", "keywords": [
        "strike", "virus", "outbreak", "health",
        "罢工", "病毒", "疫情", "健康",
    ]},
]

MEDIA_TIER1 = ["new york times", "wall street journal", "washington post",
               "financial times", "bloomberg"]
MEDIA_TIER2 = ["reuters", "associated press", "ap", "economist", "politico",
               "npr", "cnn"]

RB_MARKERS = ["reuters", "路透社", "路透", "bloomberg", "彭博社", "彭博",
              "据外媒", "援引消息人士", "知情人士透露", "sources say",
              "people familiar with", "according to sources"]

MIN_TOTAL = 15
MAX_TOTAL = 20
NORMAL_CAP = 2
FLEX_CAP = 3
DEDUP_THRESHOLD = 0.6
WSCN_LIMIT = 50


def load_config():
    if not os.path.exists(CONFIG_FILE):
        safe_print(f"[ERROR] 配置文件不存在: {CONFIG_FILE}")
        safe_print("请先创建 config.json，填入 Server酱 SendKey")
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def fetch_thehear_us():
    url = "https://www.thehear.org/api/country-view/us"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("headlines", [])
    except Exception as e:
        safe_print(f"[WARN] the-news API error: {e}")
        return []


def fetch_wallstreetcn():
    url = f"https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit={WSCN_LIMIT}"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("data", {}).get("items", [])
    except Exception as e:
        safe_print(f"[WARN] WallStreetCN error: {e}")
        return []


def wscn_as_headline(item):
    title = item.get("title", "")
    content = item.get("content_text", "") or item.get("content", "")
    if title.strip():
        return title.strip(), content.strip()
    return content.strip()[:100], content.strip()[:200]


def has_rb_source(item):
    title = item.get("title", "") or item.get("headline", "")
    subtitle = item.get("subtitle", "")
    content = item.get("content_text", "") or item.get("content", "")
    text = f"{title} {subtitle} {content}".lower()
    return any(m.lower() in text for m in RB_MARKERS)


def media_bonus(item):
    label = (item.get("sourceLabel", "") or "").lower()
    if any(m in label for m in MEDIA_TIER1):
        return 30
    if any(m in label for m in MEDIA_TIER2):
        return 20
    return 0


_built = False
_flat_keywords = []

def _build_keywords():
    global _built, _flat_keywords
    if _built:
        return
    for topic in TOPICS:
        _flat_keywords.extend(topic["keywords"])
    _built = True


def calc_score(item, src_type="hear"):
    _build_keywords()
    title = item.get("title", "") or item.get("headline", "")
    subtitle = item.get("subtitle", "")
    content = item.get("content_text", "") or item.get("content", "")
    text = f"{title} {subtitle} {content}".lower()

    score = 0
    for i, kw in enumerate(_flat_keywords):
        if kw in text:
            score += len(_flat_keywords) - i

    if has_rb_source(item):
        score += 40 if src_type == "hear" else 50

    if src_type == "hear":
        score += media_bonus(item)
    return score


def assign_topic(item):
    title = item.get("title", "") or item.get("headline", "")
    subtitle = item.get("subtitle", "")
    content = item.get("content_text", "") or item.get("content", "")
    text = f"{title} {subtitle} {content}".lower()

    for topic in TOPICS:
        for kw in topic["keywords"]:
            if kw in text:
                return topic["key"]
    return "other"


def is_similar(text1, text2, threshold=DEDUP_THRESHOLD):
    return difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio() > threshold


def subtitle_text(item):
    return (item.get("subtitle") or "").strip()


def translate_to_en(text):
    if not text or not text.strip():
        return text
    if not re.search(r'[一-鿿]', text):
        return text
    try:
        url = f"https://api.mymemory.translated.net/get?q={quote(text[:500])}&langpair=zh|en"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        translated = data.get("responseData", {}).get("translatedText", text)
        if translated and translated != text:
            return translated.strip()
    except Exception:
        pass
    return text


def select_items(scored_items):
    topic_counts = defaultdict(int)
    selected = []
    seen_headlines = []

    def try_select(item, cap):
        if topic_counts[item["topic"]] >= cap:
            return False
        hl = item["headline"]
        if any(is_similar(hl, seen) for seen in seen_headlines):
            return False
        selected.append(item)
        seen_headlines.append(hl)
        topic_counts[item["topic"]] += 1
        return True

    for item in scored_items:
        if len(selected) >= MAX_TOTAL:
            break
        try_select(item, NORMAL_CAP)

    if len(selected) < MIN_TOTAL:
        for item in scored_items:
            if len(selected) >= MAX_TOTAL:
                break
            if item in selected:
                continue
            try_select(item, FLEX_CAP)

    return selected


def format_message(selected):
    now = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d %H:%M")
    lines = [
        "## Reuters & Bloomberg Daily Top News",
        f"**{now}** (Beijing Time)",
        "",
    ]

    grouped = defaultdict(list)
    for item in selected:
        grouped[item["topic"]].append(item)

    counter = [0]

    for topic in TOPICS:
        items = grouped.get(topic["key"], [])
        if not items:
            continue

        lines.append(f"## {topic['emoji']} {topic['name']}")
        lines.append("")

        for item in items:
            counter[0] += 1
            hl = item["headline"]
            sub = item["subtitle"]
            original = item["original"]
            is_rb = item["is_rb"]

            tag = "**[Reuters/Bloomberg]** " if is_rb else ""
            lines.append(f"### {counter[0]}. {tag}{hl[:150]}")

            if sub:
                lines.append(f"> {sub[:300]}")

            if original.get("link"):
                lines.append(f"> [{original.get('sourceLabel', 'Source')}]({original['link']})")

            lines.append("")
            lines.append("---")
            lines.append("")

    lines.append("*Data: the-news API + WallStreetCN | Push: ServerChan*")
    return "\n".join(lines)


def push_wechat(sendkey, title, content):
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    body = json.dumps({"title": title, "desp": content}).encode("utf-8")
    try:
        req = Request(url, data=body,
                      headers={"Content-Type": "application/json"},
                      method="POST")
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        code = result.get("code", -1)
        if code == 0:
            safe_print("[OK] 微信推送成功!")
            return True
        else:
            safe_print(f"[FAIL] Server酱返回: {result.get('message', result)}")
            return False
    except Exception as e:
        safe_print(f"[ERROR] 推送失败: {e}")
        return False


def main():
    config = load_config()
    sendkey = config.get("sendkey", "")
    if not sendkey or sendkey == "YOUR_SENDKEY_HERE":
        safe_print("[ERROR] 请先在 config.json 中填入 Server酱 SendKey")
        safe_print("获取方式: 打开 https://sct.ftqq.com/ 微信扫码登录即可")
        sys.exit(1)

    safe_print("[INFO] 获取 the-news API (28家美国媒体头条)...")
    headlines = fetch_thehear_us()
    safe_print(f"[INFO] -> 获取到 {len(headlines)} 条")

    safe_print("[INFO] 获取华尔街见闻 7x24 快讯...")
    wscn = fetch_wallstreetcn()
    safe_print(f"[INFO] -> 获取到 {len(wscn)} 条")

    safe_print("[INFO] 智能排序筛选...")
    scored = []
    for h in headlines:
        scored.append((calc_score(h, "hear"), "hear", h))

    for item in wscn:
        scored.append((calc_score(item, "wscn"), "wscn", item))

    scored.sort(key=lambda x: x[0], reverse=True)

    item_dicts = []
    for score, src_type, raw in scored:
        if src_type == "hear":
            hl = (raw.get("headline", "") or "").strip()
            sub = subtitle_text(raw)
        else:
            hl, body = wscn_as_headline(raw)
            sub = body[:300] if body else ""

        if len(hl) < 8:
            continue

        item_dicts.append({
            "score": score,
            "topic": assign_topic(raw),
            "headline": hl,
            "subtitle": sub,
            "is_rb": has_rb_source(raw),
            "original": raw,
        })

    selected = select_items(item_dicts)

    safe_print("[INFO] Translating Chinese content to English...")
    for item in selected:
        src_label = item["original"].get("sourceLabel")
        if src_label is None:
            item["headline"] = translate_to_en(item["headline"])
            item["subtitle"] = translate_to_en(item["subtitle"])

    content = format_message(selected)

    safe_print("\n" + content + "\n")

    safe_print("[INFO] Pushing to WeChat...")
    now = datetime.now(TZ_BEIJING).strftime("%m/%d %H:%M")
    push_wechat(sendkey, f"Reuters & Bloomberg Top News {now}", content)


if __name__ == "__main__":
    main()
