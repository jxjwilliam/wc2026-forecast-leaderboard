"""
parse_forecasts.py — One-time ingestion of all 4 LLM forecast files into SQLite.

Reads forecast data from data/ directory, normalises into a standard schema,
and inserts into forecasts.db.

Model formats handled:
  - Claude PDF: most structured (#, date, group, teams, score, confidence %)
  - ChatGPT: markdown tables per group (Group K corrected: Jamaica → Congo DRC)
  - Gemini: table with two scenarios per match
  - Doubao: table with group standings + qualification predictions
"""

import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

DB_PATH = "forecasts.db"
DATA_DIR = Path("data")

# ─── Team name normalisation ────────────────────────────────────────────────
# Bidirectional team name mapping: Chinese ↔ English
# Key = variant seen in source data, Value = canonical Chinese name
TEAM_MAP = {
    # Chinese variants → Chinese canonical (for matching across models)
    "刚果(金)": "刚果(金)",
    "民主刚果": "刚果(金)",
    "刚果金": "刚果(金)",
    "刚果（金）": "刚果(金)",
    "韩国 ": "韩国",
    "韩国": "韩国",
    "土耳其 ": "土耳其",
    "土耳其": "土耳其",
    "库拉索 ": "库拉索",
    "库拉索": "库拉索",
    "佛得角": "佛得角",
    "捷克": "捷克",
    "波黑": "波黑",
    "卡塔尔": "卡塔尔",
    "瑞士": "瑞士",
    "瑞典": "瑞典",
    "突尼斯": "突尼斯",
    "塞内加尔": "塞内加尔",
    "伊拉克": "伊拉克",
    "挪威": "挪威",
    "巴拉圭": "巴拉圭",
    "乌拉圭": "乌拉圭",
    "澳大利亞": "澳大利亚",
    "澳大利亚": "澳大利亚",
    "荷兰": "荷兰",
    "海地": "海地",
    "苏格兰": "苏格兰",
    "巴西": "巴西",
    "摩洛哥": "摩洛哥",
    "美国": "美国",
    "英格兰": "英格兰",
    "克罗地亚": "克罗地亚",
    "加纳": "加纳",
    "巴拿马": "巴拿马",
    "葡萄牙": "葡萄牙",
    "哥伦比亚": "哥伦比亚",
    "乌兹别克斯坦": "乌兹别克斯坦",
    "乌兹别克": "乌兹别克斯坦",
    "阿根廷": "阿根廷",
    "奥地利": "奥地利",
    "约旦": "约旦",
    "阿尔及利亚": "阿尔及利亚",
    "法国": "法国",
    "西班牙": "西班牙",
    "沙特阿拉伯": "沙特阿拉伯",
    "比利时": "比利时",
    "埃及": "埃及",
    "伊朗": "伊朗",
    "新西兰": "新西兰",
    "日本": "日本",
    "德国": "德国",
    "厄瓜多尔": "厄瓜多尔",
    "科特迪瓦": "科特迪瓦",
    "墨西哥": "墨西哥",
    "南非": "南非",
    "加拿大": "加拿大",
    "乌克兰": "乌克兰",  # ChatGPT uses this instead of 瑞典 for group F
    # English → Chinese (for ChatGPT which outputs English names)
    "Mexico": "墨西哥",
    "South Africa": "南非",
    "Korea Republic": "韩国",
    "Czechia": "捷克",
    "Korea": "韩国",
    "Canada": "加拿大",
    "Bosnia": "波黑",
    "Qatar": "卡塔尔",
    "Switzerland": "瑞士",
    "Brazil": "巴西",
    "Morocco": "摩洛哥",
    "Haiti": "海地",
    "Scotland": "苏格兰",
    "USA": "美国",
    "Paraguay": "巴拉圭",
    "Australia": "澳大利亚",
    "Türkiye": "土耳其",
    "Turkey": "土耳其",
    "Germany": "德国",
    "Curaçao": "库拉索",
    "Curacao": "库拉索",
    "Ivory Coast": "科特迪瓦",
    "Ecuador": "厄瓜多尔",
    "Netherlands": "荷兰",
    "Japan": "日本",
    "Ukraine": "乌克兰",
    "Tunisia": "突尼斯",
    "Belgium": "比利时",
    "Egypt": "埃及",
    "Iran": "伊朗",
    "New Zealand": "新西兰",
    "Spain": "西班牙",
    "Cabo Verde": "佛得角",
    "Saudi Arabia": "沙特阿拉伯",
    "France": "法国",
    "Senegal": "塞内加尔",
    "Iraq": "伊拉克",
    "Norway": "挪威",
    "Argentina": "阿根廷",
    "Algeria": "阿尔及利亚",
    "Austria": "奥地利",
    "Jordan": "约旦",
    "Portugal": "葡萄牙",
    "Jamaica": "刚果(金)",  # ChatGPT error → corrected per user instruction
    "Colombia": "哥伦比亚",
    "Uzbekistan": "乌兹别克斯坦",
    "England": "英格兰",
    "Croatia": "克罗地亚",
    "Ghana": "加纳",
    "Panama": "巴拿马",
    "Poland": "波兰",
    "Sweden": "瑞典",
}


