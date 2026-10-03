import os
import re
import time
import json
import hmac
import hashlib
import threading
import unicodedata
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from urllib.parse import parse_qsl
from datetime import datetime, timedelta, timezone

import requests
import psycopg2

from flask import Flask, jsonify, request
from flask_cors import CORS


app = Flask(__name__)
CORS(app)


FIVE_DOLLAR_FOOTBALL_API_KEY = os.environ.get(
    "FIVE_DOLLAR_FOOTBALL_API_KEY",
    ""
).strip()

FOOTBALL_TOKEN = os.environ.get(
    "FOOTBALL_DATA_TOKEN",
    ""
).strip()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    ""
).strip()

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()


FIVE_API_URL = "https://api.5dollarfootballapi.com"
FOOTBALL_DATA_URL = "https://api.football-data.org/v4"


LEAGUES = {
    "premier_league": {
        "ids": [4160026622],
        "name": "Premier League",
        "short_name": "АПЛ",
        "country": "England",
        "flag": "🏴",
        "football_data_code": "PL",
    },
    "la_liga": {
        "ids": [4212821298],
        "name": "La Liga",
        "short_name": "Ла Лига",
        "country": "Spain",
        "flag": "🇪🇸",
        "football_data_code": "PD",
    },
    "serie_a": {
        "ids": [3405541143],
        "name": "Serie A",
        "short_name": "Серия А",
        "country": "Italy",
        "flag": "🇮🇹",
        "football_data_code": "SA",
    },
    "bundesliga": {
        "ids": [686337048],
        "name": "Bundesliga",
        "short_name": "Бундеслига",
        "country": "Germany",
        "flag": "🇩🇪",
        "football_data_code": "BL1",
    },
    "ligue_1": {
        "ids": [3614399544],
        "name": "Ligue 1",
        "short_name": "Лига 1",
        "country": "France",
        "flag": "🇫🇷",
        "football_data_code": "FL1",
    },
    "champions_league": {
        "ids": [
            2187079931,
            1318331555,
        ],
        "name": "UEFA Champions League",
        "short_name": "Лига чемпионов",
        "country": "Europe",
        "flag": "🏆",
        "football_data_code": "CL",
    },
    "europa_league": {
        "ids": [
            2629778952,
            2515803737,
        ],
        "name": "UEFA Europa League",
        "short_name": "Лига Европы",
        "country": "Europe",
        "flag": "🟠",
        "football_data_code": "EL",
    },
    "conference_league": {
        "ids": [
            51996766,
            2009834352,
        ],
        "name": "UEFA Conference League",
        "short_name": "Лига конференций",
        "country": "Europe",
        "flag": "🟢",
        "football_data_code": None,
    },
    "championship": {
        "ids": [1161691669],
        "name": "Championship",
        "short_name": "Чемпионшип",
        "country": "England",
        "flag": "🏴",
        "football_data_code": "ELC",
    },
    "eredivisie": {
        "ids": [137325260],
        "name": "Eredivisie",
        "short_name": "Эредивизи",
        "country": "Netherlands",
        "flag": "🇳🇱",
        "football_data_code": "DED",
    },
    "primeira_liga": {
        "ids": [650171110],
        "name": "Primeira Liga",
        "short_name": "Португалия",
        "country": "Portugal",
        "flag": "🇵🇹",
        "football_data_code": "PPL",
    },
    "mls": {
        "ids": [2221499861],
        "name": "Major League Soccer",
        "short_name": "MLS",
        "country": "USA",
        "flag": "🇺🇸",
        "football_data_code": None,
    },
    "saudi_pro_league": {
        "ids": [1796782054],
        "name": "Saudi Pro League",
        "short_name": "Саудовская лига",
        "country": "Saudi Arabia",
        "flag": "🇸🇦",
        "football_data_code": None,
    },
}


DEFAULT_LEAGUES = [
    "premier_league",
    "la_liga",
    "serie_a",
    "bundesliga",
    "ligue_1",
]


LEAGUE_ID_TO_KEY = {}

for league_key, league_data in LEAGUES.items():
    for league_id in league_data["ids"]:
        LEAGUE_ID_TO_KEY[int(league_id)] = league_key


FIXTURES_CACHE_SECONDS = 1800
ODDS_CACHE_SECONDS = 21600
RESULT_CACHE_SECONDS = 300

NOTIFICATION_MINUTES_BEFORE = 30
NOTIFICATION_CHECK_SECONDS = 60

SETTLEMENT_CHECK_SECONDS = 300
FAVORITE_TEAM_SCAN_SECONDS = 300

LIVE_REFRESH_SECONDS = 60
LIVE_PREMATCH_MINUTES = 15
LIVE_POSTMATCH_HOURS = 3
LIVE_MAX_MATCHES_PER_CYCLE = 3
LIVE_CACHE_KEEP_SECONDS = 21600

MAX_FIXTURE_DAYS = 14
SETTLEMENT_AFTER_KICKOFF_MINUTES = 100

FIVE_RATE_LIMIT_REQUESTS = 8
FIVE_RATE_LIMIT_WINDOW_SECONDS = 60
FIVE_RATE_LIMIT_RETRY_SECONDS = 61


TOTAL_POINTS = [
    1.5,
    2.5,
    3.5,
    4.5,
]


league_fixture_cache = {}
fixture_detail_cache = {}
odds_cache = {}
result_cache = {}

live_match_cache = {}
live_last_checked = {}

league_logo_cache = {}
global_logo_cache = {}

database_ready = False
workers_started = False

workers_lock = threading.Lock()

five_rate_lock = threading.Lock()
five_rate_timestamps = deque()


TEAM_NAME_ALIASES = {
    "cologne": "1 fc koln",
    "koln": "1 fc koln",
    "fc koln": "1 fc koln",
    "rennes": "stade rennais",
    "benfica": "sl benfica",
    "sporting lisbon": "sporting cp",
    "porto": "fc porto",
    "braga": "sc braga",
    "salzburg": "red bull salzburg",
    "rb salzburg": "red bull salzburg",
    "sparta prague": "sparta praha",
    "lech": "lech poznan",
    "omonia": "omonia nicosia",
    "celje": "nk celje",
    "hapoel": "hapoel beer sheva",
    "aek": "aek athens",
    "inter milan": "inter",
    "internazionale": "inter",
    "ac milan": "milan",
    "fc barcelona": "barcelona",
    "real madrid cf": "real madrid",
    "atletico de madrid": "atletico madrid",
}


ACHIEVEMENTS = [
    {
        "key": "bets_10",
        "title": "Начало положено",
        "description": "Сделать 10 ставок",
        "target": 10,
        "reward": 200,
    },
    {
        "key": "wins_5",
        "title": "На победной волне",
        "description": "Выиграть 5 ставок",
        "target": 5,
        "reward": 300,
    },
    {
        "key": "level_5",
        "title": "Опытный игрок",
        "description": "Достичь 5 уровня",
        "target": 5,
        "reward": 500,
    },
    {
        "key": "xp_500",
        "title": "500 XP",
        "description": "Набрать 500 XP",
        "target": 500,
        "reward": 400,
    },
    {
        "key": "high_odd_win",
        "title": "Риск оправдан",
        "description": "Выиграть ставку с коэффициентом 3.00+",
        "target": 1,
        "reward": 350,
    },
]


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not found")

    return psycopg2.connect(DATABASE_URL)