def normalise_team(name: str) -> str:
    """Map any variant to canonical Chinese team name."""
    cleaned = name.strip().rstrip('*')
    return TEAM_MAP.get(cleaned, cleaned)


# ─── Schema ──────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    source_file TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    match_number INTEGER,
    group_name TEXT NOT NULL,
    round INTEGER,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    match_date TEXT,
    stage TEXT DEFAULT 'group'
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY,
    model_id INTEGER NOT NULL,
    match_id INTEGER NOT NULL,
    scenario TEXT DEFAULT 'single',
    home_score INTEGER,
    away_score INTEGER,
    confidence REAL,
    FOREIGN KEY (model_id) REFERENCES models(id),
    FOREIGN KEY (match_id) REFERENCES matches(id),
    UNIQUE(model_id, match_id, scenario)
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL UNIQUE,
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    fetched_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (match_id) REFERENCES matches(id)
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY,
    prediction_id INTEGER NOT NULL UNIQUE,
    exact_score INTEGER DEFAULT 0,
    correct_result INTEGER DEFAULT 0,
    goal_diff_bonus REAL DEFAULT 0.0,
    total REAL DEFAULT 0.0,
    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
);

CREATE TABLE IF NOT EXISTS group_standings (
    id INTEGER PRIMARY KEY,
    model_id INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    team TEXT NOT NULL,
    position INTEGER NOT NULL,
    points INTEGER,
    qualified INTEGER DEFAULT 0,
    FOREIGN KEY (model_id) REFERENCES models(id)
);
"""

# ─── Canonical matches (from Claude PDF) ────────────────────────────────────

CANONICAL_MATCHES: list[dict] = [
    # Group A
    {"num": 1,  "group": "A", "round": 1, "home": "墨西哥",  "away": "南非",          "date": "2026-06-11"},
    {"num": 2,  "group": "A", "round": 1, "home": "韩国",    "away": "捷克",          "date": "2026-06-11"},
    {"num": 25, "group": "A", "round": 2, "home": "捷克",    "away": "南非",          "date": "2026-06-18"},
    {"num": 28, "group": "A", "round": 2, "home": "墨西哥",  "away": "韩国",          "date": "2026-06-18"},
    {"num": 50, "group": "A", "round": 3, "home": "南非",    "away": "韩国",          "date": "2026-06-24"},
    {"num": 52, "group": "A", "round": 3, "home": "墨西哥",  "away": "捷克",          "date": "2026-06-24"},
    # Group B
    {"num": 3,  "group": "B", "round": 1, "home": "加拿大",  "away": "波黑",          "date": "2026-06-12"},
    {"num": 5,  "group": "B", "round": 1, "home": "卡塔尔",  "away": "瑞士",          "date": "2026-06-13"},
    {"num": 26, "group": "B", "round": 2, "home": "瑞士",    "away": "波黑",          "date": "2026-06-18"},
    {"num": 27, "group": "B", "round": 2, "home": "加拿大",  "away": "卡塔尔",         "date": "2026-06-18"},
    {"num": 49, "group": "B", "round": 3, "home": "波黑",    "away": "卡塔尔",         "date": "2026-06-24"},
    {"num": 51, "group": "B", "round": 3, "home": "瑞士",    "away": "加拿大",         "date": "2026-06-24"},
    # Group C
    {"num": 6,  "group": "C", "round": 1, "home": "巴西",    "away": "摩洛哥",         "date": "2026-06-13"},
    {"num": 7,  "group": "C", "round": 1, "home": "海地",    "away": "苏格兰",         "date": "2026-06-13"},
    {"num": 29, "group": "C", "round": 2, "home": "苏格兰",  "away": "摩洛哥",         "date": "2026-06-19"},
    {"num": 31, "group": "C", "round": 2, "home": "巴西",    "away": "海地",          "date": "2026-06-19"},
    {"num": 54, "group": "C", "round": 3, "home": "摩洛哥",  "away": "海地",          "date": "2026-06-25"},
    {"num": 56, "group": "C", "round": 3, "home": "苏格兰",  "away": "巴西",          "date": "2026-06-25"},
    # Group D
    {"num": 4,  "group": "D", "round": 1, "home": "美国",    "away": "巴拉圭",         "date": "2026-06-12"},
    {"num": 8,  "group": "D", "round": 1, "home": "澳大利亚", "away": "土耳其",        "date": "2026-06-13"},
    {"num": 30, "group": "D", "round": 2, "home": "美国",    "away": "澳大利亚",       "date": "2026-06-19"},
    {"num": 32, "group": "D", "round": 2, "home": "土耳其",  "away": "巴拉圭",         "date": "2026-06-20"},
    {"num": 53, "group": "D", "round": 3, "home": "美国",    "away": "土耳其",         "date": "2026-06-25"},
    {"num": 55, "group": "D", "round": 3, "home": "巴拉圭",  "away": "澳大利亚",       "date": "2026-06-25"},
    # Group E
    {"num": 9,  "group": "E", "round": 1, "home": "德国",    "away": "库拉索",         "date": "2026-06-14"},
    {"num": 10, "group": "E", "round": 1, "home": "科特迪瓦", "away": "厄瓜多尔",      "date": "2026-06-14"},
    {"num": 33, "group": "E", "round": 2, "home": "厄瓜多尔", "away": "库拉索",        "date": "2026-06-20"},
    {"num": 35, "group": "E", "round": 2, "home": "德国",    "away": "科特迪瓦",       "date": "2026-06-20"},
    {"num": 65, "group": "E", "round": 3, "home": "库拉索",  "away": "科特迪瓦",       "date": "2026-06-27"},
    {"num": 67, "group": "E", "round": 3, "home": "厄瓜多尔", "away": "德国",         "date": "2026-06-27"},
    # Group F
    {"num": 11, "group": "F", "round": 1, "home": "荷兰",    "away": "日本",          "date": "2026-06-14"},
    {"num": 12, "group": "F", "round": 1, "home": "瑞典",    "away": "突尼斯",         "date": "2026-06-14"},
    {"num": 34, "group": "F", "round": 2, "home": "日本",    "away": "瑞典",          "date": "2026-06-20"},
    {"num": 36, "group": "F", "round": 2, "home": "荷兰",    "away": "突尼斯",         "date": "2026-06-21"},
    {"num": 66, "group": "F", "round": 3, "home": "日本",    "away": "突尼斯",         "date": "2026-06-27"},
    {"num": 68, "group": "F", "round": 3, "home": "荷兰",    "away": "瑞典",          "date": "2026-06-27"},
    # Group G
    {"num": 14, "group": "G", "round": 1, "home": "比利时",  "away": "埃及",          "date": "2026-06-15"},
    {"num": 16, "group": "G", "round": 1, "home": "伊朗",    "away": "新西兰",         "date": "2026-06-15"},
    {"num": 37, "group": "G", "round": 2, "home": "埃及",    "away": "新西兰",         "date": "2026-06-21"},
    {"num": 39, "group": "G", "round": 2, "home": "比利时",  "away": "伊朗",          "date": "2026-06-21"},
    {"num": 61, "group": "G", "round": 3, "home": "埃及",    "away": "伊朗",          "date": "2026-06-26"},
    {"num": 62, "group": "G", "round": 3, "home": "新西兰",  "away": "比利时",         "date": "2026-06-26"},
    # Group H
    {"num": 13, "group": "H", "round": 1, "home": "西班牙",  "away": "佛得角",         "date": "2026-06-15"},
    {"num": 15, "group": "H", "round": 1, "home": "沙特阿拉伯", "away": "乌拉圭",      "date": "2026-06-15"},
    {"num": 38, "group": "H", "round": 2, "home": "西班牙",  "away": "沙特阿拉伯",      "date": "2026-06-21"},
    {"num": 40, "group": "H", "round": 2, "home": "乌拉圭",  "away": "佛得角",         "date": "2026-06-22"},
    {"num": 59, "group": "H", "round": 3, "home": "佛得角",  "away": "沙特阿拉伯",      "date": "2026-06-26"},
    {"num": 60, "group": "H", "round": 3, "home": "乌拉圭",  "away": "西班牙",         "date": "2026-06-26"},
    # Group I
    {"num": 17, "group": "I", "round": 1, "home": "法国",    "away": "塞内加尔",       "date": "2026-06-16"},
    {"num": 18, "group": "I", "round": 1, "home": "伊拉克",  "away": "挪威",          "date": "2026-06-16"},
    {"num": 41, "group": "I", "round": 2, "home": "塞内加尔", "away": "伊拉克",        "date": "2026-06-22"},
    {"num": 43, "group": "I", "round": 2, "home": "法国",    "away": "挪威",          "date": "2026-06-22"},
    {"num": 57, "group": "I", "round": 3, "home": "法国",    "away": "伊拉克",         "date": "2026-06-26"},
    {"num": 58, "group": "I", "round": 3, "home": "塞内加尔", "away": "挪威",          "date": "2026-06-26"},
    # Group J
    {"num": 19, "group": "J", "round": 1, "home": "阿根廷",  "away": "阿尔及利亚",      "date": "2026-06-16"},
    {"num": 20, "group": "J", "round": 1, "home": "奥地利",  "away": "约旦",          "date": "2026-06-16"},
    {"num": 42, "group": "J", "round": 2, "home": "阿根廷",  "away": "奥地利",         "date": "2026-06-22"},
    {"num": 44, "group": "J", "round": 2, "home": "约旦",    "away": "阿尔及利亚",      "date": "2026-06-23"},
    {"num": 69, "group": "J", "round": 3, "home": "阿尔及利亚", "away": "奥地利",      "date": "2026-06-27"},
    {"num": 70, "group": "J", "round": 3, "home": "约旦",    "away": "阿根廷",         "date": "2026-06-27"},
    # Group K
    {"num": 21, "group": "K", "round": 1, "home": "葡萄牙",  "away": "刚果(金)",       "date": "2026-06-17"},
    {"num": 24, "group": "K", "round": 1, "home": "乌兹别克斯坦", "away": "哥伦比亚",  "date": "2026-06-17"},
    {"num": 45, "group": "K", "round": 2, "home": "葡萄牙",  "away": "乌兹别克斯坦",    "date": "2026-06-23"},
    {"num": 47, "group": "K", "round": 2, "home": "哥伦比亚", "away": "刚果(金)",       "date": "2026-06-23"},
    {"num": 71, "group": "K", "round": 3, "home": "葡萄牙",  "away": "哥伦比亚",       "date": "2026-06-27"},
    {"num": 72, "group": "K", "round": 3, "home": "刚果(金)", "away": "乌兹别克斯坦",   "date": "2026-06-27"},
    # Group L
    {"num": 22, "group": "L", "round": 1, "home": "英格兰",  "away": "克罗地亚",       "date": "2026-06-17"},
    {"num": 23, "group": "L", "round": 1, "home": "加纳",    "away": "巴拿马",         "date": "2026-06-17"},
    {"num": 46, "group": "L", "round": 2, "home": "英格兰",  "away": "加纳",          "date": "2026-06-23"},
    {"num": 48, "group": "L", "round": 2, "home": "克罗地亚", "away": "巴拿马",        "date": "2026-06-24"},
    {"num": 63, "group": "L", "round": 3, "home": "巴拿马",  "away": "英格兰",         "date": "2026-06-27"},
    {"num": 64, "group": "L", "round": 3, "home": "克罗地亚", "away": "加纳",         "date": "2026-06-27"},
]


# ─── Database helpers ────────────────────────────────────────────────────────

def get_or_create_model(conn: sqlite3.Connection, name: str, display_name: str,
                         source_file: str) -> int:
    cur = conn.execute("SELECT id FROM models WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO models (name, display_name, source_file) VALUES (?, ?, ?)",
        (name, display_name, source_file),
    )
    return cur.lastrowid


def insert_matches(conn: sqlite3.Connection) -> dict:
    """Insert canonical matches and return {match_number: match_id} mapping."""
    cur = conn.execute("SELECT COUNT(*) FROM matches")
    if cur.fetchone()[0] > 0:
        rows = conn.execute("SELECT match_number, id FROM matches").fetchall()
        return {r[0]: r[1] for r in rows}

    mapping = {}
    for m in CANONICAL_MATCHES:
        cur = conn.execute(
            """INSERT INTO matches (match_number, group_name, round,
                                    home_team, away_team, match_date, stage)
               VALUES (?, ?, ?, ?, ?, ?, 'group')""",
            (m["num"], m["group"], m["round"],
             m["home"], m["away"], m["date"]),
        )
        mapping[m["num"]] = cur.lastrowid
    print(f"  Inserted {len(mapping)} canonical matches")
    return mapping


def match_id_from_teams(match_map: dict, group: str, home: str, away: str) -> Optional[int]:
    """Find a match by group + team names (accounting for normalisation)."""
    home_norm = normalise_team(home)
    away_norm = normalise_team(away)
    for m in CANONICAL_MATCHES:
        if m["group"] == group:
            mh = normalise_team(m["home"])
            ma = normalise_team(m["away"])
            if home_norm == mh and away_norm == ma:
                return match_map.get(m["num"])
    return None


# ─── Text helpers ────────────────────────────────────────────────────────────

def clean_team_name(name: str) -> str:
    """Remove emoji flags and extra whitespace."""
    name = re.sub(r'[🇦-🇿]', '', name)
    name = re.sub(r'[\U0001F300-\U0001FAFF]', '', name)
    return name.strip()


def parse_score(text: str) -> Optional[tuple[int, int]]:
    # Handle both plain hyphens and escaped hyphens (\-)
    text = text.replace('\\-', '-')
    m = re.search(r'(\d+)\s*[-–]\s*(\d+)', text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


# ─── ChatGPT parser ──────────────────────────────────────────────────────────

def parse_chatgpt(text: str) -> list[dict]:
    """
    12 groups (A-L), each with a markdown table:
    | 比赛 | 预测比分 |
    | Team1 vs Team2 | 2-0 |
    """
    predictions = []
    current_group = None
    in_table = False
    group_pattern = re.compile(r'^##\s*Group\s+([A-L])\s*$', re.IGNORECASE)

    for line in text.split('\n'):
        gm = group_pattern.match(line)
        if gm:
            current_group = gm.group(1)
            in_table = False
            continue

        if current_group and '|' in line:
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 2:
                match_part = parts[0]
                score_part = parts[1]

                if '比赛' in match_part or '预测比分' in score_part:
                    in_table = True
                    continue

                if in_table and re.search(r'[vV][sS]', match_part):
                    teams = re.split(r'\s+[vV][sS]\s+', match_part, maxsplit=1)
                    if len(teams) == 2:
                        home = clean_team_name(teams[0])
                        away = clean_team_name(teams[1])
                        score = parse_score(score_part)
                        if score:
                            hs, as_ = score
                            # Group K correction: ChatGPT says Portugal vs Jamaica
                            # User confirmed: correct to Congo DRC
                            if current_group == 'K':
                                if 'Jamaica' in away:
                                    away = '刚果(金)'
                                elif 'Jamaica' in home:
                                    home = '刚果(金)'
                            predictions.append({
                                'group': current_group,
                                'home': home, 'away': away,
                                'home_score': hs, 'away_score': as_,
                                'confidence': None, 'scenario': 'single',
                            })
        else:
            in_table = False

    return predictions


# ─── Claude PDF parser ───────────────────────────────────────────────────────

def parse_claude(text: str) -> list[dict]:
    predictions = []
    pat = re.compile(
        r'(\d+)\s+'                         # match number
        r'(\d+/\d+)\s+'                     # date
        r'([A-L])\s+'                       # group
        r'(.+?)\s+'                         # home
        r'(\d+)[–-](\d+)\s+'                # score
        r'(.+?)\s+'                         # away
        r'(?:Home Win|Away Win|Draw)\s+'
        r'(\d+)%'                           # confidence
    )

    # Pre-process: join continuation lines (pdftotext sometimes wraps scores)
    lines = text.split('\n')
    merged = []
    for line in lines:
        # Lines with heavy leading whitespace are continuation of previous
        if merged and re.match(r'^\s{40,}', line):
            merged[-1] = merged[-1].rstrip() + line.strip()
        else:
            merged.append(line)

    for line in merged:
        m = pat.search(line)
        if m:
            match_num = int(m.group(1))
            home = m.group(4).strip()
            home_score = int(m.group(5))
            away_score = int(m.group(6))
            away = m.group(7).strip()
            confidence = int(m.group(8))

            group = None
            for cm in CANONICAL_MATCHES:
                if cm["num"] == match_num:
                    group = cm["group"]
                    break

            if group:
                predictions.append({
                    'group': group,
                    'home': home, 'away': away,
                    'home_score': home_score, 'away_score': away_score,
                    'confidence': confidence / 100.0,
                    'scenario': 'single',
                })
    return predictions


# ─── Gemini parser ───────────────────────────────────────────────────────────

def parse_gemini(text: str) -> list[dict]:
    predictions = []
    for line in text.split('\n'):
        if '|' not in line:
            continue
        parts = [p.strip() for p in line.split('|') if p.strip()]
        if len(parts) < 4:
            continue

        gm = re.match(r'([A-L])组', parts[0])
        if not gm:
            continue
        group = gm.group(1)

        teams = re.split(r'\s+[vV][sS]\s+', parts[2], maxsplit=1)
        if len(teams) != 2:
            continue
        home = clean_team_name(teams[0])
        away = clean_team_name(teams[1])

        s1 = parse_score(parts[3]) if len(parts) > 3 else None
        s2 = parse_score(parts[4]) if len(parts) > 4 else None

        if s1:
            predictions.append({
                'group': group, 'home': home, 'away': away,
                'home_score': s1[0], 'away_score': s1[1],
                'confidence': None, 'scenario': 'scenario_1',
            })
        if s2:
            predictions.append({
                'group': group, 'home': home, 'away': away,
                'home_score': s2[0], 'away_score': s2[1],
                'confidence': None, 'scenario': 'scenario_2',
            })
    return predictions


# ─── Doubao parser ───────────────────────────────────────────────────────────

def parse_doubao(text: str) -> tuple[list[dict], list[dict]]:
    predictions = []
    standings = []

    standing_pat = re.compile(
        r'(\d+)\.\s*([^(★✔✘\s]+)\s*(?:\((\d+)分\))?\s*([✔✘])?'
    )
    group_pat = re.compile(r'^([A-L])组')

    current_group = None

    for line in text.split('\n'):
        if '|' not in line:
            continue
        # Split preserving empty cells (Doubao uses empty first cell for continuation rows)
        raw_parts = line.split('|')
        parts = [p.strip() for p in raw_parts]
        meaningful = [p for p in parts if p]

        if parts[1]:
            gm = group_pat.match(parts[1])
            if gm:
                current_group = gm.group(1)

        if current_group is None or len(meaningful) < 3:
            continue

        # Find columns: matchup (contains VS) and score (contains N-N)
        matchup_idx = score_idx = None
        for i, p in enumerate(meaningful):
            if re.search(r'[vV][sS]', p):
                matchup_idx = i
            if re.search(r'\d+\s*[-–\\]?\s*\d+', p.replace('\\-', '-')):
                if score_idx is None:
                    score_idx = i

        if matchup_idx is None or score_idx is None or score_idx <= matchup_idx:
            continue

        matchup = meaningful[matchup_idx]
        score_text = meaningful[score_idx]

        teams = re.split(r'\s+[vV][sS]\s+', matchup, maxsplit=1)
        if len(teams) != 2:
            continue
        home = clean_team_name(teams[0])
        away = clean_team_name(teams[1])

        score = parse_score(score_text)
        if not score:
            continue

        predictions.append({
            'group': current_group, 'home': home, 'away': away,
            'home_score': score[0], 'away_score': score[1],
            'confidence': None, 'scenario': 'single',
        })

        # Standings from column after score (if present)
        standings_idx = score_idx + 1
        if len(meaningful) > standings_idx:
            standings_text = meaningful[standings_idx].replace('\\.', '.').replace('\\(', '(').replace('\\)', ')').replace('\\-', '-')
            for sm in standing_pat.finditer(standings_text):
                team = clean_team_name(sm.group(2))
                points = int(sm.group(3)) if sm.group(3) else None
                qualified = 1 if sm.group(4) == '✔' else 0
                standings.append({
                    'group': current_group, 'team': team,
                    'position': int(sm.group(1)),
                    'points': points, 'qualified': qualified,
                })

    return predictions, standings


# ─── DB insertion ────────────────────────────────────────────────────────────

def insert_predictions(conn: sqlite3.Connection, model_id: int,
                       predictions: list[dict], match_map: dict) -> int:
    count = 0
    for p in predictions:
        mid = match_id_from_teams(match_map, p['group'], p['home'], p['away'])
        if mid is None:
            mid = match_id_from_teams(match_map, p['group'], p['away'], p['home'])
            if mid is not None:
                p['home_score'], p['away_score'] = p['away_score'], p['home_score']

        if mid is None:
            print(f"    WARNING: Unmatched: {p['home']} vs {p['away']} (group {p['group']})")
            continue

        try:
            conn.execute(
                "INSERT OR IGNORE INTO predictions "
                "(model_id, match_id, scenario, home_score, away_score, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (model_id, mid, p['scenario'],
                 p['home_score'], p['away_score'], p['confidence']),
            )
            if conn.total_changes:
                count += 1
        except sqlite3.IntegrityError:
            pass
    return count


def insert_standings(conn: sqlite3.Connection, model_id: int,
                     standings: list[dict]) -> int:
    for s in standings:
        conn.execute(
            "INSERT INTO group_standings "
            "(model_id, group_name, team, position, points, qualified) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (model_id, s['group'], s['team'],
             s['position'], s['points'], s['qualified']),
        )
    return len(standings)


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    print("Schema ready.")

    # Register models
    models = [
        ("chatgpt", "ChatGPT", "chatgpt.md"),
        ("claude", "Claude", "claude.pdf"),
        ("gemini", "Gemini", "gemini.md"),
        ("doubao", "Doubao", "doubao.md"),
    ]
    model_ids = {}
    for name, display, source in models:
        model_ids[name] = get_or_create_model(conn, name, display, source)
    print(f"Models: {len(model_ids)} registered")

    # Insert matches
    match_map = insert_matches(conn)
    conn.commit()

    # --- Parse ChatGPT ---
    print("\n--- ChatGPT ---")
    text = (DATA_DIR / "chatgpt.md").read_text(encoding="utf-8")
    preds = parse_chatgpt(text)
    c = insert_predictions(conn, model_ids["chatgpt"], preds, match_map)
    print(f"  {c} predictions")
    conn.commit()

    # --- Parse Claude ---
    print("\n--- Claude ---")
    result = subprocess.run(
        ["pdftotext", "-layout", str(DATA_DIR / "claude.pdf"), "-"],
        capture_output=True, text=True, timeout=30,
    )
    preds = parse_claude(result.stdout)
    c = insert_predictions(conn, model_ids["claude"], preds, match_map)
    print(f"  {c} predictions")
    conn.commit()

    # --- Parse Gemini ---
    print("\n--- Gemini ---")
    text = (DATA_DIR / "gemini.md").read_text(encoding="utf-8")
    preds = parse_gemini(text)
    c = insert_predictions(conn, model_ids["gemini"], preds, match_map)
    print(f"  {c} predictions (both scenarios)")
    conn.commit()

    # --- Parse Doubao ---
    print("\n--- Doubao ---")
    text = (DATA_DIR / "doubao.md").read_text(encoding="utf-8")
    preds, standings = parse_doubao(text)
    c = insert_predictions(conn, model_ids["doubao"], preds, match_map)
    print(f"  {c} predictions")
    sc = insert_standings(conn, model_ids["doubao"], standings)
    print(f"  {sc} group standings")
    conn.commit()

    # --- Summary ---
    print("\n" + "=" * 50)
    print("Ingestion complete!")
    cur = conn.execute("SELECT COUNT(*) FROM predictions")
    print(f"Total predictions: {cur.fetchone()[0]}")
    cur = conn.execute("SELECT m.display_name, COUNT(p.id) "
                       "FROM models m LEFT JOIN predictions p ON m.id = p.model_id "
                       "GROUP BY m.id ORDER BY m.id")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")
    conn.close()


if __name__ == "__main__":
    main()