def init_database():
    global database_ready

    if database_ready:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id BIGINT PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            balance INTEGER NOT NULL DEFAULT 1000,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_daily_claim TIMESTAMPTZ,
            xp INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,
            fixture_id BIGINT NOT NULL,
            match_name TEXT NOT NULL,
            selection TEXT NOT NULL,
            odd DOUBLE PRECISION NOT NULL,
            amount INTEGER NOT NULL,
            possible INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Активна',
            settled BOOLEAN NOT NULL DEFAULT FALSE,
            score TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            provider TEXT NOT NULL DEFAULT 'five-dollar',
            result_notified BOOLEAN NOT NULL DEFAULT FALSE,
            result_notified_at TIMESTAMPTZ,
            kickoff_at TIMESTAMPTZ
        )
    """)

    cur.execute("""
        ALTER TABLE bets
        ADD COLUMN IF NOT EXISTS
        provider TEXT
        NOT NULL
        DEFAULT 'five-dollar'
    """)

    cur.execute("""
        ALTER TABLE bets
        ADD COLUMN IF NOT EXISTS
        result_notified BOOLEAN
        NOT NULL
        DEFAULT FALSE
    """)

    cur.execute("""
        ALTER TABLE bets
        ADD COLUMN IF NOT EXISTS
        result_notified_at TIMESTAMPTZ
    """)

    cur.execute("""
        ALTER TABLE bets
        ADD COLUMN IF NOT EXISTS
        kickoff_at TIMESTAMPTZ
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS parlays (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,
            amount INTEGER NOT NULL,
            total_odd DOUBLE PRECISION NOT NULL,
            possible INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Активна',
            settled BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            settled_at TIMESTAMPTZ,
            result_notified BOOLEAN NOT NULL DEFAULT FALSE,
            result_notified_at TIMESTAMPTZ
        )
    """)

    cur.execute("""
        ALTER TABLE parlays
        ADD COLUMN IF NOT EXISTS
        result_notified BOOLEAN
        NOT NULL
        DEFAULT FALSE
    """)

    cur.execute("""
        ALTER TABLE parlays
        ADD COLUMN IF NOT EXISTS
        result_notified_at TIMESTAMPTZ
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS parlay_legs (
            id SERIAL PRIMARY KEY,
            parlay_id INTEGER NOT NULL
                REFERENCES parlays(id)
                ON DELETE CASCADE,
            fixture_id BIGINT NOT NULL,
            match_name TEXT NOT NULL,
            selection TEXT NOT NULL,
            odd DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL DEFAULT 'Активна',
            score TEXT,
            provider TEXT NOT NULL DEFAULT 'five-dollar',
            kickoff_at TIMESTAMPTZ
        )
    """)

    cur.execute("""
        ALTER TABLE parlay_legs
        ADD COLUMN IF NOT EXISTS
        provider TEXT
        NOT NULL
        DEFAULT 'five-dollar'
    """)

    cur.execute("""
        ALTER TABLE parlay_legs
        ADD COLUMN IF NOT EXISTS
        kickoff_at TIMESTAMPTZ
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_tasks (
            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,
            task_date DATE NOT NULL,
            login_done BOOLEAN NOT NULL DEFAULT FALSE,
            bets_count INTEGER NOT NULL DEFAULT 0,
            wins_count INTEGER NOT NULL DEFAULT 0,
            login_claimed BOOLEAN NOT NULL DEFAULT FALSE,
            bets_claimed BOOLEAN NOT NULL DEFAULT FALSE,
            win_claimed BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (
                telegram_id,
                task_date
            )
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS achievement_claims (
            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,
            achievement_key TEXT NOT NULL,
            claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (
                telegram_id,
                achievement_key
            )
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS match_favorites (
            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,
            fixture_id BIGINT NOT NULL,
            match_name TEXT NOT NULL,
            kickoff_at TIMESTAMPTZ NOT NULL,
            notifications_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            notification_sent BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (
                telegram_id,
                fixture_id
            )
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorite_teams (
            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,
            team_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (
                telegram_id,
                normalized_name
            )
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorite_team_notifications (
            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,
            fixture_id BIGINT NOT NULL,
            team_name TEXT,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (
                telegram_id,
                fixture_id
            )
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS team_logos (
            league_key TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            team_name TEXT NOT NULL,
            logo_url TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'football-data',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (
                league_key,
                normalized_name
            )
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            reward_coins INTEGER NOT NULL DEFAULT 0,
            reward_xp INTEGER NOT NULL DEFAULT 0,
            max_uses INTEGER,
            uses_count INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_redemptions (
            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,
            code TEXT NOT NULL
                REFERENCES promo_codes(code)
                ON DELETE CASCADE,
            reward_coins INTEGER NOT NULL DEFAULT 0,
            reward_xp INTEGER NOT NULL DEFAULT 0,
            redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (
                telegram_id,
                code
            )
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_bets_user
        ON bets (telegram_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_bets_settlement_due
        ON bets (
            settled,
            status,
            kickoff_at
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_bets_notification
        ON bets (
            settled,
            result_notified
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_parlays_user
        ON parlays (telegram_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_parlay_legs_due
        ON parlay_legs (
            kickoff_at,
            status
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_parlays_notification
        ON parlays (
            settled,
            result_notified
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_favorites_due
        ON match_favorites (
            notifications_enabled,
            notification_sent,
            kickoff_at
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_favorite_teams_name
        ON favorite_teams (
            normalized_name
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_team_logos_name
        ON team_logos (
            normalized_name
        )
    """)

    cur.execute("""
        INSERT INTO promo_codes (
            code,
            reward_coins,
            reward_xp,
            max_uses
        )
        VALUES (
            'START500',
            500,
            0,
            1000
        )
        ON CONFLICT (code)
        DO NOTHING
    """)

    cur.execute("""
        INSERT INTO promo_codes (
            code,
            reward_coins,
            reward_xp,
            max_uses
        )
        VALUES (
            'BETCOIN',
            300,
            50,
            500
        )
        ON CONFLICT (code)
        DO NOTHING
    """)

    conn.commit()

    cur.close()
    conn.close()

    database_ready = True


def normalize_club_name(name):
    value = str(
        name or ""
    ).strip().lower()

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        char
        for char
        in value
        if not unicodedata.combining(char)
    )

    value = value.replace(
        "ß",
        "ss"
    )

    value = re.sub(
        r"[^a-z0-9\s]",
        " ",
        value
    )

    return re.sub(
        r"\s+",
        " ",
        value
    ).strip()


def simplified_club_name(name):
    ignored = {
        "fc",
        "cf",
        "afc",
        "ac",
        "sc",
        "ssc",
        "rc",
        "cd",
        "fk",
        "sk",
        "club",
        "football",
        "futbol",
        "calcio",
        "de",
        "the",
    }

    return " ".join(
        word
        for word
        in normalize_club_name(name).split()
        if word not in ignored
    )


def alias_club_name(name):
    normalized = normalize_club_name(name)
    simplified = simplified_club_name(name)

    return (
        TEAM_NAME_ALIASES.get(normalized)
        or
        TEAM_NAME_ALIASES.get(simplified)
        or
        normalized
    )


def favorite_team_key(name):
    return (
        simplified_club_name(
            alias_club_name(name)
        )
        or
        normalize_club_name(name)
    )


def rebuild_global_logo_cache():
    global global_logo_cache

    result = {}

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                normalized_name,
                team_name,
                logo_url
            FROM team_logos
        """)

        for row in cur.fetchall():
            result[row[0]] = {
                "name": row[1],
                "logo": row[2],
            }

        cur.close()
        conn.close()

    except Exception as error:
        print(
            "Logo cache error:",
            error
        )

    global_logo_cache = result


def find_logo_fast(team_name):
    if not global_logo_cache:
        return ""

    attempts = [
        normalize_club_name(team_name),
        simplified_club_name(team_name),
        alias_club_name(team_name),
        simplified_club_name(
            alias_club_name(team_name)
        ),
    ]

    for attempt in attempts:
        if (
            attempt
            and
            attempt in global_logo_cache
        ):
            return global_logo_cache[
                attempt
            ].get(
                "logo",
                ""
            )

    best_score = 0
    best_logo = ""

    for key, value in global_logo_cache.items():
        key_simple = simplified_club_name(
            key
        )

        if len(key_simple) < 5:
            continue

        for attempt in attempts:
            attempt_simple = simplified_club_name(
                attempt
            )

            if len(attempt_simple) < 5:
                continue

            score = SequenceMatcher(
                None,
                attempt_simple,
                key_simple
            ).ratio()

            if score > best_score:
                best_score = score
                best_logo = value.get(
                    "logo",
                    ""
                )

    if best_score >= 0.86:
        return best_logo

    return ""


def refresh_football_data_logos(
    league_key
):
    config = LEAGUES.get(
        league_key
    )

    if not config:
        return 0

    code = config.get(
        "football_data_code"
    )

    if (
        not code
        or
        not FOOTBALL_TOKEN
    ):
        return 0

    response = requests.get(
        FOOTBALL_DATA_URL
        +
        f"/competitions/{code}/teams",
        headers={
            "X-Auth-Token":
                FOOTBALL_TOKEN
        },
        timeout=20
    )

    if response.status_code != 200:
        return 0

    teams = (
        response.json().get(
            "teams"
        )
        or
        []
    )

    conn = get_db()
    cur = conn.cursor()

    count = 0

    for team in teams:
        logo = (
            team.get(
                "crest"
            )
            or
            ""
        )

        if not logo:
            continue

        for name in [
            team.get("name"),
            team.get("shortName"),
            team.get("tla"),
        ]:
            if not name:
                continue

            normalized = normalize_club_name(
                name
            )

            if not normalized:
                continue

            cur.execute("""
                INSERT INTO team_logos (
                    league_key,
                    normalized_name,
                    team_name,
                    logo_url,
                    source,
                    updated_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    'football-data',
                    NOW()
                )
                ON CONFLICT (
                    league_key,
                    normalized_name
                )
                DO UPDATE SET
                    team_name =
                        EXCLUDED.team_name,
                    logo_url =
                        EXCLUDED.logo_url,
                    updated_at =
                        NOW()
            """, (
                league_key,
                normalized,
                name,
                logo
            ))

            count += 1

    conn.commit()

    cur.close()
    conn.close()

    rebuild_global_logo_cache()

    return count


def verify_telegram_init_data(
    init_data
):
    if (
        not TELEGRAM_BOT_TOKEN
        or
        not init_data
    ):
        return None

    try:
        data = dict(
            parse_qsl(
                init_data,
                keep_blank_values=True
            )
        )

        received_hash = data.pop(
            "hash",
            None
        )

        if not received_hash:
            return None

        check_string = "\n".join(
            f"{key}={value}"
            for key, value
            in sorted(
                data.items()
            )
        )

        secret = hmac.new(
            b"WebAppData",
            TELEGRAM_BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        calculated = hmac.new(
            secret,
            check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            calculated,
            received_hash
        ):
            return None

        auth_date = int(
            data.get(
                "auth_date",
                "0"
            )
        )

        if (
            auth_date <= 0
            or
            int(time.time())
            -
            auth_date
            >
            86400
        ):
            return None

        user = json.loads(
            data.get(
                "user",
                "{}"
            )
        )

        if not user.get(
            "id"
        ):
            return None

        return user

    except Exception:
        return None


def require_telegram_user():
    init_data = request.headers.get(
        "X-Telegram-Init-Data",
        ""
    )

    if not init_data:
        body = request.get_json(
            silent=True
        ) or {}

        init_data = body.get(
            "initData",
            ""
        )

    user = verify_telegram_init_data(
        init_data
    )

    if not user:
        return None, (
            jsonify({
                "success":
                    False,
                "error":
                    "Telegram authentication failed"
            }),
            401
        )

    return user, None


def get_or_create_user(
    tg_user
):
    init_database()

    telegram_id = int(
        tg_user["id"]
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (
            telegram_id,
            first_name,
            username
        )
        VALUES (
            %s,
            %s,
            %s
        )
        ON CONFLICT (
            telegram_id
        )
        DO UPDATE SET
            first_name =
                EXCLUDED.first_name,
            username =
                EXCLUDED.username,
            updated_at =
                NOW()
    """, (
        telegram_id,
        tg_user.get(
            "first_name",
            ""
        ),
        tg_user.get(
            "username",
            ""
        )
    ))

    conn.commit()

    cur.execute("""
        SELECT
            telegram_id,
            first_name,
            username,
            balance,
            last_daily_claim,
            xp
        FROM users
        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    return {
        "telegram_id": row[0],
        "first_name": row[1],
        "username": row[2],
        "balance": row[3],
        "last_daily_claim": row[4],
        "xp": row[5],
    }


def get_user_data(
    telegram_id
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            telegram_id,
            first_name,
            username,
            balance,
            last_daily_claim,
            xp
        FROM users
        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return None

    return {
        "telegram_id": row[0],
        "first_name": row[1],
        "username": row[2],
        "balance": row[3],
        "last_daily_claim": row[4],
        "xp": row[5],
    }


def calculate_level(xp):
    return (
        int(
            xp or 0
        )
        //
        100
        +
        1
    )


def get_league(level):
    if level >= 30:
        return {
            "key": "master",
            "name": "Мастер",
            "icon": "👑",
            "min_level": 30,
            "next_level": None,
        }

    if level >= 20:
        return {
            "key": "diamond",
            "name": "Алмаз",
            "icon": "💎",
            "min_level": 20,
            "next_level": 30,
        }

    if level >= 10:
        return {
            "key": "gold",
            "name": "Золото",
            "icon": "🥇",
            "min_level": 10,
            "next_level": 20,
        }

    if level >= 5:
        return {
            "key": "silver",
            "name": "Серебро",
            "icon": "🥈",
            "min_level": 5,
            "next_level": 10,
        }

    return {
        "key": "bronze",
        "name": "Бронза",
        "icon": "🥉",
        "min_level": 1,
        "next_level": 5,
    }


def xp_info(xp):
    xp = int(
        xp or 0
    )

    level = calculate_level(
        xp
    )

    current = xp % 100

    return {
        "xp": xp,
        "level": level,
        "league": get_league(
            level
        ),
        "current_level_xp": current,
        "xp_to_next_level":
            100 - current,
    }


def add_xp(
    telegram_id,
    amount,
    cursor=None
):
    own_connection = (
        cursor is None
    )

    conn = (
        get_db()
        if own_connection
        else None
    )

    if own_connection:
        cursor = conn.cursor()

    cursor.execute("""
        SELECT xp
        FROM users
        WHERE telegram_id = %s
        FOR UPDATE
    """, (
        telegram_id,
    ))

    row = cursor.fetchone()

    old_xp = int(
        row[0]
        if row
        else 0
    )

    old_level = calculate_level(
        old_xp
    )

    new_xp = (
        old_xp
        +
        int(
            amount
        )
    )

    new_level = calculate_level(
        new_xp
    )

    cursor.execute("""
        UPDATE users
        SET
            xp = %s,
            updated_at = NOW()
        WHERE telegram_id = %s
    """, (
        new_xp,
        telegram_id
    ))

    reward = 0

    for level_number in range(
        old_level + 1,
        new_level + 1
    ):
        level_reward = 100

        if level_number % 5 == 0:
            level_reward += 500

        reward += level_reward

    if reward > 0:
        cursor.execute("""
            UPDATE users
            SET
                balance =
                    balance + %s,
                updated_at =
                    NOW()
            WHERE telegram_id = %s
        """, (
            reward,
            telegram_id
        ))

    if own_connection:
        conn.commit()
        cursor.close()
        conn.close()

    result = xp_info(
        new_xp
    )

    result[
        "level_reward"
    ] = reward

    return result


def task_date():
    return datetime.now(
        timezone.utc
    ).date()


def ensure_daily_tasks(
    telegram_id,
    cursor=None,
    mark_login=False
):
    own = (
        cursor is None
    )

    conn = (
        get_db()
        if own
        else None
    )

    if own:
        cursor = conn.cursor()

    today = task_date()

    cursor.execute("""
        INSERT INTO daily_tasks (
            telegram_id,
            task_date
        )
        VALUES (
            %s,
            %s
        )
        ON CONFLICT (
            telegram_id,
            task_date
        )
        DO NOTHING
    """, (
        telegram_id,
        today
    ))

    if mark_login:
        cursor.execute("""
            UPDATE daily_tasks
            SET login_done = TRUE
            WHERE
                telegram_id = %s
                AND
                task_date = %s
        """, (
            telegram_id,
            today
        ))

    if own:
        conn.commit()
        cursor.close()
        conn.close()


def increment_daily_bet(
    telegram_id,
    cursor
):
    ensure_daily_tasks(
        telegram_id,
        cursor,
        True
    )

    cursor.execute("""
        UPDATE daily_tasks
        SET
            bets_count =
                bets_count + 1
        WHERE
            telegram_id = %s
            AND
            task_date = %s
    """, (
        telegram_id,
        task_date()
    ))


def increment_daily_win(
    telegram_id,
    cursor
):
    ensure_daily_tasks(
        telegram_id,
        cursor,
        True
    )

    cursor.execute("""
        UPDATE daily_tasks
        SET
            wins_count =
                wins_count + 1
        WHERE
            telegram_id = %s
            AND
            task_date = %s
    """, (
        telegram_id,
        task_date()
    ))


def get_daily_tasks(
    telegram_id,
    mark_login=True
):
    conn = get_db()
    cur = conn.cursor()

    ensure_daily_tasks(
        telegram_id,
        cur,
        mark_login
    )

    cur.execute("""
        SELECT
            login_done,
            bets_count,
            wins_count,
            login_claimed,
            bets_claimed,
            win_claimed
        FROM daily_tasks
        WHERE
            telegram_id = %s
            AND
            task_date = %s
    """, (
        telegram_id,
        task_date()
    ))

    row = cur.fetchone()

    conn.commit()

    cur.close()
    conn.close()

    if not row:
        return []

    return [
        {
            "key": "login",
            "title": "Зайти в приложение",
            "description":
                "Открой BetCoin сегодня",
            "progress":
                1 if row[0] else 0,
            "target": 1,
            "completed":
                bool(row[0]),
            "claimed":
                bool(row[3]),
            "reward_type": "xp",
            "reward": 50,
        },
        {
            "key": "bets_3",
            "title": "Сделать 3 ставки",
            "description":
                "Сделай 3 ставки за сегодня",
            "progress":
                min(
                    int(
                        row[1] or 0
                    ),
                    3
                ),
            "target": 3,
            "completed":
                int(
                    row[1] or 0
                )
                >=
                3,
            "claimed":
                bool(row[4]),
            "reward_type":
                "coins",
            "reward": 100,
        },
        {
            "key": "win_1",
            "title":
                "Выиграть 1 ставку",
            "description":
                "Получи один выигрыш сегодня",
            "progress":
                min(
                    int(
                        row[2] or 0
                    ),
                    1
                ),
            "target": 1,
            "completed":
                int(
                    row[2] or 0
                )
                >=
                1,
            "claimed":
                bool(row[5]),
            "reward_type":
                "coins",
            "reward": 150,
        },
    ]


def five_headers():
    return {
        "Authorization":
            "Bearer "
            +
            FIVE_DOLLAR_FOOTBALL_API_KEY,
        "Accept":
            "application/json",
    }


def wait_for_five_rate_slot():
    while True:
        wait_seconds = 0

        with five_rate_lock:
            now = time.monotonic()

            while (
                five_rate_timestamps
                and
                now
                -
                five_rate_timestamps[0]
                >=
                FIVE_RATE_LIMIT_WINDOW_SECONDS
            ):
                five_rate_timestamps.popleft()

            if (
                len(
                    five_rate_timestamps
                )
                <
                FIVE_RATE_LIMIT_REQUESTS
            ):
                five_rate_timestamps.append(
                    now
                )
                return

            wait_seconds = max(
                0.25,
                FIVE_RATE_LIMIT_WINDOW_SECONDS
                -
                (
                    now
                    -
                    five_rate_timestamps[0]
                )
                +
                0.15
            )

        time.sleep(
            wait_seconds
        )


def reset_five_rate_window_after_429():
    with five_rate_lock:
        five_rate_timestamps.clear()

        now = time.monotonic()

        for _ in range(
            FIVE_RATE_LIMIT_REQUESTS
        ):
            five_rate_timestamps.append(
                now
            )


def five_get(
    path,
    params=None,
    attempts=2
):
    if not FIVE_DOLLAR_FOOTBALL_API_KEY:
        raise RuntimeError(
            "FIVE_DOLLAR_FOOTBALL_API_KEY not found"
        )

    last_error = None

    for attempt in range(
        attempts
    ):
        wait_for_five_rate_slot()

        try:
            response = requests.get(
                FIVE_API_URL
                +
                path,
                headers=five_headers(),
                params=params or {},
                timeout=20
            )

        except requests.RequestException as error:
            last_error = str(
                error
            )

            if attempt < attempts - 1:
                time.sleep(
                    2
                )
                continue

            raise

        if response.status_code == 429:
            last_error = (
                "5DollarFootballAPI rate limit"
            )

            reset_five_rate_window_after_429()

            if attempt < attempts - 1:
                retry_after = (
                    response.headers.get(
                        "Retry-After"
                    )
                )

                try:
                    retry_after = float(
                        retry_after
                    )

                except Exception:
                    retry_after = (
                        FIVE_RATE_LIMIT_RETRY_SECONDS
                    )

                time.sleep(
                    max(
                        FIVE_RATE_LIMIT_RETRY_SECONDS,
                        retry_after
                    )
                )

                continue

        if response.status_code != 200:
            try:
                payload = response.json()

            except Exception:
                payload = (
                    response.text[
                        :300
                    ]
                )

            raise RuntimeError(
                f"5DollarFootballAPI HTTP "
                f"{response.status_code}: "
                f"{payload}"
            )

        return response.json()

    raise RuntimeError(
        last_error
        or
        "5DollarFootballAPI request failed"
    )


def parse_match_datetime(
    value
):
    if not value:
        return None

    if isinstance(
        value,
        datetime
    ):
        result = value

    else:
        raw = str(
            value
        ).strip()

        if raw.endswith(
            "Z"
        ):
            raw = (
                raw[:-1]
                +
                "+00:00"
            )

        try:
            result = datetime.fromisoformat(
                raw
            )

        except Exception:
            return None

    if result.tzinfo is None:
        result = result.replace(
            tzinfo=timezone.utc
        )

    return result.astimezone(
        timezone.utc
    )


def first_snapshot(
    market
):
    if not isinstance(
        market,
        dict
    ):
        return None

    return (
        market.get("closing")
        or
        market.get("opening")
        or
        market.get("inplay")
    )


def extract_bookmakers(
    payload
):
    if not payload:
        return []

    if isinstance(
        payload,
        list
    ):
        return payload

    if not isinstance(
        payload,
        dict
    ):
        return []

    if isinstance(
        payload.get(
            "bookmakers"
        ),
        list
    ):
        return payload[
            "bookmakers"
        ]

    data = payload.get(
        "data"
    )

    if (
        isinstance(
            data,
            dict
        )
        and
        isinstance(
            data.get(
                "bookmakers"
            ),
            list
        )
    ):
        return data[
            "bookmakers"
        ]

    if {
        "1x2",
        "asian_handicap",
        "goal_line",
        "goal_line_fixed",
        "btts",
    } & set(
        payload.keys()
    ):
        return [{
            "name": "Bet 365",
            "slug": "bet365",
            "odds": payload,
        }]

    return []


def parse_odds_response(
    payload
):
    result = {
        "odds": None,
        "totals": {},
        "btts": None,
        "handicaps": None,
        "bookmaker": None,
        "available_markets": [],
    }

    bookmakers = extract_bookmakers(
        payload
    )

    if not bookmakers:
        return result

    bookmaker = next(
        (
            item
            for item
            in bookmakers
            if str(
                item.get(
                    "slug",
                    ""
                )
            ).lower()
            ==
            "bet365"
        ),
        bookmakers[0]
    )

    result[
        "bookmaker"
    ] = (
        bookmaker.get(
            "name"
        )
        or
        "Bet 365"
    )

    odds = (
        bookmaker.get(
            "odds"
        )
        or
        {}
    )

    if not isinstance(
        odds,
        dict
    ):
        return result

    result[
        "available_markets"
    ] = list(
        odds.keys()
    )

    snapshot = first_snapshot(
        odds.get(
            "1x2"
        )
    )

    if isinstance(
        snapshot,
        dict
    ):
        result[
            "odds"
        ] = {
            "home":
                snapshot.get(
                    "home"
                ),
            "draw":
                snapshot.get(
                    "draw"
                ),
            "away":
                snapshot.get(
                    "away"
                ),
        }

    snapshot = first_snapshot(
        odds.get(
            "btts"
        )
    )

    if isinstance(
        snapshot,
        dict
    ):
        result[
            "btts"
        ] = {
            "yes":
                snapshot.get(
                    "yes"
                ),
            "no":
                snapshot.get(
                    "no"
                ),
        }

    fixed_lines = (
        odds.get(
            "goal_line_fixed"
        )
        or
        odds.get(
            "goalline_fixed"
        )
        or
        []
    )

    if isinstance(
        fixed_lines,
        dict
    ):
        fixed_lines = (
            fixed_lines.get(
                "lines"
            )
            or
            []
        )

    if isinstance(
        fixed_lines,
        list
    ):
        for item in fixed_lines:
            try:
                line = float(
                    item.get(
                        "line"
                    )
                )

            except Exception:
                continue

            if line not in TOTAL_POINTS:
                continue

            snapshot = first_snapshot(
                item
            )

            if not isinstance(
                snapshot,
                dict
            ):
                continue

            result[
                "totals"
            ][
                str(
                    line
                )
            ] = {
                "over":
                    snapshot.get(
                        "over"
                    ),
                "under":
                    snapshot.get(
                        "under"
                    ),
            }

    snapshot = first_snapshot(
        odds.get(
            "goal_line"
        )
    )

    if isinstance(
        snapshot,
        dict
    ):
        try:
            line = float(
                snapshot.get(
                    "line"
                )
            )

        except Exception:
            line = None

        if (
            line in TOTAL_POINTS
            and
            str(line)
            not in
            result["totals"]
        ):
            result[
                "totals"
            ][
                str(
                    line
                )
            ] = {
                "over":
                    snapshot.get(
                        "over"
                    ),
                "under":
                    snapshot.get(
                        "under"
                    ),
            }

    snapshot = first_snapshot(
        odds.get(
            "asian_handicap"
        )
    )

    if isinstance(
        snapshot,
        dict
    ):
        try:
            home_line = float(
                snapshot.get(
                    "line"
                )
            )

        except Exception:
            home_line = None

        if home_line is not None:
            away_line = (
                -home_line
            )

            home_key = (
                str(
                    home_line
                )
                .rstrip(
                    "0"
                )
                .rstrip(
                    "."
                )
            )

            away_key = (
                str(
                    away_line
                )
                .rstrip(
                    "0"
                )
                .rstrip(
                    "."
                )
            )

            result[
                "handicaps"
            ] = {
                "home": {
                    home_key:
                        snapshot.get(
                            "home"
                        )
                },
                "away": {
                    away_key:
                        snapshot.get(
                            "away"
                        )
                },
                "main_home_line":
                    home_line,
                "main_away_line":
                    away_line,
            }

    return result


def get_league_key_by_id(
    league_id
):
    try:
        return LEAGUE_ID_TO_KEY.get(
            int(
                league_id
            )
        )

    except Exception:
        return None


def make_match_from_item(
    item,
    fallback_league_key=None
):
    teams = (
        item.get(
            "teams"
        )
        or
        {}
    )

    home = (
        teams.get(
            "home"
        )
        or
        {}
    )

    away = (
        teams.get(
            "away"
        )
        or
        {}
    )

    league = (
        item.get(
            "league"
        )
        or
        {}
    )

    league_id = league.get(
        "id"
    )

    league_key = (
        get_league_key_by_id(
            league_id
        )
        or
        fallback_league_key
    )

    league_config = (
        LEAGUES.get(
            league_key
        )
        or
        {}
    )

    home_name = home.get(
        "name",
        "Unknown"
    )

    away_name = away.get(
        "name",
        "Unknown"
    )

    home_logo = (
        home.get(
            "logo"
        )
        or
        find_logo_fast(
            home_name
        )
    )

    away_logo = (
        away.get(
            "logo"
        )
        or
        find_logo_fast(
            away_name
        )
    )

    parsed = parse_odds_response(
        item.get(
            "odds"
        )
    )

    goals = (
        item.get(
            "goals"
        )
        or
        {}
    )

    match = {
        "fixture_id":
            item.get(
                "id"
            ),
        "date":
            item.get(
                "kickoff_utc"
            ),
        "status":
            item.get(
                "status"
            ),
        "status_code":
            item.get(
                "status_code"
            ),
        "league":
            (
                league.get(
                    "name"
                )
                or
                league_config.get(
                    "name"
                )
                or
                "Football"
            ),
        "league_id":
            league_id,
        "league_key":
            league_key,
        "country":
            league_config.get(
                "country",
                ""
            ),
        "league_short_name":
            league_config.get(
                "short_name",
                ""
            ),
        "league_flag":
            league_config.get(
                "flag",
                ""
            ),
        "home":
            home_name,
        "away":
            away_name,
        "home_team_id":
            home.get(
                "id"
            ),
        "away_team_id":
            away.get(
                "id"
            ),
        "home_logo":
            home_logo,
        "away_logo":
            away_logo,
        "home_score":
            goals.get(
                "home"
            ),
        "away_score":
            goals.get(
                "away"
            ),
        "odds":
            parsed.get(
                "odds"
            ),
        "btts":
            parsed.get(
                "btts"
            ),
        "handicaps":
            parsed.get(
                "handicaps"
            ),
        "bookmaker":
            parsed.get(
                "bookmaker"
            ),
        "available_extra_markets":
            parsed.get(
                "available_markets",
                []
            ),
    }

    totals = (
        parsed.get(
            "totals"
        )
        or
        {}
    )

    for line in TOTAL_POINTS:
        field = (
            "total_"
            +
            str(
                line
            ).replace(
                ".",
                "_"
            )
        )

        value = totals.get(
            str(
                line
            ),
            {}
        )

        if (
            value.get(
                "over"
            )
            is not None
            or
            value.get(
                "under"
            )
            is not None
        ):
            match[
                field
            ] = {
                "point":
                    line,
                "over":
                    value.get(
                        "over"
                    ),
                "under":
                    value.get(
                        "under"
                    ),
            }

        else:
            match[
                field
            ] = None

    return match


def fetch_league_id_fixtures(
    league_key,
    league_id,
    start_ts,
    end_ts
):
    data = five_get(
        f"/v1/leagues/"
        f"{league_id}"
        f"/fixtures",
        {
            "status":
                "scheduled",
            "start_time":
                start_ts,
            "end_time":
                end_ts,
            "include":
                "odds",
            "order":
                "asc",
            "page":
                1,
            "per_page":
                50,
        }
    )

    result = []

    for item in (
        data.get(
            "data"
        )
        or
        []
    ):
        try:
            match = make_match_from_item(
                item,
                league_key
            )

            if match.get(
                "fixture_id"
            ):
                result.append(
                    match
                )

        except Exception as error:
            print(
                "Fixture parse error:",
                error
            )

    return result


def load_league_fixtures(
    league_key,
    force=False
):
    if league_key not in LEAGUES:
        raise ValueError(
            "Неизвестная лига"
        )

    cached = league_fixture_cache.get(
        league_key
    )

    if (
        not force
        and
        cached
        and
        time.time()
        -
        cached["time"]
        <
        FIXTURES_CACHE_SECONDS
    ):
        return cached[
            "data"
        ]

    now = datetime.now(
        timezone.utc
    )

    start_ts = int(
        now.timestamp()
    )

    end_ts = int(
        (
            now
            +
            timedelta(
                days=
                    MAX_FIXTURE_DAYS
            )
        ).timestamp()
    )

    league_ids = (
        LEAGUES[
            league_key
        ][
            "ids"
        ]
    )

    result = []

    successful_requests = 0
    request_errors = []

    with ThreadPoolExecutor(
        max_workers=max(
            1,
            min(
                2,
                len(
                    league_ids
                )
            )
        )
    ) as executor:
        futures = [
            executor.submit(
                fetch_league_id_fixtures,
                league_key,
                league_id,
                start_ts,
                end_ts
            )
            for league_id
            in league_ids
        ]

        for future in as_completed(
            futures
        ):
            try:
                loaded = future.result()

                successful_requests += 1

                result.extend(
                    loaded
                )

            except Exception as error:
                request_errors.append(
                    str(
                        error
                    )
                )

                print(
                    "League load error:",
                    league_key,
                    error
                )

    if successful_requests == 0:
        if (
            cached
            and
            cached.get(
                "data"
            ) is not None
        ):
            return cached[
                "data"
            ]

        raise RuntimeError(
            "Не удалось загрузить "
            +
            LEAGUES[
                league_key
            ].get(
                "name",
                league_key
            )
            +
            (
                ": "
                +
                request_errors[0]
                if request_errors
                else ""
            )
        )

    unique = {}

    for match in result:
        fixture_id = int(
            match[
                "fixture_id"
            ]
        )

        unique[
            fixture_id
        ] = match

        fixture_detail_cache[
            str(
                fixture_id
            )
        ] = {
            "time":
                time.time(),
            "data":
                match,
        }

    result = list(
        unique.values()
    )

    result.sort(
        key=lambda match:
            match.get(
                "date"
            )
            or
            ""
    )

    league_fixture_cache[
        league_key
    ] = {
        "time":
            time.time(),
        "data":
            result,
    }

    return result


def load_default_fixtures(
    force=False
):
    result = []

    with ThreadPoolExecutor(
        max_workers=2
    ) as executor:
        future_map = {
            executor.submit(
                load_league_fixtures,
                league_key,
                force
            ):
                league_key
            for league_key
            in DEFAULT_LEAGUES
        }

        for future in as_completed(
            future_map
        ):
            league_key = (
                future_map[
                    future
                ]
            )

            try:
                result.extend(
                    future.result()
                )

            except Exception as error:
                print(
                    "Top5 load error:",
                    league_key,
                    error
                )

    unique = {}

    for match in result:
        unique[
            int(
                match[
                    "fixture_id"
                ]
            )
        ] = match

    result = list(
        unique.values()
    )

    result.sort(
        key=lambda match:
            match.get(
                "date"
            )
            or
            ""
    )

    return result


def get_all_cached_matches():
    unique = {}

    for cache in (
        league_fixture_cache.values()
    ):
        for match in (
            cache.get(
                "data"
            )
            or
            []
        ):
            fixture_id = match.get(
                "fixture_id"
            )

            if fixture_id:
                unique[
                    int(
                        fixture_id
                    )
                ] = match

    return list(
        unique.values()
    )


def find_cached_fixture(
    fixture_id
):
    key = str(
        int(
            fixture_id
        )
    )

    cached = fixture_detail_cache.get(
        key
    )

    if (
        cached
        and
        time.time()
        -
        cached["time"]
        <
        FIXTURES_CACHE_SECONDS
    ):
        return cached[
            "data"
        ]

    return None


def fetch_fixture_odds(
    fixture_id,
    force=False
):
    key = str(
        int(
            fixture_id
        )
    )

    cached = odds_cache.get(
        key
    )

    if (
        not force
        and
        cached
        and
        time.time()
        -
        cached["time"]
        <
        ODDS_CACHE_SECONDS
    ):
        return cached[
            "data"
        ]

    data = five_get(
        f"/v1/fixtures/"
        f"{int(fixture_id)}"
        f"/odds"
    )

    parsed = parse_odds_response(
        data
    )

    odds_cache[
        key
    ] = {
        "time":
            time.time(),
        "data":
            parsed,
    }

    return parsed


def apply_parsed_odds_to_match(
    match,
    parsed
):
    match[
        "odds"
    ] = parsed.get(
        "odds"
    )

    match[
        "btts"
    ] = parsed.get(
        "btts"
    )

    match[
        "handicaps"
    ] = parsed.get(
        "handicaps"
    )

    match[
        "bookmaker"
    ] = parsed.get(
        "bookmaker"
    )

    totals = (
        parsed.get(
            "totals"
        )
        or
        {}
    )

    for line in TOTAL_POINTS:
        field = (
            "total_"
            +
            str(
                line
            ).replace(
                ".",
                "_"
            )
        )

        value = totals.get(
            str(
                line
            ),
            {}
        )

        match[
            field
        ] = (
            {
                "point":
                    line,
                "over":
                    value.get(
                        "over"
                    ),
                "under":
                    value.get(
                        "under"
                    ),
            }
            if (
                value.get(
                    "over"
                )
                is not None
                or
                value.get(
                    "under"
                )
                is not None
            )
            else None
        )

    return match


def get_fixture(
    fixture_id,
    with_odds=True,
    force=False
):
    if not force:
        cached = find_cached_fixture(
            fixture_id
        )

        if cached:
            match = dict(
                cached
            )

            if (
                with_odds
                and
                not match.get(
                    "odds"
                )
            ):
                try:
                    parsed = fetch_fixture_odds(
                        fixture_id
                    )

                    apply_parsed_odds_to_match(
                        match,
                        parsed
                    )

                except Exception:
                    pass

            return match

    data = five_get(
        f"/v1/fixtures/"
        f"{int(fixture_id)}"
    )

    item = (
        data.get(
            "data"
        )
        or
        {}
    )

    match = make_match_from_item(
        item
    )

    if (
        with_odds
        and
        not match.get(
            "odds"
        )
    ):
        try:
            parsed = fetch_fixture_odds(
                fixture_id
            )

            apply_parsed_odds_to_match(
                match,
                parsed
            )

        except Exception:
            pass

    fixture_detail_cache[
        str(
            int(
                fixture_id
            )
        )
    ] = {
        "time":
            time.time(),
        "data":
            match,
    }

    return match


def normalize_line_key(
    line
):
    return (
        str(
            float(
                line
            )
        )
        .rstrip(
            "0"
        )
        .rstrip(
            "."
        )
    )


def match_market_odd(
    match,
    selection
):
    selection = re.sub(
        r"\s+",
        " ",
        str(
            selection
            or
            ""
        ).strip()
    )

    odds = (
        match.get(
            "odds"
        )
        or
        {}
    )

    if selection == "П1":
        return (
            odds.get(
                "home"
            ),
            "П1",
        )

    if selection == "X":
        return (
            odds.get(
                "draw"
            ),
            "X",
        )

    if selection == "П2":
        return (
            odds.get(
                "away"
            ),
            "П2",
        )

    btts = (
        match.get(
            "btts"
        )
        or
        {}
    )

    if selection == "ОЗ Да":
        return (
            btts.get(
                "yes"
            ),
            "ОЗ Да",
        )

    if selection == "ОЗ Нет":
        return (
            btts.get(
                "no"
            ),
            "ОЗ Нет",
        )

    total_match = re.fullmatch(
        r"Т([БМ])\s*([0-9.]+)",
        selection
    )

    if total_match:
        line = float(
            total_match.group(
                2
            )
        )

        field = (
            "total_"
            +
            str(
                line
            ).replace(
                ".",
                "_"
            )
        )

        market = (
            match.get(
                field
            )
            or
            {}
        )

        side = (
            "over"
            if
            total_match.group(
                1
            )
            ==
            "Б"
            else
            "under"
        )

        return (
            market.get(
                side
            ),
            f"Т"
            f"{total_match.group(1)} "
            f"{line}",
        )

    handicap_match = re.fullmatch(
        r"Ф([12])\(([-+]?[0-9.]+)\)",
        selection
    )

    if handicap_match:
        team_number = int(
            handicap_match.group(
                1
            )
        )

        line = float(
            handicap_match.group(
                2
            )
        )

        side = (
            "home"
            if team_number == 1
            else
            "away"
        )

        line_key = normalize_line_key(
            line
        )

        odd = (
            (
                match.get(
                    "handicaps"
                )
                or
                {}
            )
            .get(
                side,
                {}
            )
            .get(
                line_key
            )
        )

        signed = (
            f"+{line_key}"
            if line > 0
            else
            line_key
        )

        return (
            odd,
            f"Ф{team_number}({signed})",
        )

    return (
        None,
        selection,
    )


def resolve_canonical_bet(
    fixture_id,
    selection
):
    match = get_fixture(
        fixture_id,
        True
    )

    kickoff = parse_match_datetime(
        match.get(
            "date"
        )
    )

    if (
        kickoff
        and
        datetime.now(
            timezone.utc
        )
        >=
        kickoff
    ):
        raise ValueError(
            "Матч уже начался. Ставки закрыты"
        )

    odd, canonical = (
        match_market_odd(
            match,
            selection
        )
    )

    if odd is None:
        parsed = fetch_fixture_odds(
            fixture_id,
            True
        )

        temp = dict(
            match
        )

        apply_parsed_odds_to_match(
            temp,
            parsed
        )

        odd, canonical = (
            match_market_odd(
                temp,
                selection
            )
        )

    if odd is None:
        raise ValueError(
            "Этот исход сейчас недоступен"
        )

    odd = round(
        float(
            odd
        ),
        4
    )

    return {
        "fixture_id":
            int(
                fixture_id
            ),
        "match":
            f"{match['home']} — "
            f"{match['away']}",
        "selection":
            canonical,
        "odd":
            odd,
        "provider":
            "five-dollar",
        "kickoff_at":
            kickoff,
    }


def calculate_bet_result(
    selection,
    home_score,
    away_score
):
    total = (
        home_score
        +
        away_score
    )

    if selection == "П1":
        return (
            "win"
            if home_score > away_score
            else
            "loss"
        )

    if selection == "X":
        return (
            "win"
            if home_score == away_score
            else
            "loss"
        )

    if selection == "П2":
        return (
            "win"
            if away_score > home_score
            else
            "loss"
        )

    if selection == "ОЗ Да":
        return (
            "win"
            if home_score > 0
            and
            away_score > 0
            else
            "loss"
        )

    if selection == "ОЗ Нет":
        return (
            "win"
            if home_score == 0
            or
            away_score == 0
            else
            "loss"
        )

    total_match = re.fullmatch(
        r"Т([БМ])\s*([0-9.]+)",
        selection
    )

    if total_match:
        line = float(
            total_match.group(
                2
            )
        )

        if total_match.group(
            1
        ) == "Б":
            if total > line:
                return "win"

            if total < line:
                return "loss"

            return "refund"

        if total < line:
            return "win"

        if total > line:
            return "loss"

        return "refund"

    handicap_match = re.fullmatch(
        r"Ф([12])\(([-+]?[0-9.]+)\)",
        selection
    )

    if handicap_match:
        team = int(
            handicap_match.group(
                1
            )
        )

        handicap = float(
            handicap_match.group(
                2
            )
        )

        if team == 1:
            value = (
                home_score
                +
                handicap
                -
                away_score
            )

        else:
            value = (
                away_score
                +
                handicap
                -
                home_score
            )

        if value > 0:
            return "win"

        if value < 0:
            return "loss"

        return "refund"

    return None


def get_result(
    fixture_id
):
    key = str(
        int(
            fixture_id
        )
    )

    cached = result_cache.get(
        key
    )

    if (
        cached
        and
        time.time()
        -
        cached["time"]
        <
        RESULT_CACHE_SECONDS
    ):
        return cached[
            "data"
        ]

    try:
        data = get_fixture(
            fixture_id,
            False,
            True
        )

        result_cache[
            key
        ] = {
            "time":
                time.time(),
            "data":
                data,
        }

        return data

    except Exception as error:
        print(
            "Result fetch error:",
            fixture_id,
            error
        )

        return None


def settle_user_bets(
    telegram_id
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            fixture_id,
            selection,
            amount,
            possible
        FROM bets
        WHERE
            telegram_id = %s
            AND
            status = 'Активна'
            AND
            settled = FALSE
            AND
            (
                kickoff_at IS NULL
                OR
                kickoff_at <=
                    NOW()
                    -
                    (%s * INTERVAL '1 minute')
            )
    """, (
        telegram_id,
        SETTLEMENT_AFTER_KICKOFF_MINUTES
    ))

    rows = cur.fetchall()

    for row in rows:
        (
            bet_id,
            fixture_id,
            selection,
            amount,
            possible
        ) = row

        match = get_result(
            fixture_id
        )

        if (
            not match
            or
            str(
                match.get(
                    "status",
                    ""
                )
            ).lower()
            !=
            "finished"
        ):
            continue

        home_score = match.get(
            "home_score"
        )

        away_score = match.get(
            "away_score"
        )

        if (
            home_score is None
            or
            away_score is None
        ):
            continue

        result = calculate_bet_result(
            selection,
            int(
                home_score
            ),
            int(
                away_score
            )
        )

        if result == "win":
            status = "Выиграла"
            payout = int(
                possible
            )

        elif result == "refund":
            status = "Возврат"
            payout = int(
                amount
            )

        elif result == "loss":
            status = "Проиграла"
            payout = 0

        else:
            continue

        score = (
            f"{int(home_score)}:"
            f"{int(away_score)}"
        )

        cur.execute("""
            UPDATE bets
            SET
                status = %s,
                settled = TRUE,
                score = %s
            WHERE
                id = %s
                AND
                settled = FALSE
        """, (
            status,
            score,
            bet_id
        ))

        if cur.rowcount == 1:
            if payout > 0:
                cur.execute("""
                    UPDATE users
                    SET
                        balance =
                            balance + %s,
                        updated_at =
                            NOW()
                    WHERE telegram_id = %s
                """, (
                    payout,
                    telegram_id
                ))

            if result == "win":
                add_xp(
                    telegram_id,
                    25,
                    cur
                )

                increment_daily_win(
                    telegram_id,
                    cur
                )

    conn.commit()

    cur.close()
    conn.close()


def settle_user_parlays(
    telegram_id
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            amount
        FROM parlays
        WHERE
            telegram_id = %s
            AND
            status = 'Активна'
            AND
            settled = FALSE
    """, (
        telegram_id,
    ))

    parlays = cur.fetchall()

    for parlay_id, amount in parlays:
        cur.execute("""
            SELECT
                id,
                fixture_id,
                selection,
                odd,
                status,
                kickoff_at
            FROM parlay_legs
            WHERE parlay_id = %s
            ORDER BY id ASC
        """, (
            parlay_id,
        ))

        legs = cur.fetchall()

        any_loss = False
        all_resolved = True
        effective_odd = 1.0

        for leg in legs:
            (
                leg_id,
                fixture_id,
                selection,
                odd,
                leg_status,
                kickoff_at
            ) = leg

            if leg_status == "Проиграла":
                any_loss = True
                continue

            if leg_status == "Выиграла":
                effective_odd *= float(
                    odd
                )
                continue

            if leg_status == "Возврат":
                continue

            if kickoff_at:
                if (
                    datetime.now(
                        timezone.utc
                    )
                    <
                    kickoff_at
                    +
                    timedelta(
                        minutes=
                            SETTLEMENT_AFTER_KICKOFF_MINUTES
                    )
                ):
                    all_resolved = False
                    continue

            match = get_result(
                fixture_id
            )

            if (
                not match
                or
                str(
                    match.get(
                        "status",
                        ""
                    )
                ).lower()
                !=
                "finished"
            ):
                all_resolved = False
                continue

            home_score = match.get(
                "home_score"
            )

            away_score = match.get(
                "away_score"
            )

            if (
                home_score is None
                or
                away_score is None
            ):
                all_resolved = False
                continue

            result = calculate_bet_result(
                selection,
                int(
                    home_score
                ),
                int(
                    away_score
                )
            )

            if result == "win":
                new_status = "Выиграла"

                effective_odd *= float(
                    odd
                )

            elif result == "refund":
                new_status = "Возврат"

            elif result == "loss":
                new_status = "Проиграла"
                any_loss = True

            else:
                all_resolved = False
                continue

            score = (
                f"{int(home_score)}:"
                f"{int(away_score)}"
            )

            cur.execute("""
                UPDATE parlay_legs
                SET
                    status = %s,
                    score = %s
                WHERE id = %s
            """, (
                new_status,
                score,
                leg_id
            ))

        if any_loss:
            cur.execute("""
                UPDATE parlays
                SET
                    status =
                        'Проиграла',
                    settled =
                        TRUE,
                    settled_at =
                        NOW()
                WHERE
                    id = %s
                    AND
                    settled = FALSE
            """, (
                parlay_id,
            ))

            continue

        if not all_resolved:
            continue

        if effective_odd <= 1.000001:
            final_status = "Возврат"
            payout = int(
                amount
            )

        else:
            final_status = "Выиграла"

            payout = int(
                float(
                    amount
                )
                *
                effective_odd
                +
                0.5
            )

        cur.execute("""
            UPDATE parlays
            SET
                status = %s,
                settled = TRUE,
                settled_at = NOW()
            WHERE
                id = %s
                AND
                settled = FALSE
        """, (
            final_status,
            parlay_id
        ))

        if (
            cur.rowcount == 1
            and
            payout > 0
        ):
            cur.execute("""
                UPDATE users
                SET
                    balance =
                        balance + %s,
                    updated_at =
                        NOW()
                WHERE telegram_id = %s
            """, (
                payout,
                telegram_id
            ))

            if final_status == "Выиграла":
                add_xp(
                    telegram_id,
                    40,
                    cur
                )

                increment_daily_win(
                    telegram_id,
                    cur
                )

    conn.commit()

    cur.close()
    conn.close()


def get_user_bets(
    telegram_id
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            fixture_id,
            match_name,
            selection,
            odd,
            amount,
            possible,
            status,
            settled,
            score,
            created_at
        FROM bets
        WHERE telegram_id = %s
        ORDER BY id DESC
    """, (
        telegram_id,
    ))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {
            "id": row[0],
            "fixture_id": row[1],
            "match": row[2],
            "selection": row[3],
            "odd": row[4],
            "amount": row[5],
            "possible": row[6],
            "status": row[7],
            "settled": row[8],
            "score": row[9],
            "created_at":
                row[10].isoformat()
                if row[10]
                else None,
        }
        for row in rows
    ]


def get_user_parlays(
    telegram_id
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            amount,
            total_odd,
            possible,
            status,
            settled,
            created_at,
            settled_at
        FROM parlays
        WHERE telegram_id = %s
        ORDER BY id DESC
    """, (
        telegram_id,
    ))

    rows = cur.fetchall()

    result = []

    for row in rows:
        parlay_id = row[0]

        cur.execute("""
            SELECT
                id,
                fixture_id,
                match_name,
                selection,
                odd,
                status,
                score
            FROM parlay_legs
            WHERE parlay_id = %s
            ORDER BY id ASC
        """, (
            parlay_id,
        ))

        legs = [
            {
                "id": leg[0],
                "fixture_id": leg[1],
                "match": leg[2],
                "selection": leg[3],
                "odd": leg[4],
                "status": leg[5],
                "score": leg[6],
            }
            for leg
            in cur.fetchall()
        ]

        result.append({
            "id": row[0],
            "amount": row[1],
            "total_odd": row[2],
            "possible": row[3],
            "status": row[4],
            "settled": row[5],
            "created_at":
                row[6].isoformat()
                if row[6]
                else None,
            "settled_at":
                row[7].isoformat()
                if row[7]
                else None,
            "legs": legs,
        })

    cur.close()
    conn.close()

    return result


def get_profile_stats(
    telegram_id
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            COUNT(*),
            COUNT(*) FILTER (
                WHERE status = 'Активна'
            ),
            COUNT(*) FILTER (
                WHERE status = 'Выиграла'
            ),
            COUNT(*) FILTER (
                WHERE status = 'Проиграла'
            ),
            COUNT(*) FILTER (
                WHERE status = 'Возврат'
            )
        FROM bets
        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    row = cur.fetchone()

    total = int(
        row[0] or 0
    )

    active = int(
        row[1] or 0
    )

    wins = int(
        row[2] or 0
    )

    losses = int(
        row[3] or 0
    )

    refunds = int(
        row[4] or 0
    )

    win_rate = (
        round(
            wins
            /
            (
                wins
                +
                losses
            )
            *
            100,
            1
        )
        if (
            wins
            +
            losses
            >
            0
        )
        else 0
    )

    cur.execute("""
        SELECT
            COUNT(*),
            COUNT(*) FILTER (
                WHERE status = 'Выиграла'
            ),
            COUNT(*) FILTER (
                WHERE status = 'Проиграла'
            )
        FROM parlays
        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    parlay = cur.fetchone()

    cur.close()
    conn.close()

    return {
        "total_bets":
            total,
        "active_bets":
            active,
        "wins":
            wins,
        "losses":
            losses,
        "refunds":
            refunds,
        "win_rate":
            win_rate,
        "current_win_streak":
            0,
        "best_win_streak":
            0,
        "total_parlays":
            int(
                parlay[0] or 0
            ),
        "parlay_wins":
            int(
                parlay[1] or 0
            ),
        "parlay_losses":
            int(
                parlay[2] or 0
            ),
        "net_profit":
            0,
    }


def get_achievements(
    telegram_id
):
    user = get_user_data(
        telegram_id
    )

    if not user:
        return []

    xp = int(
        user[
            "xp"
        ]
        or 0
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*)
        FROM bets
        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    bets_count = int(
        cur.fetchone()[0]
    )

    cur.execute("""
        SELECT COUNT(*)
        FROM parlays
        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    parlay_count = int(
        cur.fetchone()[0]
    )

    cur.execute("""
        SELECT COUNT(*)
        FROM bets
        WHERE
            telegram_id = %s
            AND
            status = 'Выиграла'
    """, (
        telegram_id,
    ))

    wins = int(
        cur.fetchone()[0]
    )

    cur.execute("""
        SELECT achievement_key
        FROM achievement_claims
        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    claimed = {
        row[0]
        for row
        in cur.fetchall()
    }

    cur.close()
    conn.close()

    values = {
        "bets_10":
            bets_count
            +
            parlay_count,
        "wins_5":
            wins,
        "level_5":
            calculate_level(
                xp
            ),
        "xp_500":
            xp,
        "high_odd_win":
            0,
    }

    result = []

    for achievement in ACHIEVEMENTS:
        progress = values.get(
            achievement[
                "key"
            ],
            0
        )

        result.append({
            **achievement,
            "progress":
                min(
                    progress,
                    achievement[
                        "target"
                    ]
                ),
            "completed":
                progress
                >=
                achievement[
                    "target"
                ],
            "claimed":
                achievement[
                    "key"
                ]
                in
                claimed,
        })

    return result


def get_user_favorites(
    telegram_id
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            fixture_id,
            match_name,
            kickoff_at,
            notifications_enabled,
            notification_sent
        FROM match_favorites
        WHERE
            telegram_id = %s
            AND
            kickoff_at > NOW()
        ORDER BY kickoff_at ASC
    """, (
        telegram_id,
    ))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {
            "fixture_id":
                int(
                    row[0]
                ),
            "match":
                row[1],
            "date":
                row[2].isoformat()
                if row[2]
                else None,
            "notifications_enabled":
                bool(
                    row[3]
                ),
            "notification_sent":
                bool(
                    row[4]
                ),
        }
        for row in rows
    ]


def add_favorite_match(
    telegram_id,
    fixture_id
):
    match = get_fixture(
        fixture_id,
        False
    )

    kickoff = parse_match_datetime(
        match.get(
            "date"
        )
    )

    if not kickoff:
        raise ValueError(
            "Не удалось определить время матча"
        )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO match_favorites (
            telegram_id,
            fixture_id,
            match_name,
            kickoff_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s
        )
        ON CONFLICT (
            telegram_id,
            fixture_id
        )
        DO UPDATE SET
            match_name =
                EXCLUDED.match_name,
            kickoff_at =
                EXCLUDED.kickoff_at,
            notifications_enabled =
                TRUE,
            updated_at =
                NOW()
    """, (
        telegram_id,
        fixture_id,
        f"{match['home']} — "
        f"{match['away']}",
        kickoff
    ))

    conn.commit()

    cur.close()
    conn.close()


def remove_favorite_match(
    telegram_id,
    fixture_id
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM match_favorites
        WHERE
            telegram_id = %s
            AND
            fixture_id = %s
    """, (
        telegram_id,
        fixture_id
    ))

    conn.commit()

    cur.close()
    conn.close()


def get_user_favorite_teams(
    telegram_id
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT team_name
        FROM favorite_teams
        WHERE telegram_id = %s
        ORDER BY created_at ASC
    """, (
        telegram_id,
    ))

    result = [
        row[0]
        for row
        in cur.fetchall()
    ]

    cur.close()
    conn.close()

    return result


def add_favorite_team(
    telegram_id,
    team_name
):
    key = favorite_team_key(
        team_name
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO favorite_teams (
            telegram_id,
            team_name,
            normalized_name
        )
        VALUES (
            %s,
            %s,
            %s
        )
        ON CONFLICT (
            telegram_id,
            normalized_name
        )
        DO UPDATE SET
            team_name =
                EXCLUDED.team_name
    """, (
        telegram_id,
        team_name,
        key
    ))

    conn.commit()

    cur.close()
    conn.close()


def remove_favorite_team(
    telegram_id,
    team_name
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM favorite_teams
        WHERE
            telegram_id = %s
            AND
            normalized_name = %s
    """, (
        telegram_id,
        favorite_team_key(
            team_name
        )
    ))

    conn.commit()

    cur.close()
    conn.close()


def send_telegram_message(
    telegram_id,
    text
):
    response = requests.post(
        "https://api.telegram.org/bot"
        +
        TELEGRAM_BOT_TOKEN
        +
        "/sendMessage",
        json={
            "chat_id":
                int(
                    telegram_id
                ),
            "text":
                str(
                    text
                ),
        },
        timeout=10
    )

    data = response.json()

    if not data.get(
        "ok"
    ):
        raise RuntimeError(
            str(
                data
            )
        )


def process_result_notifications():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            telegram_id,
            match_name,
            selection,
            amount,
            possible,
            status,
            score
        FROM bets
        WHERE
            settled = TRUE
            AND
            result_notified = FALSE
        ORDER BY id ASC
        LIMIT 50
    """)

    singles = cur.fetchall()

    for row in singles:
        (
            bet_id,
            telegram_id,
            match_name,
            selection,
            amount,
            possible,
            status,
            score
        ) = row

        if status == "Выиграла":
            message = (
                "✅ Ставка выиграла!\n\n"
                f"⚽ {match_name}\n"
                f"🎯 {selection}\n"
                f"🏁 Счёт: {score}\n"
                f"🪙 +{possible} монет"
            )

        elif status == "Проиграла":
            message = (
                "❌ Ставка проиграла\n\n"
                f"⚽ {match_name}\n"
                f"🎯 {selection}\n"
                f"🏁 Счёт: {score}"
            )

        else:
            message = (
                "↩️ Возврат ставки\n\n"
                f"⚽ {match_name}\n"
                f"🪙 +{amount} монет"
            )

        try:
            send_telegram_message(
                telegram_id,
                message
            )

            cur.execute("""
                UPDATE bets
                SET
                    result_notified = TRUE,
                    result_notified_at = NOW()
                WHERE id = %s
            """, (
                bet_id,
            ))

        except Exception as error:
            print(
                "Bet notification error:",
                error
            )

    cur.execute("""
        SELECT
            id,
            telegram_id,
            amount,
            possible,
            total_odd,
            status
        FROM parlays
        WHERE
            settled = TRUE
            AND
            result_notified = FALSE
        ORDER BY id ASC
        LIMIT 50
    """)

    parlay_rows = cur.fetchall()

    for row in parlay_rows:
        (
            parlay_id,
            telegram_id,
            amount,
            possible,
            total_odd,
            status
        ) = row

        if status == "Выиграла":
            message = (
                "✅ Экспресс выиграл!\n\n"
                f"🧾 Экспресс #{parlay_id}\n"
                f"📈 Кэф: {total_odd:.2f}\n"
                f"🪙 +{possible} монет"
            )

        elif status == "Проиграла":
            message = (
                "❌ Экспресс проиграл\n\n"
                f"🧾 Экспресс #{parlay_id}"
            )

        else:
            message = (
                "↩️ Возврат экспресса\n\n"
                f"🧾 Экспресс #{parlay_id}\n"
                f"🪙 +{amount} монет"
            )

        try:
            send_telegram_message(
                telegram_id,
                message
            )

            cur.execute("""
                UPDATE parlays
                SET
                    result_notified = TRUE,
                    result_notified_at = NOW()
                WHERE id = %s
            """, (
                parlay_id,
            ))

        except Exception as error:
            print(
                "Parlay notification error:",
                error
            )

    conn.commit()

    cur.close()
    conn.close()


def process_match_notifications():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            telegram_id,
            fixture_id,
            match_name,
            kickoff_at
        FROM match_favorites
        WHERE
            notifications_enabled = TRUE
            AND
            notification_sent = FALSE
            AND
            kickoff_at > NOW()
            AND
            kickoff_at <=
                NOW()
                +
                (%s * INTERVAL '1 minute')
        ORDER BY kickoff_at ASC
        LIMIT 50
    """, (
        NOTIFICATION_MINUTES_BEFORE,
    ))

    rows = cur.fetchall()

    for row in rows:
        (
            telegram_id,
            fixture_id,
            match_name,
            kickoff_at
        ) = row

        minutes = max(
            1,
            round(
                (
                    kickoff_at
                    -
                    datetime.now(
                        timezone.utc
                    )
                ).total_seconds()
                /
                60
            )
        )

        try:
            send_telegram_message(
                telegram_id,
                (
                    "⏰ Скоро матч!\n\n"
                    f"⚽ {match_name}\n"
                    f"🕒 Начало примерно "
                    f"через {minutes} мин."
                )
            )

            cur.execute("""
                UPDATE match_favorites
                SET
                    notification_sent = TRUE,
                    updated_at = NOW()
                WHERE
                    telegram_id = %s
                    AND
                    fixture_id = %s
            """, (
                telegram_id,
                fixture_id
            ))

        except Exception as error:
            print(
                "Match notification error:",
                error
            )

    conn.commit()

    cur.close()
    conn.close()


def process_favorite_team_notifications():
    matches = get_all_cached_matches()

    if not matches:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            telegram_id,
            team_name,
            normalized_name
        FROM favorite_teams
    """)

    favorite_rows = cur.fetchall()

    now = datetime.now(
        timezone.utc
    )

    for match in matches:
        kickoff = parse_match_datetime(
            match.get(
                "date"
            )
        )

        if not kickoff:
            continue

        seconds = (
            kickoff
            -
            now
        ).total_seconds()

        if (
            seconds <= 0
            or
            seconds
            >
            NOTIFICATION_MINUTES_BEFORE
            *
            60
        ):
            continue

        home_key = favorite_team_key(
            match.get(
                "home"
            )
        )

        away_key = favorite_team_key(
            match.get(
                "away"
            )
        )

        fixture_id = int(
            match[
                "fixture_id"
            ]
        )

        for (
            telegram_id,
            team_name,
            normalized_name
        ) in favorite_rows:
            if normalized_name not in {
                home_key,
                away_key
            }:
                continue

            cur.execute("""
                SELECT 1
                FROM match_favorites
                WHERE
                    telegram_id = %s
                    AND
                    fixture_id = %s
            """, (
                telegram_id,
                fixture_id
            ))

            if cur.fetchone():
                continue

            cur.execute("""
                INSERT INTO favorite_team_notifications (
                    telegram_id,
                    fixture_id,
                    team_name
                )
                VALUES (
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT DO NOTHING
                RETURNING fixture_id
            """, (
                telegram_id,
                fixture_id,
                team_name
            ))

            if not cur.fetchone():
                continue

            try:
                send_telegram_message(
                    telegram_id,
                    (
                        "⭐ Скоро играет "
                        "твоя любимая команда!\n\n"
                        f"⚽ {match['home']} — "
                        f"{match['away']}\n"
                        f"🕒 Начало примерно "
                        f"через "
                        f"{max(1, round(seconds / 60))} мин."
                    )
                )

            except Exception:
                cur.execute("""
                    DELETE FROM
                    favorite_team_notifications
                    WHERE
                        telegram_id = %s
                        AND
                        fixture_id = %s
                """, (
                    telegram_id,
                    fixture_id
                ))

    conn.commit()

    cur.close()
    conn.close()


def get_users_with_due_bets():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT telegram_id
        FROM (
            SELECT telegram_id
            FROM bets
            WHERE
                settled = FALSE
                AND
                status = 'Активна'
                AND
                (
                    kickoff_at IS NULL
                    OR
                    kickoff_at <=
                        NOW()
                        -
                        (%s * INTERVAL '1 minute')
                )

            UNION

            SELECT p.telegram_id
            FROM parlays p
            JOIN parlay_legs l
                ON l.parlay_id = p.id
            WHERE
                p.settled = FALSE
                AND
                p.status = 'Активна'
                AND
                l.status = 'Активна'
                AND
                (
                    l.kickoff_at IS NULL
                    OR
                    l.kickoff_at <=
                        NOW()
                        -
                        (%s * INTERVAL '1 minute')
                )
        ) due
        LIMIT 50
    """, (
        SETTLEMENT_AFTER_KICKOFF_MINUTES,
        SETTLEMENT_AFTER_KICKOFF_MINUTES
    ))

    users = [
        int(
            row[0]
        )
        for row
        in cur.fetchall()
    ]

    cur.close()
    conn.close()

    return users


def settlement_worker():
    time.sleep(
        15
    )

    while True:
        try:
            users = (
                get_users_with_due_bets()
            )

            for telegram_id in users:
                settle_user_bets(
                    telegram_id
                )

                settle_user_parlays(
                    telegram_id
                )

            process_result_notifications()

        except Exception as error:
            print(
                "Settlement worker error:",
                error
            )

        time.sleep(
            SETTLEMENT_CHECK_SECONDS
        )


def notification_worker():
    time.sleep(
        10
    )

    while True:
        try:
            process_match_notifications()

        except Exception as error:
            print(
                "Notification worker error:",
                error
            )

        time.sleep(
            NOTIFICATION_CHECK_SECONDS
        )


def favorite_team_worker():
    time.sleep(
        30
    )

    while True:
        try:
            process_favorite_team_notifications()

        except Exception as error:
            print(
                "Favorite team worker error:",
                error
            )

        time.sleep(
            FAVORITE_TEAM_SCAN_SECONDS
        )


def is_finished_status(
    status
):
    value = (
        str(
            status
            or
            ""
        )
        .strip()
        .lower()
        .replace(
            "-",
            "_"
        )
        .replace(
            " ",
            "_"
        )
    )

    return value in {
        "finished",
        "ft",
        "ended",
        "full_time",
        "fulltime",
    }


def update_cached_match_snapshot(
    fresh
):
    if (
        not fresh
        or
        not fresh.get(
            "fixture_id"
        )
    ):
        return

    fixture_id = int(
        fresh[
            "fixture_id"
        ]
    )

    fields = [
        "status",
        "status_code",
        "home_score",
        "away_score",
        "date",
        "home",
        "away",
        "home_logo",
        "away_logo",
    ]

    for cache in (
        league_fixture_cache.values()
    ):
        for match in (
            cache.get(
                "data"
            )
            or
            []
        ):
            try:
                same = (
                    int(
                        match.get(
                            "fixture_id"
                        )
                    )
                    ==
                    fixture_id
                )

            except Exception:
                same = False

            if not same:
                continue

            for field in fields:
                if field in fresh:
                    match[
                        field
                    ] = fresh.get(
                        field
                    )

    fixture_detail_cache[
        str(
            fixture_id
        )
    ] = {
        "time":
            time.time(),
        "data":
            fresh,
    }


def get_live_candidates():
    now = datetime.now(
        timezone.utc
    )

    earliest = (
        now
        -
        timedelta(
            hours=
                LIVE_POSTMATCH_HOURS
        )
    )

    latest = (
        now
        +
        timedelta(
            minutes=
                LIVE_PREMATCH_MINUTES
        )
    )

    candidates = []

    for match in get_all_cached_matches():
        kickoff = parse_match_datetime(
            match.get(
                "date"
            )
        )

        if not kickoff:
            continue

        if (
            kickoff < earliest
            or
            kickoff > latest
        ):
            continue

        fixture_id = match.get(
            "fixture_id"
        )

        if not fixture_id:
            continue

        cached_live = live_match_cache.get(
            str(
                int(
                    fixture_id
                )
            )
        )

        if (
            cached_live
            and
            is_finished_status(
                cached_live.get(
                    "status"
                )
            )
        ):
            continue

        candidates.append(
            match
        )

    candidates.sort(
        key=lambda match:
            live_last_checked.get(
                str(
                    int(
                        match.get(
                            "fixture_id"
                        )
                    )
                ),
                0
            )
    )

    return candidates


def refresh_live_matches_once():
    now_ts = time.time()

    candidates = (
        get_live_candidates()[
            :LIVE_MAX_MATCHES_PER_CYCLE
        ]
    )

    for match in candidates:
        fixture_id = int(
            match[
                "fixture_id"
            ]
        )

        key = str(
            fixture_id
        )

        try:
            fresh = get_fixture(
                fixture_id,
                False,
                True
            )

            live_last_checked[
                key
            ] = time.time()

            update_cached_match_snapshot(
                fresh
            )

            live_match_cache[
                key
            ] = {
                "fixture_id":
                    fixture_id,
                "date":
                    fresh.get(
                        "date"
                    ),
                "home":
                    fresh.get(
                        "home"
                    ),
                "away":
                    fresh.get(
                        "away"
                    ),
                "home_logo":
                    fresh.get(
                        "home_logo"
                    ),
                "away_logo":
                    fresh.get(
                        "away_logo"
                    ),
                "status":
                    fresh.get(
                        "status"
                    ),
                "status_code":
                    fresh.get(
                        "status_code"
                    ),
                "home_score":
                    fresh.get(
                        "home_score"
                    ),
                "away_score":
                    fresh.get(
                        "away_score"
                    ),
                "league":
                    fresh.get(
                        "league"
                    ),
                "league_key":
                    fresh.get(
                        "league_key"
                    ),
                "updated_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
            }

        except Exception as error:
            live_last_checked[
                key
            ] = time.time()

            print(
                "Live refresh error:",
                fixture_id,
                error
            )

    stale = []

    for key, item in (
        live_match_cache.items()
    ):
        updated = parse_match_datetime(
            item.get(
                "updated_at"
            )
        )

        if (
            updated
            and
            now_ts
            -
            updated.timestamp()
            >
            LIVE_CACHE_KEEP_SECONDS
        ):
            stale.append(
                key
            )

    for key in stale:
        live_match_cache.pop(
            key,
            None
        )

        live_last_checked.pop(
            key,
            None
        )


def live_worker():
    time.sleep(
        45
    )

    while True:
        try:
            refresh_live_matches_once()

        except Exception as error:
            print(
                "Live worker error:",
                error
            )

        time.sleep(
            LIVE_REFRESH_SECONDS
        )


def start_workers():
    global workers_started

    with workers_lock:
        if workers_started:
            return

        workers_started = True

        threading.Thread(
            target=
                settlement_worker,
            daemon=
                True,
            name=
                "betcoin-settlement"
        ).start()

        threading.Thread(
            target=
                notification_worker,
            daemon=
                True,
            name=
                "betcoin-match-notifications"
        ).start()

        threading.Thread(
            target=
                favorite_team_worker,
            daemon=
                True,
            name=
                "betcoin-team-notifications"
        ).start()

        threading.Thread(
            target=
                live_worker,
            daemon=
                True,
            name=
                "betcoin-live"
        ).start()


def redeem_promo_code(
    telegram_id,
    raw_code
):
    code = str(
        raw_code
        or
        ""
    ).strip().upper()

    if not code:
        raise ValueError(
            "Введите промокод"
        )

    if (
        len(code) > 32
        or
        not re.fullmatch(
            r"[A-Z0-9_-]+",
            code
        )
    ):
        raise ValueError(
            "Неверный формат промокода"
        )

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT
                reward_coins,
                reward_xp,
                max_uses,
                uses_count,
                active,
                expires_at
            FROM promo_codes
            WHERE code = %s
            FOR UPDATE
        """, (
            code,
        ))

        promo = cur.fetchone()

        if not promo:
            raise ValueError(
                "Такого промокода нет"
            )

        (
            reward_coins,
            reward_xp,
            max_uses,
            uses_count,
            active,
            expires_at
        ) = promo

        if not active:
            raise ValueError(
                "Промокод больше не действует"
            )

        now = datetime.now(
            timezone.utc
        )

        if (
            expires_at
            and
            now >= expires_at
        ):
            raise ValueError(
                "Срок промокода закончился"
            )

        if (
            max_uses is not None
            and
            int(
                uses_count or 0
            )
            >=
            int(
                max_uses
            )
        ):
            raise ValueError(
                "Лимит активаций промокода закончился"
            )

        cur.execute("""
            INSERT INTO promo_redemptions (
                telegram_id,
                code,
                reward_coins,
                reward_xp
            )
            VALUES (
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (
                telegram_id,
                code
            )
            DO NOTHING
            RETURNING code
        """, (
            telegram_id,
            code,
            int(
                reward_coins or 0
            ),
            int(
                reward_xp or 0
            )
        ))

        if not cur.fetchone():
            raise ValueError(
                "Ты уже использовал этот промокод"
            )

        reward_coins = int(
            reward_coins or 0
        )

        reward_xp = int(
            reward_xp or 0
        )

        if reward_coins > 0:
            cur.execute("""
                UPDATE users
                SET
                    balance =
                        balance + %s,
                    updated_at =
                        NOW()
                WHERE telegram_id = %s
            """, (
                reward_coins,
                telegram_id
            ))

        if reward_xp > 0:
            add_xp(
                telegram_id,
                reward_xp,
                cur
            )

        cur.execute("""
            UPDATE promo_codes
            SET
                uses_count =
                    uses_count + 1
            WHERE code = %s
        """, (
            code,
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()

    user = get_user_data(
        telegram_id
    )

    return {
        "code":
            code,
        "reward_coins":
            reward_coins,
        "reward_xp":
            reward_xp,
        "balance":
            int(
                user[
                    "balance"
                ]
            ),
        "xp":
            int(
                user[
                    "xp"
                ]
                or
                0
            ),
    }


@app.route("/")
def root():
    return jsonify({
        "status":
            "ok",
        "message":
            "BetCoin optimized server is working",
        "provider":
            "5DollarFootballAPI Pro",
        "optimized":
            True,
        "parallel_top5":
            True,
        "external_logo_lookup_on_match_load":
            False,
        "session_settlement_wait":
            False,
        "automatic_settlement":
            True,
        "favorite_team_notifications":
            True,
        "result_notifications":
            True,
        "live_cache":
            True,
        "live_refresh_seconds":
            LIVE_REFRESH_SECONDS,
        "live_max_matches_per_cycle":
            LIVE_MAX_MATCHES_PER_CYCLE,
    })


@app.route("/api/leagues")
def api_leagues():
    return jsonify({
        "success":
            True,
        "leagues": [
            {
                "key":
                    key,
                "name":
                    value[
                        "name"
                    ],
                "short_name":
                    value[
                        "short_name"
                    ],
                "country":
                    value[
                        "country"
                    ],
                "flag":
                    value[
                        "flag"
                    ],
            }
            for key, value
            in LEAGUES.items()
        ]
    })


@app.route("/api/matches")
def api_matches():
    try:
        league_key = str(
            request.args.get(
                "league",
                ""
            )
            or
            ""
        ).strip()

        force = (
            request.args.get(
                "refresh"
            )
            ==
            "1"
        )

        start = time.time()

        if (
            not league_key
            or
            league_key == "top5"
        ):
            fixtures = (
                load_default_fixtures(
                    force
                )
            )

        elif league_key in LEAGUES:
            fixtures = (
                load_league_fixtures(
                    league_key,
                    force
                )
            )

        else:
            return jsonify({
                "success":
                    False,
                "error":
                    "Неизвестная лига"
            }), 400

        return jsonify({
            "success":
                True,
            "count":
                len(
                    fixtures
                ),
            "load_ms":
                int(
                    (
                        time.time()
                        -
                        start
                    )
                    *
                    1000
                ),
            "matches":
                fixtures,
        })

    except Exception as error:
        return jsonify({
            "success":
                False,
            "error":
                str(
                    error
                )
        }), 500


@app.route("/api/live")
def api_live():
    try:
        items = list(
            live_match_cache.values()
        )

        items.sort(
            key=lambda item:
                item.get(
                    "date"
                )
                or
                ""
        )

        return jsonify({
            "success":
                True,
            "count":
                len(
                    items
                ),
            "refresh_seconds":
                LIVE_REFRESH_SECONDS,
            "matches":
                items,
        })

    except Exception as error:
        return jsonify({
            "success":
                False,
            "error":
                str(
                    error
                )
        }), 500


@app.route(
    "/api/match/<int:fixture_id>"
)
def api_match(
    fixture_id
):
    try:
        match = get_fixture(
            fixture_id,
            False
        )

        try:
            parsed = fetch_fixture_odds(
                fixture_id
            )

            apply_parsed_odds_to_match(
                match,
                parsed
            )

        except Exception as odds_error:
            print(
                "Match detail odds error:",
                fixture_id,
                odds_error
            )

        return jsonify({
            "success":
                True,
            **match,
        })

    except Exception as error:
        return jsonify({
            "success":
                False,
            "error":
                str(
                    error
                )
        }), 500


@app.route(
    "/api/session",
    methods=[
        "POST"
    ]
)
def api_session():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    try:
        user = get_or_create_user(
            tg_user
        )

        telegram_id = (
            user[
                "telegram_id"
            ]
        )

        last_claim = user.get(
            "last_daily_claim"
        )

        available = True
        seconds_left = 0
        next_claim = None

        if last_claim:
            next_claim = (
                last_claim
                +
                timedelta(
                    hours=24
                )
            )

            now = datetime.now(
                timezone.utc
            )

            if now < next_claim:
                available = False

                seconds_left = int(
                    (
                        next_claim
                        -
                        now
                    ).total_seconds()
                )

        return jsonify({
            "success":
                True,
            "user": {
                "telegram_id":
                    telegram_id,
                "first_name":
                    user[
                        "first_name"
                    ],
                "username":
                    user[
                        "username"
                    ],
            },
            "balance":
                int(
                    user[
                        "balance"
                    ]
                ),
            **xp_info(
                user[
                    "xp"
                ]
            ),
            "bets":
                get_user_bets(
                    telegram_id
                ),
            "parlays":
                get_user_parlays(
                    telegram_id
                ),
            "favorites":
                get_user_favorites(
                    telegram_id
                ),
            "favorite_teams":
                get_user_favorite_teams(
                    telegram_id
                ),
            "tasks":
                get_daily_tasks(
                    telegram_id,
                    True
                ),
            "achievements":
                get_achievements(
                    telegram_id
                ),
            "stats":
                get_profile_stats(
                    telegram_id
                ),
            "leaderboard": {
                "my_rank":
                    None
            },
            "daily_reward": {
                "amount":
                    300,
                "available":
                    available,
                "seconds_left":
                    max(
                        seconds_left,
                        0
                    ),
                "next_claim":
                    next_claim.isoformat()
                    if next_claim
                    else None,
            },
        })

    except Exception as error:
        return jsonify({
            "success":
                False,
            "error":
                str(
                    error
                )
        }), 500


@app.route(
    "/api/bets",
    methods=[
        "POST"
    ]
)
def api_bets():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    body = request.get_json(
        silent=True
    ) or {}

    try:
        fixture_id = int(
            body.get(
                "fixture_id"
            )
        )

        amount = int(
            body.get(
                "amount"
            )
        )

        selection = str(
            body.get(
                "selection",
                ""
            )
        ).strip()

        if amount <= 0:
            raise ValueError(
                "Неправильная сумма"
            )

        canonical = resolve_canonical_bet(
            fixture_id,
            selection
        )

        user = get_or_create_user(
            tg_user
        )

        telegram_id = (
            user[
                "telegram_id"
            ]
        )

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT balance
            FROM users
            WHERE telegram_id = %s
            FOR UPDATE
        """, (
            telegram_id,
        ))

        current_balance = int(
            cur.fetchone()[0]
        )

        if amount > current_balance:
            conn.rollback()

            cur.close()
            conn.close()

            return jsonify({
                "success":
                    False,
                "error":
                    "Недостаточно монет"
            }), 400

        odd = canonical[
            "odd"
        ]

        possible = int(
            amount
            *
            odd
            +
            0.5
        )

        cur.execute("""
            UPDATE users
            SET
                balance =
                    balance - %s,
                updated_at =
                    NOW()
            WHERE telegram_id = %s
        """, (
            amount,
            telegram_id
        ))

        cur.execute("""
            INSERT INTO bets (
                telegram_id,
                fixture_id,
                match_name,
                selection,
                odd,
                amount,
                possible,
                provider,
                kickoff_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'five-dollar',
                %s
            )
            RETURNING id
        """, (
            telegram_id,
            fixture_id,
            canonical[
                "match"
            ],
            canonical[
                "selection"
            ],
            odd,
            amount,
            possible,
            canonical[
                "kickoff_at"
            ]
        ))

        bet_id = cur.fetchone()[0]

        ensure_daily_tasks(
            telegram_id,
            cur,
            True
        )

        increment_daily_bet(
            telegram_id,
            cur
        )

        add_xp(
            telegram_id,
            10,
            cur
        )

        conn.commit()

        cur.close()
        conn.close()

        fresh = get_user_data(
            telegram_id
        )

        return jsonify({
            "success":
                True,
            "bet_id":
                bet_id,
            "balance":
                int(
                    fresh[
                        "balance"
                    ]
                ),
            "possible":
                possible,
            "bets":
                get_user_bets(
                    telegram_id
                ),
        })

    except ValueError as error:
        return jsonify({
            "success":
                False,
            "error":
                str(
                    error
                )
        }), 400

    except Exception as error:
        return jsonify({
            "success":
                False,
            "error":
                str(
                    error
                )
        }), 500


@app.route(
    "/api/parlays",
    methods=[
        "POST"
    ]
)
def api_parlays():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    body = request.get_json(
        silent=True
    ) or {}

    try:
        amount = int(
            body.get(
                "amount"
            )
        )

        legs = body.get(
            "legs",
            []
        )

        if (
            amount <= 0
            or
            not isinstance(
                legs,
                list
            )
            or
            len(
                legs
            )
            <
            2
        ):
            raise ValueError(
                "В экспрессе нужно минимум 2 события"
            )

        if len(
            legs
        ) > 15:
            raise ValueError(
                "Максимум 15 событий"
            )

        validated = []

        def validate_leg(
            leg
        ):
            return resolve_canonical_bet(
                int(
                    leg[
                        "fixture_id"
                    ]
                ),
                str(
                    leg[
                        "selection"
                    ]
                )
            )

        fixture_ids = [
            int(
                leg[
                    "fixture_id"
                ]
            )
            for leg
            in legs
        ]

        if len(
            fixture_ids
        ) != len(
            set(
                fixture_ids
            )
        ):
            raise ValueError(
                "Нельзя добавить два исхода одного матча"
            )

        with ThreadPoolExecutor(
            max_workers=min(
                6,
                len(
                    legs
                )
            )
        ) as executor:
            futures = [
                executor.submit(
                    validate_leg,
                    leg
                )
                for leg
                in legs
            ]

            for future in futures:
                validated.append(
                    future.result()
                )

        total_odd = 1.0

        for leg in validated:
            total_odd *= float(
                leg[
                    "odd"
                ]
            )

        total_odd = round(
            total_odd,
            4
        )

        possible = int(
            amount
            *
            total_odd
            +
            0.5
        )

        user = get_or_create_user(
            tg_user
        )

        telegram_id = (
            user[
                "telegram_id"
            ]
        )

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT balance
            FROM users
            WHERE telegram_id = %s
            FOR UPDATE
        """, (
            telegram_id,
        ))

        current_balance = int(
            cur.fetchone()[0]
        )

        if amount > current_balance:
            conn.rollback()

            cur.close()
            conn.close()

            return jsonify({
                "success":
                    False,
                "error":
                    "Недостаточно монет"
            }), 400

        cur.execute("""
            UPDATE users
            SET
                balance =
                    balance - %s,
                updated_at =
                    NOW()
            WHERE telegram_id = %s
        """, (
            amount,
            telegram_id
        ))

        cur.execute("""
            INSERT INTO parlays (
                telegram_id,
                amount,
                total_odd,
                possible
            )
            VALUES (
                %s,
                %s,
                %s,
                %s
            )
            RETURNING id
        """, (
            telegram_id,
            amount,
            total_odd,
            possible
        ))

        parlay_id = cur.fetchone()[0]

        for leg in validated:
            cur.execute("""
                INSERT INTO parlay_legs (
                    parlay_id,
                    fixture_id,
                    match_name,
                    selection,
                    odd,
                    provider,
                    kickoff_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'five-dollar',
                    %s
                )
            """, (
                parlay_id,
                leg[
                    "fixture_id"
                ],
                leg[
                    "match"
                ],
                leg[
                    "selection"
                ],
                leg[
                    "odd"
                ],
                leg[
                    "kickoff_at"
                ]
            ))

        ensure_daily_tasks(
            telegram_id,
            cur,
            True
        )

        increment_daily_bet(
            telegram_id,
            cur
        )

        add_xp(
            telegram_id,
            10,
            cur
        )

        conn.commit()

        cur.close()
        conn.close()

        fresh = get_user_data(
            telegram_id
        )

        return jsonify({
            "success":
                True,
            "parlay_id":
                parlay_id,
            "balance":
                int(
                    fresh[
                        "balance"
                    ]
                ),
            "total_odd":
                total_odd,
            "possible":
                possible,
            "parlays":
                get_user_parlays(
                    telegram_id
                ),
        })

    except ValueError as error:
        return jsonify({
            "success":
                False,
            "error":
                str(
                    error
                )
        }), 400

    except Exception as error:
        return jsonify({
            "success":
                False,
            "error":
                str(
                    error
                )
        }), 500


@app.route(
    "/api/favorites",
    methods=[
        "POST"
    ]
)
def api_favorites():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    user = get_or_create_user(
        tg_user
    )

    return jsonify({
        "success":
            True,
        "favorites":
            get_user_favorites(
                user[
                    "telegram_id"
                ]
            ),
    })


@app.route(
    "/api/favorites/toggle",
    methods=[
        "POST"
    ]
)
def api_favorites_toggle():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    body = request.get_json(
        silent=True
    ) or {}

    user = get_or_create_user(
        tg_user
    )

    telegram_id = (
        user[
            "telegram_id"
        ]
    )

    fixture_id = int(
        body[
            "fixture_id"
        ]
    )

    favorite = bool(
        body.get(
            "favorite",
            True
        )
    )

    if favorite:
        add_favorite_match(
            telegram_id,
            fixture_id
        )

    else:
        remove_favorite_match(
            telegram_id,
            fixture_id
        )

    return jsonify({
        "success":
            True,
        "favorites":
            get_user_favorites(
                telegram_id
            ),
    })


@app.route(
    "/api/favorites/sync",
    methods=[
        "POST"
    ]
)
def api_favorites_sync():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    body = request.get_json(
        silent=True
    ) or {}

    user = get_or_create_user(
        tg_user
    )

    telegram_id = (
        user[
            "telegram_id"
        ]
    )

    for fixture_id in body.get(
        "fixture_ids",
        []
    )[:100]:
        try:
            add_favorite_match(
                telegram_id,
                int(
                    fixture_id
                )
            )

        except Exception:
            pass

    return jsonify({
        "success":
            True,
        "favorites":
            get_user_favorites(
                telegram_id
            ),
    })


@app.route(
    "/api/favorite-teams",
    methods=[
        "POST"
    ]
)
def api_favorite_teams():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    user = get_or_create_user(
        tg_user
    )

    return jsonify({
        "success":
            True,
        "favorite_teams":
            get_user_favorite_teams(
                user[
                    "telegram_id"
                ]
            ),
    })


@app.route(
    "/api/favorite-teams/toggle",
    methods=[
        "POST"
    ]
)
def api_favorite_teams_toggle():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    body = request.get_json(
        silent=True
    ) or {}

    user = get_or_create_user(
        tg_user
    )

    telegram_id = (
        user[
            "telegram_id"
        ]
    )

    team_name = str(
        body.get(
            "team_name",
            ""
        )
    ).strip()

    favorite = bool(
        body.get(
            "favorite",
            True
        )
    )

    if favorite:
        add_favorite_team(
            telegram_id,
            team_name
        )

    else:
        remove_favorite_team(
            telegram_id,
            team_name
        )

    return jsonify({
        "success":
            True,
        "favorite_teams":
            get_user_favorite_teams(
                telegram_id
            ),
    })


@app.route(
    "/api/favorite-teams/sync",
    methods=[
        "POST"
    ]
)
def api_favorite_teams_sync():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    user = get_or_create_user(
        tg_user
    )

    telegram_id = (
        user[
            "telegram_id"
        ]
    )

    body = request.get_json(
        silent=True
    ) or {}

    for team in body.get(
        "teams",
        []
    )[:100]:
        try:
            add_favorite_team(
                telegram_id,
                str(
                    team
                )
            )

        except Exception:
            pass

    return jsonify({
        "success":
            True,
        "favorite_teams":
            get_user_favorite_teams(
                telegram_id
            ),
    })


@app.route(
    "/api/leaderboard",
    methods=[
        "POST"
    ]
)
def api_leaderboard():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    user = get_or_create_user(
        tg_user
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            telegram_id,
            first_name,
            balance,
            xp
        FROM users
        ORDER BY
            xp DESC,
            balance DESC
        LIMIT 50
    """)

    players = []

    for rank, row in enumerate(
        cur.fetchall(),
        1
    ):
        player_level = calculate_level(
            row[3]
        )

        players.append({
            "rank":
                rank,
            "telegram_id":
                row[0],
            "first_name":
                row[1]
                or
                "Игрок",
            "balance":
                int(
                    row[2]
                    or
                    0
                ),
            "xp":
                int(
                    row[3]
                    or
                    0
                ),
            "level":
                player_level,
            "league":
                get_league(
                    player_level
                ),
        })

    my_rank = next(
        (
            player[
                "rank"
            ]
            for player
            in players
            if int(
                player[
                    "telegram_id"
                ]
            )
            ==
            int(
                user[
                    "telegram_id"
                ]
            )
        ),
        None
    )

    cur.close()
    conn.close()

    return jsonify({
        "success":
            True,
        "players":
            players,
        "my_rank":
            my_rank,
    })


@app.route(
    "/api/daily-reward",
    methods=[
        "POST"
    ]
)
def api_daily_reward():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    user = get_or_create_user(
        tg_user
    )

    telegram_id = (
        user[
            "telegram_id"
        ]
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT last_daily_claim
        FROM users
        WHERE telegram_id = %s
        FOR UPDATE
    """, (
        telegram_id,
    ))

    last_claim = (
        cur.fetchone()[0]
    )

    now = datetime.now(
        timezone.utc
    )

    if (
        last_claim
        and
        now
        <
        last_claim
        +
        timedelta(
            hours=24
        )
    ):
        conn.rollback()

        cur.close()
        conn.close()

        return jsonify({
            "success":
                False,
            "error":
                "Бонус уже получен"
        }), 400

    cur.execute("""
        UPDATE users
        SET
            balance =
                balance + 300,
            last_daily_claim =
                %s,
            updated_at =
                NOW()
        WHERE telegram_id = %s
    """, (
        now,
        telegram_id
    ))

    add_xp(
        telegram_id,
        15,
        cur
    )

    conn.commit()

    cur.close()
    conn.close()

    fresh = get_user_data(
        telegram_id
    )

    return jsonify({
        "success":
            True,
        "balance":
            int(
                fresh[
                    "balance"
                ]
            ),
        **xp_info(
            fresh[
                "xp"
            ]
        ),
    })


@app.route(
    "/api/tasks/claim",
    methods=[
        "POST"
    ]
)
def api_task_claim():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    body = request.get_json(
        silent=True
    ) or {}

    key = body.get(
        "task_key"
    )

    user = get_or_create_user(
        tg_user
    )

    telegram_id = (
        user[
            "telegram_id"
        ]
    )

    tasks = get_daily_tasks(
        telegram_id,
        True
    )

    target = next(
        (
            item
            for item
            in tasks
            if item[
                "key"
            ]
            ==
            key
        ),
        None
    )

    if (
        not target
        or
        not target[
            "completed"
        ]
        or
        target[
            "claimed"
        ]
    ):
        return jsonify({
            "success":
                False,
            "error":
                "Награда недоступна"
        }), 400

    column_map = {
        "login":
            "login_claimed",
        "bets_3":
            "bets_claimed",
        "win_1":
            "win_claimed",
    }

    conn = get_db()
    cur = conn.cursor()

    column = column_map[
        key
    ]

    cur.execute(
        f"""
        UPDATE daily_tasks
        SET {column} = TRUE
        WHERE
            telegram_id = %s
            AND
            task_date = %s
        """,
        (
            telegram_id,
            task_date()
        )
    )

    if target[
        "reward_type"
    ] == "coins":
        cur.execute("""
            UPDATE users
            SET
                balance =
                    balance + %s
            WHERE telegram_id = %s
        """, (
            target[
                "reward"
            ],
            telegram_id
        ))

    else:
        add_xp(
            telegram_id,
            target[
                "reward"
            ],
            cur
        )

    conn.commit()

    cur.close()
    conn.close()

    fresh = get_user_data(
        telegram_id
    )

    return jsonify({
        "success":
            True,
        "balance":
            int(
                fresh[
                    "balance"
                ]
            ),
        **xp_info(
            fresh[
                "xp"
            ]
        ),
        "tasks":
            get_daily_tasks(
                telegram_id
            ),
    })


@app.route(
    "/api/achievements/claim",
    methods=[
        "POST"
    ]
)
def api_achievement_claim():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    body = request.get_json(
        silent=True
    ) or {}

    key = body.get(
        "achievement_key"
    )

    user = get_or_create_user(
        tg_user
    )

    telegram_id = (
        user[
            "telegram_id"
        ]
    )

    achievements = get_achievements(
        telegram_id
    )

    achievement = next(
        (
            item
            for item
            in achievements
            if item[
                "key"
            ]
            ==
            key
        ),
        None
    )

    if (
        not achievement
        or
        not achievement[
            "completed"
        ]
        or
        achievement[
            "claimed"
        ]
    ):
        return jsonify({
            "success":
                False,
            "error":
                "Награда недоступна"
        }), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO achievement_claims (
            telegram_id,
            achievement_key
        )
        VALUES (
            %s,
            %s
        )
        ON CONFLICT DO NOTHING
    """, (
        telegram_id,
        key
    ))

    cur.execute("""
        UPDATE users
        SET
            balance =
                balance + %s
        WHERE telegram_id = %s
    """, (
        achievement[
            "reward"
        ],
        telegram_id
    ))

    conn.commit()

    cur.close()
    conn.close()

    fresh = get_user_data(
        telegram_id
    )

    return jsonify({
        "success":
            True,
        "balance":
            int(
                fresh[
                    "balance"
                ]
            ),
        "achievements":
            get_achievements(
                telegram_id
            ),
    })


@app.route(
    "/api/promo/redeem",
    methods=[
        "POST"
    ]
)
def api_promo_redeem():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    body = request.get_json(
        silent=True
    ) or {}

    try:
        user = get_or_create_user(
            tg_user
        )

        result = redeem_promo_code(
            user[
                "telegram_id"
            ],
            body.get(
                "code",
                ""
            )
        )

        return jsonify({
            "success":
                True,
            **result,
        })

    except ValueError as error:
        return jsonify({
            "success":
                False,
            "error":
                str(
                    error
                )
        }), 400

    except Exception as error:
        print(
            "Promo error:",
            error
        )

        return jsonify({
            "success":
                False,
            "error":
                "Не удалось активировать промокод"
        }), 500


@app.route(
    "/api/settle",
    methods=[
        "POST"
    ]
)
def api_settle():
    tg_user, error = (
        require_telegram_user()
    )

    if error:
        return error

    user = get_or_create_user(
        tg_user
    )

    telegram_id = (
        user[
            "telegram_id"
        ]
    )

    settle_user_bets(
        telegram_id
    )

    settle_user_parlays(
        telegram_id
    )

    fresh = get_user_data(
        telegram_id
    )

    return jsonify({
        "success":
            True,
        "balance":
            int(
                fresh[
                    "balance"
                ]
            ),
        **xp_info(
            fresh[
                "xp"
            ]
        ),
        "bets":
            get_user_bets(
                telegram_id
            ),
        "parlays":
            get_user_parlays(
                telegram_id
            ),
        "stats":
            get_profile_stats(
                telegram_id
            ),
    })


@app.route(
    "/api/logo-refresh/<league_key>"
)
def api_logo_refresh(
    league_key
):
    if league_key not in LEAGUES:
        return jsonify({
            "success":
                False,
            "error":
                "Неизвестная лига"
        }), 400

    try:
        count = refresh_football_data_logos(
            league_key
        )

        return jsonify({
            "success":
                True,
            "league":
                league_key,
            "saved":
                count,
        })

    except Exception as error:
        return jsonify({
            "success":
                False,
            "error":
                str(
                    error
                )
        }), 500


try:
    init_database()
    rebuild_global_logo_cache()

except Exception as error:
    print(
        "Database startup error:",
        error
    )


start_workers()


if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
