import os
import re
import time
import json
import hmac
import hashlib
import threading
import unicodedata

from difflib import SequenceMatcher
from urllib.parse import parse_qsl
from datetime import datetime, timedelta, timezone

import requests
import psycopg2

from flask import Flask, jsonify, request
from flask_cors import CORS


# =========================================================
# APP
# =========================================================

app = Flask(__name__)
CORS(app)


# =========================================================
# ENV
# =========================================================

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


# =========================================================
# LEAGUES
# =========================================================

LEAGUES = {

    "premier_league": {
        "ids": [4160026622],
        "name": "Premier League",
        "short_name": "АПЛ",
        "country": "England",
        "flag": "🏴",
        "football_data_code": "PL"
    },

    "la_liga": {
        "ids": [4212821298],
        "name": "La Liga",
        "short_name": "Ла Лига",
        "country": "Spain",
        "flag": "🇪🇸",
        "football_data_code": "PD"
    },

    "serie_a": {
        "ids": [3405541143],
        "name": "Serie A",
        "short_name": "Серия А",
        "country": "Italy",
        "flag": "🇮🇹",
        "football_data_code": "SA"
    },

    "bundesliga": {
        "ids": [686337048],
        "name": "Bundesliga",
        "short_name": "Бундеслига",
        "country": "Germany",
        "flag": "🇩🇪",
        "football_data_code": "BL1"
    },

    "ligue_1": {
        "ids": [3614399544],
        "name": "Ligue 1",
        "short_name": "Лига 1",
        "country": "France",
        "flag": "🇫🇷",
        "football_data_code": "FL1"
    },

    "champions_league": {
        "ids": [
            2187079931,
            1318331555
        ],
        "name": "UEFA Champions League",
        "short_name": "Лига чемпионов",
        "country": "Europe",
        "flag": "🏆",
        "football_data_code": "CL"
    },

    "europa_league": {
        "ids": [
            2629778952,
            2515803737
        ],
        "name": "UEFA Europa League",
        "short_name": "Лига Европы",
        "country": "Europe",
        "flag": "🟠",
        "football_data_code": "EL"
    },

    "conference_league": {
        "ids": [
            51996766,
            2009834352
        ],
        "name": "UEFA Conference League",
        "short_name": "Лига конференций",
        "country": "Europe",
        "flag": "🟢",
        "football_data_code": None
    },

    "championship": {
        "ids": [1161691669],
        "name": "Championship",
        "short_name": "Чемпионшип",
        "country": "England",
        "flag": "🏴",
        "football_data_code": "ELC"
    },

    "eredivisie": {
        "ids": [137325260],
        "name": "Eredivisie",
        "short_name": "Эредивизи",
        "country": "Netherlands",
        "flag": "🇳🇱",
        "football_data_code": "DED"
    },

    "primeira_liga": {
        "ids": [650171110],
        "name": "Primeira Liga",
        "short_name": "Португалия",
        "country": "Portugal",
        "flag": "🇵🇹",
        "football_data_code": "PPL"
    },

    "mls": {
        "ids": [2221499861],
        "name": "Major League Soccer",
        "short_name": "MLS",
        "country": "USA",
        "flag": "🇺🇸",
        "football_data_code": None
    },

    "saudi_pro_league": {
        "ids": [1796782054],
        "name": "Saudi Pro League",
        "short_name": "Саудовская лига",
        "country": "Saudi Arabia",
        "flag": "🇸🇦",
        "football_data_code": None
    }
}


DEFAULT_LEAGUES = [
    "premier_league",
    "la_liga",
    "serie_a",
    "bundesliga",
    "ligue_1"
]


LEAGUE_ID_TO_KEY = {}

for league_key, league_data in LEAGUES.items():

    for league_id in league_data["ids"]:

        LEAGUE_ID_TO_KEY[
            int(league_id)
        ] = league_key


# =========================================================
# SETTINGS
# =========================================================

FIXTURES_CACHE_SECONDS = 1800
ODDS_CACHE_SECONDS = 21600
RESULT_CACHE_SECONDS = 300

LOGO_MEMORY_CACHE_SECONDS = 21600
LOGO_DATABASE_REFRESH_SECONDS = 604800

NOTIFICATION_MINUTES_BEFORE = 30
NOTIFICATION_CHECK_SECONDS = 60

MAX_FIXTURE_DAYS = 14


TOTAL_POINTS = [
    1.5,
    2.5,
    3.5,
    4.5
]


# =========================================================
# CACHE
# =========================================================

league_fixture_cache = {}

fixture_detail_cache = {}

odds_cache = {}

result_cache = {}

league_logo_cache = {}

global_logo_cache = {}

database_ready = False

notification_worker_started = False

notification_worker_lock = threading.Lock()


# =========================================================
# ACHIEVEMENTS
# =========================================================

ACHIEVEMENTS = [

    {
        "key": "bets_10",
        "title": "Начало положено",
        "description": "Сделать 10 ставок",
        "target": 10,
        "reward": 200
    },

    {
        "key": "wins_5",
        "title": "На победной волне",
        "description": "Выиграть 5 ставок",
        "target": 5,
        "reward": 300
    },

    {
        "key": "level_5",
        "title": "Опытный игрок",
        "description": "Достичь 5 уровня",
        "target": 5,
        "reward": 500
    },

    {
        "key": "xp_500",
        "title": "500 XP",
        "description": "Набрать 500 XP",
        "target": 500,
        "reward": 400
    },

    {
        "key": "high_odd_win",
        "title": "Риск оправдан",
        "description":
            "Выиграть ставку с коэффициентом 3.00+",
        "target": 1,
        "reward": 350
    }
]


# =========================================================
# DATABASE
# =========================================================

def get_db():

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL not found"
        )

    return psycopg2.connect(
        DATABASE_URL
    )


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

            balance INTEGER
                NOT NULL
                DEFAULT 1000,

            created_at TIMESTAMPTZ
                NOT NULL
                DEFAULT NOW(),

            updated_at TIMESTAMPTZ
                NOT NULL
                DEFAULT NOW(),

            last_daily_claim TIMESTAMPTZ,

            xp INTEGER
                NOT NULL
                DEFAULT 0
        )
    """)


    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS
        last_daily_claim TIMESTAMPTZ
    """)


    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS
        xp INTEGER
        NOT NULL
        DEFAULT 0
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS bets (

            id SERIAL PRIMARY KEY,

            telegram_id BIGINT
                NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            fixture_id BIGINT
                NOT NULL,

            match_name TEXT
                NOT NULL,

            selection TEXT
                NOT NULL,

            odd DOUBLE PRECISION
                NOT NULL,

            amount INTEGER
                NOT NULL,

            possible INTEGER
                NOT NULL,

            status TEXT
                NOT NULL
                DEFAULT 'Активна',

            settled BOOLEAN
                NOT NULL
                DEFAULT FALSE,

            score TEXT,

            created_at TIMESTAMPTZ
                NOT NULL
                DEFAULT NOW(),

            provider TEXT
                NOT NULL
                DEFAULT 'five-dollar'
        )
    """)


    cur.execute("""
        ALTER TABLE bets
        ADD COLUMN IF NOT EXISTS
        provider TEXT
        NOT NULL
        DEFAULT 'football-data'
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS parlays (

            id SERIAL PRIMARY KEY,

            telegram_id BIGINT
                NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            amount INTEGER
                NOT NULL,

            total_odd DOUBLE PRECISION
                NOT NULL,

            possible INTEGER
                NOT NULL,

            status TEXT
                NOT NULL
                DEFAULT 'Активна',

            settled BOOLEAN
                NOT NULL
                DEFAULT FALSE,

            created_at TIMESTAMPTZ
                NOT NULL
                DEFAULT NOW(),

            settled_at TIMESTAMPTZ
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS parlay_legs (

            id SERIAL PRIMARY KEY,

            parlay_id INTEGER
                NOT NULL
                REFERENCES parlays(id)
                ON DELETE CASCADE,

            fixture_id BIGINT
                NOT NULL,

            match_name TEXT
                NOT NULL,

            selection TEXT
                NOT NULL,

            odd DOUBLE PRECISION
                NOT NULL,

            status TEXT
                NOT NULL
                DEFAULT 'Активна',

            score TEXT,

            provider TEXT
                NOT NULL
                DEFAULT 'five-dollar'
        )
    """)


    cur.execute("""
        ALTER TABLE parlay_legs
        ADD COLUMN IF NOT EXISTS
        provider TEXT
        NOT NULL
        DEFAULT 'football-data'
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_tasks (

            telegram_id BIGINT
                NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            task_date DATE
                NOT NULL,

            login_done BOOLEAN
                NOT NULL
                DEFAULT FALSE,

            bets_count INTEGER
                NOT NULL
                DEFAULT 0,

            wins_count INTEGER
                NOT NULL
                DEFAULT 0,

            login_claimed BOOLEAN
                NOT NULL
                DEFAULT FALSE,

            bets_claimed BOOLEAN
                NOT NULL
                DEFAULT FALSE,

            win_claimed BOOLEAN
                NOT NULL
                DEFAULT FALSE,

            created_at TIMESTAMPTZ
                NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                telegram_id,
                task_date
            )
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS achievement_claims (

            telegram_id BIGINT
                NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            achievement_key TEXT
                NOT NULL,

            claimed_at TIMESTAMPTZ
                NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                telegram_id,
                achievement_key
            )
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS match_favorites (

            telegram_id BIGINT
                NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            fixture_id BIGINT
                NOT NULL,

            match_name TEXT
                NOT NULL,

            kickoff_at TIMESTAMPTZ
                NOT NULL,

            notifications_enabled BOOLEAN
                NOT NULL
                DEFAULT TRUE,

            notification_sent BOOLEAN
                NOT NULL
                DEFAULT FALSE,

            created_at TIMESTAMPTZ
                NOT NULL
                DEFAULT NOW(),

            updated_at TIMESTAMPTZ
                NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                telegram_id,
                fixture_id
            )
        )
    """)


    # -----------------------------------------------------
    # LOGO CACHE
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS team_logos (

            league_key TEXT
                NOT NULL,

            normalized_name TEXT
                NOT NULL,

            team_name TEXT
                NOT NULL,

            logo_url TEXT
                NOT NULL,

            source TEXT
                NOT NULL
                DEFAULT 'football-data',

            updated_at TIMESTAMPTZ
                NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                league_key,
                normalized_name
            )
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_team_logos_name

        ON team_logos (
            normalized_name
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_bets_user

        ON bets(
            telegram_id
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_parlays_user

        ON parlays(
            telegram_id
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_parlay_legs_parlay

        ON parlay_legs(
            parlay_id
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_match_favorites_due

        ON match_favorites (
            notifications_enabled,
            notification_sent,
            kickoff_at
        )
    """)


    conn.commit()

    cur.close()
    conn.close()

    database_ready = True


# =========================================================
# TEAM LOGOS
# =========================================================

def normalize_club_name(
    name
):

    value = str(
        name or ""
    ).strip().lower()


    if not value:
        return ""


    value = unicodedata.normalize(
        "NFKD",
        value
    )


    value = "".join(
        char
        for char
        in value
        if not unicodedata.combining(
            char
        )
    )


    value = value.replace(
        "&",
        " and "
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


    words = [
        word
        for word
        in value.split()
        if word not in {
            "fc",
            "cf",
            "afc",
            "ac",
            "sc",
            "ssc",
            "rcd",
            "rc",
            "cd",
            "ud",
            "as",
            "sv",
            "vfb",
            "vfl",
            "fk",
            "sk",
            "club",
            "football",
            "futbol",
            "calcio"
        }
    ]


    return " ".join(
        words
    ).strip()


def football_data_get(
    path
):

    if not FOOTBALL_TOKEN:

        raise RuntimeError(
            "FOOTBALL_DATA_TOKEN not found"
        )


    response = requests.get(
        (
            FOOTBALL_DATA_URL
            +
            path
        ),

        headers={
            "X-Auth-Token":
                FOOTBALL_TOKEN
        },

        timeout=25
    )


    if response.status_code != 200:

        try:

            payload = response.json()

        except Exception:

            payload = response.text[:300]


        raise RuntimeError(
            (
                "football-data.org HTTP "
                f"{response.status_code}: "
                f"{payload}"
            )
        )


    return response.json()


def save_logo_entry(
    league_key,
    name,
    logo_url,
    cursor
):

    normalized = normalize_club_name(
        name
    )


    if (
        not normalized
        or
        not logo_url
    ):

        return


    cursor.execute("""
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

            source =
                EXCLUDED.source,

            updated_at =
                NOW()
    """, (
        league_key,
        normalized,
        name,
        logo_url
    ))


def read_league_logos_from_db(
    league_key
):

    try:

        conn = get_db()
        cur = conn.cursor()


        cur.execute("""
            SELECT
                normalized_name,
                team_name,
                logo_url,
                updated_at

            FROM team_logos

            WHERE league_key = %s
        """, (
            league_key,
        ))


        rows = cur.fetchall()

        cur.close()
        conn.close()


        result = {}


        newest = None


        for row in rows:

            normalized = row[0]

            result[
                normalized
            ] = {
                "name":
                    row[1],

                "logo":
                    row[2]
            }


            if (
                row[3]
                and
                (
                    newest is None
                    or
                    row[3] > newest
                )
            ):

                newest = row[3]


        return result, newest


    except Exception as error:

        print(
            "Read logo DB error:",
            error
        )

        return {}, None


def refresh_football_data_logos(
    league_key
):

    config = LEAGUES.get(
        league_key
    )


    if not config:

        return {}


    code = config.get(
        "football_data_code"
    )


    if (
        not code
        or
        not FOOTBALL_TOKEN
    ):

        return {}


    try:

        data = football_data_get(
            (
                "/competitions/"
                f"{code}"
                "/teams"
            )
        )


        teams = (
            data.get(
                "teams"
            )
            or
            []
        )


        conn = get_db()
        cur = conn.cursor()


        result = {}


        for team in teams:

            crest = (
                team.get(
                    "crest"
                )
                or
                ""
            )


            if not crest:
                continue


            names = [
                team.get(
                    "name"
                ),
                team.get(
                    "shortName"
                )
            ]


            tla = team.get(
                "tla"
            )


            for name in names:

                if not name:
                    continue


                normalized = normalize_club_name(
                    name
                )


                if not normalized:
                    continue


                result[
                    normalized
                ] = {
                    "name":
                        name,

                    "logo":
                        crest
                }


                save_logo_entry(
                    league_key,
                    name,
                    crest,
                    cur
                )


            # TLA сохраняем только в оперативный кэш.
            # Например ARS / BAR / RMA.

            if tla:

                normalized_tla = (
                    normalize_club_name(
                        tla
                    )
                )


                if normalized_tla:

                    result[
                        normalized_tla
                    ] = {
                        "name":
                            tla,

                        "logo":
                            crest
                    }


        conn.commit()

        cur.close()
        conn.close()


        return result


    except Exception as error:

        print(
            "Football-data logo error:",
            league_key,
            error
        )

        return {}


def rebuild_global_logo_cache():

    global global_logo_cache

    combined = {}


    for cache_item in (
        league_logo_cache.values()
    ):

        data = (
            cache_item.get(
                "data"
            )
            or
            {}
        )


        for key, value in data.items():

            if key not in combined:

                combined[
                    key
                ] = value


    global_logo_cache = combined


def load_league_logos(
    league_key,
    force=False
):

    cached = league_logo_cache.get(
        league_key
    )


    if (
        not force
        and
        cached
        and
        time.time()
        -
        cached[
            "time"
        ]
        <
        LOGO_MEMORY_CACHE_SECONDS
    ):

        return cached[
            "data"
        ]


    db_logos, newest = (
        read_league_logos_from_db(
            league_key
        )
    )


    database_fresh = False


    if newest:

        now = datetime.now(
            timezone.utc
        )


        if newest.tzinfo is None:

            newest = newest.replace(
                tzinfo=timezone.utc
            )


        age = (
            now
            -
            newest.astimezone(
                timezone.utc
            )
        ).total_seconds()


        if (
            age
            <
            LOGO_DATABASE_REFRESH_SECONDS
        ):

            database_fresh = True


    logos = db_logos


    if (
        force
        or
        not database_fresh
        or
        len(
            db_logos
        )
        <
        8
    ):

        refreshed = (
            refresh_football_data_logos(
                league_key
            )
        )


        if refreshed:

            logos.update(
                refreshed
            )


    league_logo_cache[
        league_key
    ] = {
        "time":
            time.time(),

        "data":
            logos
    }


    rebuild_global_logo_cache()


    return logos


def logo_similarity(
    first,
    second
):

    if (
        not first
        or
        not second
    ):

        return 0


    return SequenceMatcher(
        None,
        first,
        second
    ).ratio()


def find_logo_in_map(
    team_name,
    logo_map
):

    normalized = normalize_club_name(
        team_name
    )


    if (
        not normalized
        or
        not logo_map
    ):

        return ""


    # 1. Точное совпадение

    exact = logo_map.get(
        normalized
    )


    if exact:

        return exact.get(
            "logo",
            ""
        )


    # 2. Одно название содержится в другом

    candidates = []


    for key, value in logo_map.items():

        if (
            len(
                normalized
            )
            >=
            5
            and
            len(
                key
            )
            >=
            5
            and
            (
                normalized in key
                or
                key in normalized
            )
        ):

            difference = abs(
                len(
                    normalized
                )
                -
                len(
                    key
                )
            )


            candidates.append(
                (
                    difference,
                    value.get(
                        "logo",
                        ""
                    )
                )
            )


    if candidates:

        candidates.sort(
            key=lambda item:
                item[0]
        )


        if candidates[0][1]:

            return candidates[0][1]


    # 3. Нечёткое совпадение

    best_logo = ""
    best_score = 0


    for key, value in logo_map.items():

        score = logo_similarity(
            normalized,
            key
        )


        if score > best_score:

            best_score = score

            best_logo = value.get(
                "logo",
                ""
            )


    if (
        best_score
        >=
        0.78
    ):

        return best_logo


    return ""


def resolve_team_logo(
    team_name,
    league_key=None
):

    if league_key:

        league_map = (
            load_league_logos(
                league_key
            )
        )


        result = find_logo_in_map(
            team_name,
            league_map
        )


        if result:
            return result


    # Если команда играет в ЛЧ/ЛЕ/ЛК,
    # но логотип уже был загружен из её чемпионата.

    result = find_logo_in_map(
        team_name,
        global_logo_cache
    )


    if result:
        return result


    return ""


# =========================================================
# TELEGRAM AUTH
# =========================================================

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
            int(
                time.time()
            )
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
                "success": False,
                "error":
                    "Telegram authentication failed"
            }),
            401
        )


    return user, None


# =========================================================
# USERS
# =========================================================

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
        "telegram_id":
            row[0],

        "first_name":
            row[1],

        "username":
            row[2],

        "balance":
            row[3],

        "last_daily_claim":
            row[4],

        "xp":
            row[5]
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
        "telegram_id":
            row[0],

        "first_name":
            row[1],

        "username":
            row[2],

        "balance":
            row[3],

        "last_daily_claim":
            row[4],

        "xp":
            row[5]
    }


# =========================================================
# XP
# =========================================================

def calculate_level(
    xp
):

    return (
        int(
            xp or 0
        )
        //
        100
    ) + 1


def get_league(
    level
):

    level = int(
        level or 1
    )


    if level >= 30:

        return {
            "key": "master",
            "name": "Мастер",
            "icon": "👑",
            "min_level": 30,
            "next_level": None
        }


    if level >= 20:

        return {
            "key": "diamond",
            "name": "Алмаз",
            "icon": "💎",
            "min_level": 20,
            "next_level": 30
        }


    if level >= 10:

        return {
            "key": "gold",
            "name": "Золото",
            "icon": "🥇",
            "min_level": 10,
            "next_level": 20
        }


    if level >= 5:

        return {
            "key": "silver",
            "name": "Серебро",
            "icon": "🥈",
            "min_level": 5,
            "next_level": 10
        }


    return {
        "key": "bronze",
        "name": "Бронза",
        "icon": "🥉",
        "min_level": 1,
        "next_level": 5
    }


def xp_info(
    xp
):

    xp = int(
        xp or 0
    )


    level = calculate_level(
        xp
    )


    current = xp % 100


    return {
        "xp":
            xp,

        "level":
            level,

        "league":
            get_league(
                level
            ),

        "current_level_xp":
            current,

        "xp_to_next_level":
            100 - current
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
    gained = []


    for level_number in range(
        old_level + 1,
        new_level + 1
    ):

        level_reward = 100


        if (
            level_number
            %
            5
            ==
            0
        ):

            level_reward += 500


        reward += level_reward


        gained.append({
            "level":
                level_number,

            "reward":
                level_reward
        })


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


    result[
        "levels_gained"
    ] = gained


    return result


# =========================================================
# DAILY TASKS
# =========================================================

def task_date():

    return datetime.now(
        timezone.utc
    ).date()


def ensure_daily_tasks(
    telegram_id,
    cursor=None,
    mark_login=False
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

            SET
                login_done = TRUE

            WHERE
                telegram_id = %s
                AND
                task_date = %s
        """, (
            telegram_id,
            today
        ))


    if own_connection:

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


    (
        login_done,
        bets_count,
        wins_count,
        login_claimed,
        bets_claimed,
        win_claimed
    ) = row


    bets_count = int(
        bets_count or 0
    )

    wins_count = int(
        wins_count or 0
    )


    return [

        {
            "key": "login",
            "title":
                "Зайти в приложение",
            "description":
                "Открой BetCoin сегодня",
            "progress":
                1 if login_done else 0,
            "target": 1,
            "completed":
                bool(
                    login_done
                ),
            "claimed":
                bool(
                    login_claimed
                ),
            "reward_type":
                "xp",
            "reward":
                50
        },

        {
            "key": "bets_3",
            "title":
                "Сделать 3 ставки",
            "description":
                "Сделай 3 ставки за сегодня",
            "progress":
                min(
                    bets_count,
                    3
                ),
            "target": 3,
            "completed":
                bets_count >= 3,
            "claimed":
                bool(
                    bets_claimed
                ),
            "reward_type":
                "coins",
            "reward":
                100
        },

        {
            "key": "win_1",
            "title":
                "Выиграть 1 ставку",
            "description":
                "Получи один выигрыш сегодня",
            "progress":
                min(
                    wins_count,
                    1
                ),
            "target": 1,
            "completed":
                wins_count >= 1,
            "claimed":
                bool(
                    win_claimed
                ),
            "reward_type":
                "coins",
            "reward":
                150
        }
    ]


# =========================================================
# 5 DOLLAR API
# =========================================================

def five_headers():

    return {
        "Authorization":
            (
                "Bearer "
                +
                FIVE_DOLLAR_FOOTBALL_API_KEY
            ),

        "Accept":
            "application/json"
    }


def five_get(
    path,
    params=None,
    attempts=3
):

    if not FIVE_DOLLAR_FOOTBALL_API_KEY:

        raise RuntimeError(
            "FIVE_DOLLAR_FOOTBALL_API_KEY not found"
        )


    last_error = None


    for attempt in range(
        attempts
    ):

        response = requests.get(
            FIVE_API_URL + path,

            headers=
                five_headers(),

            params=
                params or {},

            timeout=30
        )


        if (
            response.status_code
            ==
            429
        ):

            last_error = (
                "5DollarFootballAPI rate limit"
            )


            if (
                attempt
                <
                attempts - 1
            ):

                time.sleep(
                    7
                )

                continue


        if (
            response.status_code
            !=
            200
        ):

            try:

                payload = response.json()

            except Exception:

                payload = response.text[:500]


            raise RuntimeError(
                (
                    "5DollarFootballAPI HTTP "
                    f"{response.status_code}: "
                    f"{payload}"
                )
            )


        data = response.json()


        if (
            isinstance(
                data,
                dict
            )
            and
            data.get(
                "success"
            )
            is False
        ):

            raise RuntimeError(
                (
                    "5DollarFootballAPI error: "
                    f"{data}"
                )
            )


        return data


    raise RuntimeError(
        last_error
        or
        "5DollarFootballAPI request failed"
    )


# =========================================================
# DATE HELPERS
# =========================================================

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


        if not raw:
            return None


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


# =========================================================
# ODDS PARSER
# =========================================================

def first_snapshot(
    market
):

    if not isinstance(
        market,
        dict
    ):

        return None


    return (
        market.get(
            "closing"
        )
        or
        market.get(
            "opening"
        )
        or
        market.get(
            "inplay"
        )
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


    if isinstance(
        data,
        dict
    ):

        if isinstance(
            data.get(
                "bookmakers"
            ),
            list
        ):

            return data[
                "bookmakers"
            ]


    market_keys = {
        "1x2",
        "asian_handicap",
        "goal_line",
        "goal_line_fixed",
        "goalline_fixed",
        "btts"
    }


    if (
        market_keys
        &
        set(
            payload.keys()
        )
    ):

        return [{
            "name":
                "Bet 365",

            "slug":
                "bet365",

            "odds":
                payload
        }]


    return []


def parse_odds_response(
    payload
):

    result = {
        "odds":
            None,

        "double_chance":
            None,

        "totals":
            {},

        "btts":
            None,

        "handicaps":
            None,

        "team_totals":
            None,

        "bookmaker":
            None,

        "available_markets":
            []
    }


    bookmakers = extract_bookmakers(
        payload
    )


    if not bookmakers:
        return result


    bookmaker = None


    for item in bookmakers:

        if (
            str(
                item.get(
                    "slug",
                    ""
                )
            ).lower()
            ==
            "bet365"
        ):

            bookmaker = item
            break


    if bookmaker is None:

        bookmaker = bookmakers[0]


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


    # 1X2

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
                )
        }


    # BTTS

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
                )
        }


    # TOTALS

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

        for line_item in fixed_lines:

            if not isinstance(
                line_item,
                dict
            ):

                continue


            try:

                line = float(
                    line_item.get(
                        "line"
                    )
                )

            except Exception:

                continue


            if line not in TOTAL_POINTS:
                continue


            snapshot = first_snapshot(
                line_item
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
                    )
            }


    # MAIN GOAL LINE

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
            str(
                line
            )
            not in
            result[
                "totals"
            ]
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
                    )
            }


    # ASIAN HANDICAP

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
                    away_line
            }


    return result


# =========================================================
# MATCH NORMALIZER
# =========================================================

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
    fallback_league_key=None,
    load_logos=True
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
        ""
    )


    away_logo = (
        away.get(
            "logo"
        )
        or
        ""
    )


    if load_logos:

        if not home_logo:

            home_logo = (
                resolve_team_logo(
                    home_name,
                    league_key
                )
            )


        if not away_logo:

            away_logo = (
                resolve_team_logo(
                    away_name,
                    league_key
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
            league.get(
                "name"
            )
            or
            league_config.get(
                "name"
            )
            or
            "Football",

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

        "double_chance":
            parsed.get(
                "double_chance"
            ),

        "handicaps":
            parsed.get(
                "handicaps"
            ),

        "team_totals":
            parsed.get(
                "team_totals"
            ),

        "bookmaker":
            parsed.get(
                "bookmaker"
            ),

        "available_extra_markets":
            parsed.get(
                "available_markets",
                []
            )
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
                    )
            }


        else:

            match[
                field
            ] = None


    return match


# =========================================================
# LEAGUE FIXTURES
# =========================================================

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
        cached[
            "time"
        ]
        <
        FIXTURES_CACHE_SECONDS
    ):

        return cached[
            "data"
        ]


    # Сначала один раз грузим эмблемы
    # всех команд этой лиги.

    try:

        load_league_logos(
            league_key,
            force=False
        )

    except Exception as error:

        print(
            "League logo load error:",
            league_key,
            error
        )


    config = LEAGUES[
        league_key
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


    result = []


    for league_id in config[
        "ids"
    ]:

        try:

            data = five_get(
                (
                    "/v1/leagues/"
                    f"{league_id}"
                    "/fixtures"
                ),

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
                        50
                }
            )


            items = (
                data.get(
                    "data"
                )
                or
                []
            )


            for item in items:

                try:

                    match = make_match_from_item(
                        item,
                        league_key,
                        True
                    )


                    if not match.get(
                        "fixture_id"
                    ):

                        continue


                    result.append(
                        match
                    )


                    fixture_detail_cache[
                        str(
                            int(
                                match[
                                    "fixture_id"
                                ]
                            )
                        )
                    ] = {
                        "time":
                            time.time(),

                        "data":
                            match
                    }


                except Exception as error:

                    print(
                        "Fixture normalize error:",
                        error
                    )


        except Exception as error:

            print(
                "League fixtures error:",
                league_key,
                league_id,
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


    league_fixture_cache[
        league_key
    ] = {
        "time":
            time.time(),

        "data":
            result
    }


    return result


def load_default_fixtures(
    force=False
):

    result = []


    for league_key in DEFAULT_LEAGUES:

        try:

            result.extend(
                load_league_fixtures(
                    league_key,
                    force
                )
            )


        except Exception as error:

            print(
                "Default league error:",
                league_key,
                error
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
        cached[
            "time"
        ]
        <
        FIXTURES_CACHE_SECONDS
    ):

        return cached[
            "data"
        ]


    for league_cache in (
        league_fixture_cache.values()
    ):

        for match in (
            league_cache.get(
                "data"
            )
            or
            []
        ):

            if (
                int(
                    match.get(
                        "fixture_id"
                    )
                    or
                    0
                )
                ==
                int(
                    fixture_id
                )
            ):

                return match


    return None


# =========================================================
# SINGLE MATCH / ODDS
# =========================================================

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
        cached[
            "time"
        ]
        <
        ODDS_CACHE_SECONDS
    ):

        return cached[
            "data"
        ]


    data = five_get(
        (
            "/v1/fixtures/"
            f"{int(fixture_id)}"
            "/odds"
        )
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
            parsed
    }


    return parsed


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

            return dict(
                cached
            )


    data = five_get(
        (
            "/v1/fixtures/"
            f"{int(fixture_id)}"
        )
    )


    item = (
        data.get(
            "data"
        )
        or
        {}
    )


    match = make_match_from_item(
        item,
        None,
        True
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
                "double_chance"
            ] = parsed.get(
                "double_chance"
            )


            match[
                "team_totals"
            ] = parsed.get(
                "team_totals"
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
                            )
                    }

                    if
                    (
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

                    else
                    None
                )


        except Exception as error:

            print(
                "Single match odds error:",
                error
            )


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
            match
    }


    return match


# =========================================================
# MARKET LOOKUP
# =========================================================

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
            "П1"
        )


    if selection == "X":

        return (
            odds.get(
                "draw"
            ),
            "X"
        )


    if selection == "П2":

        return (
            odds.get(
                "away"
            ),
            "П2"
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
            "ОЗ Да"
        )


    if selection == "ОЗ Нет":

        return (
            btts.get(
                "no"
            ),
            "ОЗ Нет"
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

            (
                f"Т"
                f"{total_match.group(1)} "
                f"{line}"
            )
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


        handicap_data = (
            match.get(
                "handicaps"
            )
            or
            {}
        )


        odd = (
            handicap_data.get(
                side,
                {}
            ).get(
                line_key
            )
        )


        signed = (
            f"+{line_key}"
            if line > 0
            else line_key
        )


        return (
            odd,
            f"Ф{team_number}({signed})"
        )


    return (
        None,
        selection
    )


def resolve_canonical_bet(
    fixture_id,
    selection
):

    match = get_fixture(
        fixture_id,
        True
    )


    status = str(
        match.get(
            "status",
            ""
        )
    ).lower()


    if status not in (
        "",
        "scheduled",
        "unknown"
    ):

        raise ValueError(
            "На этот матч уже нельзя ставить"
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


    odd, canonical_selection = (
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


        temp_match = dict(
            match
        )


        temp_match[
            "odds"
        ] = parsed.get(
            "odds"
        )


        temp_match[
            "btts"
        ] = parsed.get(
            "btts"
        )


        temp_match[
            "handicaps"
        ] = parsed.get(
            "handicaps"
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


            temp_match[
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
                    )
            }


        odd, canonical_selection = (
            match_market_odd(
                temp_match,
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


    if (
        odd <= 1
        or
        odd > 1000
    ):

        raise ValueError(
            "Некорректный коэффициент"
        )


    return {
        "fixture_id":
            int(
                fixture_id
            ),

        "match":
            (
                f"{match['home']} — "
                f"{match['away']}"
            ),

        "selection":
            canonical_selection,

        "odd":
            odd,

        "provider":
            "five-dollar"
    }


# =========================================================
# RESULT CALCULATION
# =========================================================

def compare_total(
    value,
    line,
    kind
):

    if kind == "over":

        if value > line:
            return "win"

        if value < line:
            return "loss"

        return "refund"


    if value < line:
        return "win"

    if value > line:
        return "loss"

    return "refund"


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

            if
            (
                home_score > 0
                and
                away_score > 0
            )

            else
            "loss"
        )


    if selection == "ОЗ Нет":

        return (
            "win"

            if
            (
                home_score == 0
                or
                away_score == 0
            )

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


        kind = (
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


        return compare_total(
            total,
            line,
            kind
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


        handicap = float(
            handicap_match.group(
                2
            )
        )


        if team_number == 1:

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


# =========================================================
# RESULTS
# =========================================================

def get_legacy_result(
    fixture_id
):

    if not FOOTBALL_TOKEN:
        return None


    response = requests.get(
        (
            FOOTBALL_DATA_URL
            +
            "/matches/"
            +
            str(
                int(
                    fixture_id
                )
            )
        ),

        headers={
            "X-Auth-Token":
                FOOTBALL_TOKEN
        },

        timeout=20
    )


    response.raise_for_status()


    data = response.json()


    full_time = (
        (
            data.get(
                "score"
            )
            or
            {}
        ).get(
            "fullTime"
        )
        or
        {}
    )


    return {
        "status":
            data.get(
                "status"
            ),

        "home_score":
            full_time.get(
                "home"
            ),

        "away_score":
            full_time.get(
                "away"
            )
    }


def get_result(
    provider,
    fixture_id
):

    cache_key = (
        f"{provider}:"
        f"{int(fixture_id)}"
    )


    cached = result_cache.get(
        cache_key
    )


    if (
        cached
        and
        time.time()
        -
        cached[
            "time"
        ]
        <
        RESULT_CACHE_SECONDS
    ):

        return cached[
            "data"
        ]


    try:

        if provider == "five-dollar":

            data = get_fixture(
                fixture_id,
                False,
                True
            )


        else:

            data = get_legacy_result(
                fixture_id
            )


        result_cache[
            cache_key
        ] = {
            "time":
                time.time(),

            "data":
                data
        }


        return data


    except Exception:

        return None


def is_finished(
    provider,
    status
):

    if provider == "five-dollar":

        return (
            str(
                status
            ).lower()
            ==
            "finished"
        )


    return (
        str(
            status
        ).upper()
        ==
        "FINISHED"
    )


# =========================================================
# SETTLE SINGLES
# =========================================================

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
            possible,
            provider

        FROM bets

        WHERE
            telegram_id = %s
            AND
            status = 'Активна'
            AND
            settled = FALSE
    """, (
        telegram_id,
    ))


    rows = cur.fetchall()


    for row in rows:

        (
            bet_id,
            fixture_id,
            selection,
            amount,
            possible,
            provider
        ) = row


        match = get_result(
            provider,
            fixture_id
        )


        if (
            not match
            or
            not is_finished(
                provider,
                match.get(
                    "status"
                )
            )
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


        if result is None:
            continue


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


        else:

            status = "Проиграла"
            payout = 0


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


# =========================================================
# SETTLE PARLAYS
# =========================================================

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

        FOR UPDATE
    """, (
        telegram_id,
    ))


    parlay_rows = cur.fetchall()


    for (
        parlay_id,
        amount
    ) in parlay_rows:


        cur.execute("""
            SELECT
                id,
                fixture_id,
                selection,
                odd,
                status,
                provider

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
                current_status,
                provider
            ) = leg


            if current_status == "Проиграла":

                any_loss = True
                continue


            if current_status == "Выиграла":

                effective_odd *= float(
                    odd
                )

                continue


            if current_status == "Возврат":
                continue


            match = get_result(
                provider,
                fixture_id
            )


            if (
                not match
                or
                not is_finished(
                    provider,
                    match.get(
                        "status"
                    )
                )
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


            if result is None:

                all_resolved = False
                continue


            if result == "win":

                leg_status = "Выиграла"

                effective_odd *= float(
                    odd
                )


            elif result == "refund":

                leg_status = "Возврат"


            else:

                leg_status = "Проиграла"
                any_loss = True


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
                leg_status,
                score,
                leg_id
            ))


        if any_loss:

            cur.execute("""
                UPDATE parlays

                SET
                    status = 'Проиграла',
                    settled = TRUE,
                    settled_at = NOW()

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


# =========================================================
# BET LISTS
# =========================================================

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
            "id":
                row[0],

            "fixture_id":
                row[1],

            "match":
                row[2],

            "selection":
                row[3],

            "odd":
                row[4],

            "amount":
                row[5],

            "possible":
                row[6],

            "status":
                row[7],

            "settled":
                row[8],

            "score":
                row[9],

            "created_at":
                (
                    row[10].isoformat()
                    if row[10]
                    else None
                )
        }

        for row
        in rows
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


        legs = []


        for leg in cur.fetchall():

            legs.append({
                "id":
                    leg[0],

                "fixture_id":
                    leg[1],

                "match":
                    leg[2],

                "selection":
                    leg[3],

                "odd":
                    leg[4],

                "status":
                    leg[5],

                "score":
                    leg[6]
            })


        result.append({
            "id":
                row[0],

            "amount":
                row[1],

            "total_odd":
                row[2],

            "possible":
                row[3],

            "status":
                row[4],

            "settled":
                row[5],

            "created_at":
                (
                    row[6].isoformat()
                    if row[6]
                    else None
                ),

            "settled_at":
                (
                    row[7].isoformat()
                    if row[7]
                    else None
                ),

            "legs":
                legs
        })


    cur.close()
    conn.close()


    return result


# =========================================================
# ACHIEVEMENTS
# =========================================================

def get_achievements(
    telegram_id
):

    conn = get_db()
    cur = conn.cursor()


    cur.execute("""
        SELECT xp

        FROM users

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))


    row = cur.fetchone()


    user_xp = int(
        row[0]
        if row
        else 0
    )


    level = calculate_level(
        user_xp
    )


    cur.execute("""
        SELECT COUNT(*)

        FROM bets

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))


    bet_count = int(
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
        SELECT COUNT(*)

        FROM parlays

        WHERE
            telegram_id = %s
            AND
            status = 'Выиграла'
    """, (
        telegram_id,
    ))


    parlay_wins = int(
        cur.fetchone()[0]
    )


    cur.execute("""
        SELECT COUNT(*)

        FROM bets

        WHERE
            telegram_id = %s
            AND
            status = 'Выиграла'
            AND
            odd >= 3
    """, (
        telegram_id,
    ))


    high_odd = int(
        cur.fetchone()[0]
    )


    cur.execute("""
        SELECT COUNT(*)

        FROM parlays

        WHERE
            telegram_id = %s
            AND
            status = 'Выиграла'
            AND
            total_odd >= 3
    """, (
        telegram_id,
    ))


    high_parlay = int(
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
        item[0]
        for item
        in cur.fetchall()
    }


    cur.close()
    conn.close()


    values = {

        "bets_10":
            bet_count
            +
            parlay_count,

        "wins_5":
            wins
            +
            parlay_wins,

        "level_5":
            level,

        "xp_500":
            user_xp,

        "high_odd_win":
            (
                1

                if
                high_odd
                +
                high_parlay
                >
                0

                else
                0
            )
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
                claimed
        })


    return result


# =========================================================
# LEADERBOARD
# =========================================================

def get_leaderboard(
    current_telegram_id=None,
    limit=50
):

    conn = get_db()
    cur = conn.cursor()


    limit = max(
        1,
        min(
            int(
                limit
            ),
            100
        )
    )


    cur.execute("""
        SELECT
            telegram_id,
            first_name,
            username,
            balance,
            xp

        FROM users

        ORDER BY
            xp DESC,
            balance DESC,
            telegram_id ASC

        LIMIT %s
    """, (
        limit,
    ))


    players = []


    for rank, row in enumerate(
        cur.fetchall(),
        start=1
    ):

        player_xp = int(
            row[4]
            or
            0
        )


        player_level = calculate_level(
            player_xp
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

            "username":
                row[2]
                or
                "",

            "balance":
                int(
                    row[3]
                    or
                    0
                ),

            "xp":
                player_xp,

            "level":
                player_level,

            "league":
                get_league(
                    player_level
                )
        })


    my_rank = None


    if current_telegram_id is not None:

        cur.execute("""
            SELECT
                COUNT(*) + 1

            FROM users target

            WHERE
                target.xp >
                    (
                        SELECT xp
                        FROM users
                        WHERE telegram_id = %s
                    )

                OR
                (
                    target.xp =
                        (
                            SELECT xp
                            FROM users
                            WHERE telegram_id = %s
                        )

                    AND

                    target.balance >
                        (
                            SELECT balance
                            FROM users
                            WHERE telegram_id = %s
                        )
                )
        """, (
            current_telegram_id,
            current_telegram_id,
            current_telegram_id
        ))


        row = cur.fetchone()


        if row:

            my_rank = int(
                row[0]
            )


    cur.close()
    conn.close()


    return {
        "players":
            players,

        "my_rank":
            my_rank
    }


# =========================================================
# PROFILE STATS
# =========================================================

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
            ),

            COALESCE(
                SUM(
                    CASE
                        WHEN status = 'Выиграла'
                        THEN possible
                        ELSE 0
                    END
                ),
                0
            ),

            COALESCE(
                SUM(
                    CASE
                        WHEN settled = TRUE
                        THEN amount
                        ELSE 0
                    END
                ),
                0
            ),

            COALESCE(
                SUM(
                    CASE
                        WHEN status = 'Выиграла'
                        THEN possible

                        WHEN status = 'Возврат'
                        THEN amount

                        ELSE 0
                    END
                ),
                0
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

    total_won = int(
        row[5] or 0
    )

    staked = int(
        row[6] or 0
    )

    returned = int(
        row[7] or 0
    )


    if (
        wins
        +
        losses
        >
        0
    ):

        win_rate = round(
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

    else:

        win_rate = 0.0


    cur.execute("""
        SELECT status

        FROM bets

        WHERE
            telegram_id = %s
            AND
            settled = TRUE

        ORDER BY id ASC
    """, (
        telegram_id,
    ))


    streak = 0
    best_streak = 0


    for status_row in cur.fetchall():

        if status_row[0] == "Выиграла":

            streak += 1

            best_streak = max(
                best_streak,
                streak
            )

        else:

            streak = 0


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
            ),

            COALESCE(
                SUM(
                    CASE
                        WHEN status = 'Выиграла'
                        THEN possible
                        ELSE 0
                    END
                ),
                0
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

        "settled_bets":
            wins
            +
            losses
            +
            refunds,

        "win_rate":
            win_rate,

        "current_win_streak":
            streak,

        "best_win_streak":
            best_streak,

        "total_won":
            total_won,

        "settled_staked":
            staked,

        "settled_returned":
            returned,

        "net_profit":
            returned
            -
            staked,

        "total_parlays":
            int(
                parlay[0]
                or
                0
            ),

        "active_parlays":
            int(
                parlay[1]
                or
                0
            ),

        "parlay_wins":
            int(
                parlay[2]
                or
                0
            ),

        "parlay_losses":
            int(
                parlay[3]
                or
                0
            ),

        "parlay_refunds":
            int(
                parlay[4]
                or
                0
            ),

        "parlay_total_won":
            int(
                parlay[5]
                or
                0
            )
    }


# =========================================================
# FAVORITES
# =========================================================

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
                (
                    row[2].isoformat()
                    if row[2]
                    else None
                ),

            "notifications_enabled":
                bool(
                    row[3]
                ),

            "notification_sent":
                bool(
                    row[4]
                )
        }

        for row
        in rows
    ]


def add_favorite_match(
    telegram_id,
    fixture_id
):

    fixture_id = int(
        fixture_id
    )


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


    if (
        kickoff
        <=
        datetime.now(
            timezone.utc
        )
    ):

        raise ValueError(
            "Матч уже начался"
        )


    match_name = (
        f"{match.get('home', 'Unknown')} — "
        f"{match.get('away', 'Unknown')}"
    )


    conn = get_db()
    cur = conn.cursor()


    cur.execute("""
        INSERT INTO match_favorites (
            telegram_id,
            fixture_id,
            match_name,
            kickoff_at,
            notifications_enabled,
            notification_sent
        )

        VALUES (
            %s,
            %s,
            %s,
            %s,
            TRUE,
            FALSE
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

            notification_sent =
                CASE

                    WHEN
                        match_favorites.kickoff_at
                        IS DISTINCT FROM
                        EXCLUDED.kickoff_at

                    THEN FALSE

                    ELSE
                        match_favorites.notification_sent
                END,

            updated_at =
                NOW()
    """, (
        telegram_id,
        fixture_id,
        match_name,
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
        int(
            fixture_id
        )
    ))


    conn.commit()

    cur.close()
    conn.close()


# =========================================================
# NOTIFICATIONS
# =========================================================

def send_telegram_message(
    telegram_id,
    text
):

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN not found"
        )


    response = requests.post(
        (
            "https://api.telegram.org/bot"
            +
            TELEGRAM_BOT_TOKEN
            +
            "/sendMessage"
        ),

        json={
            "chat_id":
                int(
                    telegram_id
                ),

            "text":
                str(
                    text
                ),

            "disable_web_page_preview":
                True
        },

        timeout=20
    )


    try:

        payload = response.json()

    except Exception:

        payload = {
            "ok": False
        }


    if (
        response.status_code
        !=
        200
        or
        not payload.get(
            "ok"
        )
    ):

        raise RuntimeError(
            (
                "Telegram sendMessage error: "
                f"{payload}"
            )
        )


def claim_due_notification():

    conn = get_db()
    cur = conn.cursor()


    cur.execute("""
        WITH candidate AS (

            SELECT
                telegram_id,
                fixture_id

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

            FOR UPDATE
            SKIP LOCKED

            LIMIT 1
        )

        UPDATE match_favorites AS target

        SET
            notification_sent = TRUE,
            updated_at = NOW()

        FROM candidate

        WHERE
            target.telegram_id =
                candidate.telegram_id

            AND

            target.fixture_id =
                candidate.fixture_id

        RETURNING
            target.telegram_id,
            target.fixture_id,
            target.match_name,
            target.kickoff_at
    """, (
        NOTIFICATION_MINUTES_BEFORE,
    ))


    row = cur.fetchone()


    conn.commit()

    cur.close()
    conn.close()


    if not row:
        return None


    return {
        "telegram_id":
            int(
                row[0]
            ),

        "fixture_id":
            int(
                row[1]
            ),

        "match":
            row[2],

        "kickoff_at":
            row[3]
    }


def reset_notification(
    telegram_id,
    fixture_id
):

    try:

        conn = get_db()
        cur = conn.cursor()


        cur.execute("""
            UPDATE match_favorites

            SET
                notification_sent = FALSE,
                updated_at = NOW()

            WHERE
                telegram_id = %s
                AND
                fixture_id = %s
                AND
                kickoff_at > NOW()
        """, (
            telegram_id,
            fixture_id
        ))


        conn.commit()

        cur.close()
        conn.close()


    except Exception:

        pass


def process_due_notifications():

    processed = 0


    while processed < 100:

        item = claim_due_notification()


        if not item:
            break


        now = datetime.now(
            timezone.utc
        )


        minutes_left = max(
            1,

            round(
                (
                    item[
                        "kickoff_at"
                    ]
                    -
                    now
                ).total_seconds()
                /
                60
            )
        )


        message = (
            "⏰ Скоро матч!\n\n"
            f"⚽ {item['match']}\n"
            f"🕒 Начало примерно через "
            f"{minutes_left} мин.\n\n"
            "⭐ Матч находится в твоём "
            "избранном BetCoin."
        )


        try:

            send_telegram_message(
                item[
                    "telegram_id"
                ],
                message
            )


        except Exception as error:

            print(
                "Telegram notification error:",
                error
            )


            reset_notification(
                item[
                    "telegram_id"
                ],
                item[
                    "fixture_id"
                ]
            )


        processed += 1


def notification_worker():

    time.sleep(
        10
    )


    while True:

        try:

            process_due_notifications()

        except Exception as error:

            print(
                "Notification worker error:",
                error
            )


        time.sleep(
            NOTIFICATION_CHECK_SECONDS
        )


def start_notification_worker():

    global notification_worker_started


    with notification_worker_lock:

        if notification_worker_started:
            return


        notification_worker_started = True


        thread = threading.Thread(
            target=
                notification_worker,

            daemon=
                True
        )


        thread.start()


# =========================================================
# ROOT
# =========================================================

@app.route("/")
def root():

    try:

        init_database()
        database_ok = True

    except Exception:

        database_ok = False


    return jsonify({

        "status":
            "ok",

        "message":
            "BetCoin server is working",

        "database":
            database_ok,

        "provider":
            "5DollarFootballAPI Pro",

        "logo_provider":
            "football-data.org",

        "automatic_team_logos":
            True,

        "league_count":
            len(
                LEAGUES
            ),

        "leagues":
            LEAGUES,

        "parlays":
            True,

        "favorites":
            True,

        "notifications":
            True,

        "notification_minutes_before":
            NOTIFICATION_MINUTES_BEFORE
    })


# =========================================================
# LEAGUES ROUTE
# =========================================================

@app.route(
    "/api/leagues"
)
def api_leagues():

    result = []


    for key, value in LEAGUES.items():

        result.append({

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
                ]
        })


    return jsonify({
        "success":
            True,

        "count":
            len(
                result
            ),

        "leagues":
            result
    })


# =========================================================
# MATCHES
# =========================================================

@app.route(
    "/api/matches"
)
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
            str(
                request.args.get(
                    "refresh",
                    "0"
                )
            )
            ==
            "1"
        )


        if (
            not league_key
            or
            league_key == "top5"
        ):

            fixtures = load_default_fixtures(
                force
            )


        elif league_key in LEAGUES:

            fixtures = load_league_fixtures(
                league_key,
                force
            )


        else:

            return jsonify({
                "success":
                    False,

                "error":
                    "Неизвестная лига"
            }), 400


        logo_count = 0


        for match in fixtures:

            if match.get(
                "home_logo"
            ):

                logo_count += 1


            if match.get(
                "away_logo"
            ):

                logo_count += 1


        return jsonify({

            "success":
                True,

            "league":
                (
                    league_key
                    or
                    "top5"
                ),

            "count":
                len(
                    fixtures
                ),

            "logos_found":
                logo_count,

            "matches":
                fixtures
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


# =========================================================
# MATCH
# =========================================================

@app.route(
    "/api/match/<int:fixture_id>"
)
def api_match(
    fixture_id
):

    try:

        match = get_fixture(
            fixture_id,
            True
        )


        return jsonify({
            "success":
                True,

            **match
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


# =========================================================
# SESSION
# =========================================================

@app.route(
    "/api/session",
    methods=[
        "POST"
    ]
)
def api_session():

    telegram_user, error = (
        require_telegram_user()
    )


    if error:
        return error


    try:

        user = get_or_create_user(
            telegram_user
        )


        telegram_id = user[
            "telegram_id"
        ]


        settle_user_bets(
            telegram_id
        )


        settle_user_parlays(
            telegram_id
        )


        user = get_user_data(
            telegram_id
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


                seconds_left = max(
                    0,

                    int(
                        (
                            next_claim
                            -
                            now
                        ).total_seconds()
                    )
                )


        leaderboard = get_leaderboard(
            telegram_id,
            50
        )


        return jsonify({

            "success":
                True,

            "user": {

                "telegram_id":
                    user[
                        "telegram_id"
                    ],

                "first_name":
                    user[
                        "first_name"
                    ],

                "username":
                    user[
                        "username"
                    ]
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
                    leaderboard[
                        "my_rank"
                    ]
            },

            "daily_reward": {

                "amount":
                    300,

                "available":
                    available,

                "seconds_left":
                    seconds_left,

                "next_claim":
                    (
                        next_claim.isoformat()
                        if next_claim
                        else None
                    )
            }
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


# =========================================================
# CREATE BET
# =========================================================

@app.route(
    "/api/bets",
    methods=[
        "POST"
    ]
)
def api_bets():

    telegram_user, error = (
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


    except Exception:

        return jsonify({
            "success":
                False,

            "error":
                "Некорректные данные ставки"
        }), 400


    if (
        amount <= 0
        or
        not selection
    ):

        return jsonify({
            "success":
                False,

            "error":
                "Некорректные данные ставки"
        }), 400


    try:

        canonical = resolve_canonical_bet(
            fixture_id,
            selection
        )


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
                (
                    "Не удалось проверить "
                    f"коэффициент: {error}"
                )
        }), 503


    try:

        user = get_or_create_user(
            telegram_user
        )


        telegram_id = user[
            "telegram_id"
        ]


        conn = get_db()
        cur = conn.cursor()


        ensure_daily_tasks(
            telegram_id,
            cur,
            True
        )


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
                status,
                settled,
                provider
            )

            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'Активна',
                FALSE,
                'five-dollar'
            )

            RETURNING id
        """, (
            telegram_id,

            canonical[
                "fixture_id"
            ],

            canonical[
                "match"
            ],

            canonical[
                "selection"
            ],

            odd,
            amount,
            possible
        ))


        bet_id = cur.fetchone()[0]


        xp_result = add_xp(
            telegram_id,
            10,
            cur
        )


        increment_daily_bet(
            telegram_id,
            cur
        )


        cur.execute("""
            SELECT balance

            FROM users

            WHERE telegram_id = %s
        """, (
            telegram_id,
        ))


        final_balance = int(
            cur.fetchone()[0]
        )


        conn.commit()

        cur.close()
        conn.close()


        leaderboard = get_leaderboard(
            telegram_id,
            50
        )


        return jsonify({

            "success":
                True,

            "bet_id":
                bet_id,

            "balance":
                final_balance,

            "odd":
                odd,

            "possible":
                possible,

            "xp_gained":
                10,

            **xp_result,

            "bets":
                get_user_bets(
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

            "my_rank":
                leaderboard[
                    "my_rank"
                ]
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


# =========================================================
# CREATE PARLAY
# =========================================================

@app.route(
    "/api/parlays",
    methods=[
        "POST"
    ]
)
def api_parlays():

    telegram_user, error = (
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


    except Exception:

        return jsonify({
            "success":
                False,

            "error":
                "Некорректный экспресс"
        }), 400


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

        return jsonify({
            "success":
                False,

            "error":
                "В экспрессе должно быть минимум 2 события"
        }), 400


    if len(
        legs
    ) > 15:

        return jsonify({
            "success":
                False,

            "error":
                "Максимум 15 событий в экспрессе"
        }), 400


    validated = []
    seen = set()


    try:

        for leg in legs:

            fixture_id = int(
                leg.get(
                    "fixture_id"
                )
            )


            selection = str(
                leg.get(
                    "selection",
                    ""
                )
            ).strip()


            if fixture_id in seen:

                raise ValueError(
                    "Нельзя добавить два исхода одного матча"
                )


            seen.add(
                fixture_id
            )


            validated.append(
                resolve_canonical_bet(
                    fixture_id,
                    selection
                )
            )


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
                (
                    "Не удалось проверить "
                    f"экспресс: {error}"
                )
        }), 503


    try:

        user = get_or_create_user(
            telegram_user
        )


        telegram_id = user[
            "telegram_id"
        ]


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


        conn = get_db()
        cur = conn.cursor()


        ensure_daily_tasks(
            telegram_id,
            cur,
            True
        )


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
                possible,
                status,
                settled
            )

            VALUES (
                %s,
                %s,
                %s,
                %s,
                'Активна',
                FALSE
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
                    status,
                    provider
                )

                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'Активна',
                    'five-dollar'
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
                ]
            ))


        xp_result = add_xp(
            telegram_id,
            10,
            cur
        )


        increment_daily_bet(
            telegram_id,
            cur
        )


        cur.execute("""
            SELECT balance

            FROM users

            WHERE telegram_id = %s
        """, (
            telegram_id,
        ))


        final_balance = int(
            cur.fetchone()[0]
        )


        conn.commit()

        cur.close()
        conn.close()


        leaderboard = get_leaderboard(
            telegram_id,
            50
        )


        return jsonify({

            "success":
                True,

            "parlay_id":
                parlay_id,

            "balance":
                final_balance,

            "total_odd":
                total_odd,

            "possible":
                possible,

            "legs":
                validated,

            "xp_gained":
                10,

            **xp_result,

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

            "my_rank":
                leaderboard[
                    "my_rank"
                ],

            "parlays":
                get_user_parlays(
                    telegram_id
                )
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


# =========================================================
# FAVORITES ROUTES
# =========================================================

@app.route(
    "/api/favorites",
    methods=[
        "POST"
    ]
)
def api_favorites():

    telegram_user, error = (
        require_telegram_user()
    )


    if error:
        return error


    user = get_or_create_user(
        telegram_user
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

        "notification_minutes_before":
            NOTIFICATION_MINUTES_BEFORE
    })


@app.route(
    "/api/favorites/toggle",
    methods=[
        "POST"
    ]
)
def api_favorites_toggle():

    telegram_user, error = (
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


        favorite = bool(
            body.get(
                "favorite",
                True
            )
        )


        user = get_or_create_user(
            telegram_user
        )


        telegram_id = user[
            "telegram_id"
        ]


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
                )
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
    "/api/favorites/sync",
    methods=[
        "POST"
    ]
)
def api_favorites_sync():

    telegram_user, error = (
        require_telegram_user()
    )


    if error:
        return error


    body = request.get_json(
        silent=True
    ) or {}


    fixture_ids = body.get(
        "fixture_ids",
        []
    )


    if not isinstance(
        fixture_ids,
        list
    ):

        return jsonify({
            "success":
                False,

            "error":
                "Некорректный список избранного"
        }), 400


    try:

        user = get_or_create_user(
            telegram_user
        )


        telegram_id = user[
            "telegram_id"
        ]


        wanted = []


        for value in fixture_ids[:100]:

            try:

                fixture_id = int(
                    value
                )

            except Exception:

                continue


            if fixture_id not in wanted:

                wanted.append(
                    fixture_id
                )


        for fixture_id in wanted:

            try:

                add_favorite_match(
                    telegram_id,
                    fixture_id
                )

            except Exception:

                pass


        return jsonify({

            "success":
                True,

            "favorites":
                get_user_favorites(
                    telegram_id
                )
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


# =========================================================
# LEADERBOARD
# =========================================================

@app.route(
    "/api/leaderboard",
    methods=[
        "POST"
    ]
)
def api_leaderboard():

    telegram_user, error = (
        require_telegram_user()
    )


    if error:
        return error


    user = get_or_create_user(
        telegram_user
    )


    data = get_leaderboard(
        user[
            "telegram_id"
        ],
        50
    )


    return jsonify({
        "success":
            True,

        **data
    })


# =========================================================
# DAILY REWARD
# =========================================================

@app.route(
    "/api/daily-reward",
    methods=[
        "POST"
    ]
)
def api_daily_reward():

    telegram_user, error = (
        require_telegram_user()
    )


    if error:
        return error


    try:

        user = get_or_create_user(
            telegram_user
        )


        telegram_id = user[
            "telegram_id"
        ]


        conn = get_db()
        cur = conn.cursor()


        cur.execute("""
            SELECT
                balance,
                last_daily_claim

            FROM users

            WHERE telegram_id = %s

            FOR UPDATE
        """, (
            telegram_id,
        ))


        row = cur.fetchone()

        last_claim = row[1]

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

            next_claim = (
                last_claim
                +
                timedelta(
                    hours=24
                )
            )


            conn.rollback()

            cur.close()
            conn.close()


            return jsonify({

                "success":
                    False,

                "error":
                    "Бонус уже получен",

                "seconds_left":
                    max(
                        0,

                        int(
                            (
                                next_claim
                                -
                                now
                            ).total_seconds()
                        )
                    )
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


        xp_result = add_xp(
            telegram_id,
            15,
            cur
        )


        cur.execute("""
            SELECT balance

            FROM users

            WHERE telegram_id = %s
        """, (
            telegram_id,
        ))


        final_balance = int(
            cur.fetchone()[0]
        )


        conn.commit()

        cur.close()
        conn.close()


        return jsonify({

            "success":
                True,

            "reward":
                300,

            "balance":
                final_balance,

            "xp_gained":
                15,

            **xp_result,

            "seconds_left":
                86400
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


# =========================================================
# TASK CLAIM
# =========================================================

@app.route(
    "/api/tasks/claim",
    methods=[
        "POST"
    ]
)
def api_tasks_claim():

    telegram_user, error = (
        require_telegram_user()
    )


    if error:
        return error


    body = request.get_json(
        silent=True
    ) or {}


    task_key = str(
        body.get(
            "task_key",
            ""
        )
    ).strip()


    if task_key not in (
        "login",
        "bets_3",
        "win_1"
    ):

        return jsonify({
            "success":
                False,

            "error":
                "Неизвестное задание"
        }), 400


    try:

        user = get_or_create_user(
            telegram_user
        )


        telegram_id = user[
            "telegram_id"
        ]


        conn = get_db()
        cur = conn.cursor()


        ensure_daily_tasks(
            telegram_id,
            cur,
            True
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

            FOR UPDATE
        """, (
            telegram_id,
            task_date()
        ))


        row = cur.fetchone()


        if task_key == "login":

            completed = bool(
                row[0]
            )

            claimed = bool(
                row[3]
            )

            reward_type = "xp"

            reward = 50

            column = "login_claimed"


        elif task_key == "bets_3":

            completed = (
                int(
                    row[1]
                    or
                    0
                )
                >=
                3
            )

            claimed = bool(
                row[4]
            )

            reward_type = "coins"

            reward = 100

            column = "bets_claimed"


        else:

            completed = (
                int(
                    row[2]
                    or
                    0
                )
                >=
                1
            )

            claimed = bool(
                row[5]
            )

            reward_type = "coins"

            reward = 150

            column = "win_claimed"


        if not completed:

            conn.rollback()

            cur.close()
            conn.close()


            return jsonify({
                "success":
                    False,

                "error":
                    "Задание ещё не выполнено"
            }), 400


        if claimed:

            conn.rollback()

            cur.close()
            conn.close()


            return jsonify({
                "success":
                    False,

                "error":
                    "Награда уже получена"
            }), 400


        cur.execute(
            f"""
            UPDATE daily_tasks

            SET
                {column} = TRUE

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


        if reward_type == "coins":

            cur.execute("""
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


        else:

            add_xp(
                telegram_id,
                reward,
                cur
            )


        conn.commit()

        cur.close()
        conn.close()


        fresh_user = get_user_data(
            telegram_id
        )


        return jsonify({

            "success":
                True,

            "reward":
                reward,

            "reward_type":
                reward_type,

            "balance":
                int(
                    fresh_user[
                        "balance"
                    ]
                ),

            **xp_info(
                fresh_user[
                    "xp"
                ]
            ),

            "tasks":
                get_daily_tasks(
                    telegram_id,
                    True
                )
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


# =========================================================
# ACHIEVEMENT CLAIM
# =========================================================

@app.route(
    "/api/achievements/claim",
    methods=[
        "POST"
    ]
)
def api_achievement_claim():

    telegram_user, error = (
        require_telegram_user()
    )


    if error:
        return error


    body = request.get_json(
        silent=True
    ) or {}


    key = str(
        body.get(
            "achievement_key",
            ""
        )
    ).strip()


    achievement = next(
        (
            item
            for item
            in ACHIEVEMENTS
            if
            item[
                "key"
            ]
            ==
            key
        ),
        None
    )


    if not achievement:

        return jsonify({
            "success":
                False,

            "error":
                "Неизвестное достижение"
        }), 400


    user = get_or_create_user(
        telegram_user
    )


    telegram_id = user[
        "telegram_id"
    ]


    current = next(
        (
            item
            for item
            in get_achievements(
                telegram_id
            )
            if
            item[
                "key"
            ]
            ==
            key
        ),
        None
    )


    if (
        not current
        or
        not current[
            "completed"
        ]
    ):

        return jsonify({
            "success":
                False,

            "error":
                "Достижение ещё не выполнено"
        }), 400


    if current[
        "claimed"
    ]:

        return jsonify({
            "success":
                False,

            "error":
                "Награда уже получена"
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

        ON CONFLICT (
            telegram_id,
            achievement_key
        )

        DO NOTHING
    """, (
        telegram_id,
        key
    ))


    if cur.rowcount != 1:

        conn.rollback()

        cur.close()
        conn.close()


        return jsonify({
            "success":
                False,

            "error":
                "Награда уже получена"
        }), 400


    reward = int(
        achievement[
            "reward"
        ]
    )


    cur.execute("""
        UPDATE users

        SET
            balance =
                balance + %s,

            updated_at =
                NOW()

        WHERE telegram_id = %s

        RETURNING balance
    """, (
        reward,
        telegram_id
    ))


    balance = int(
        cur.fetchone()[0]
    )


    conn.commit()

    cur.close()
    conn.close()


    return jsonify({

        "success":
            True,

        "reward":
            reward,

        "balance":
            balance,

        "achievements":
            get_achievements(
                telegram_id
            )
    })


# =========================================================
# SETTLE
# =========================================================

@app.route(
    "/api/settle",
    methods=[
        "POST"
    ]
)
def api_settle():

    telegram_user, error = (
        require_telegram_user()
    )


    if error:
        return error


    user = get_or_create_user(
        telegram_user
    )


    telegram_id = user[
        "telegram_id"
    ]


    settle_user_bets(
        telegram_id
    )


    settle_user_parlays(
        telegram_id
    )


    user = get_user_data(
        telegram_id
    )


    return jsonify({

        "success":
            True,

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
            )
    })


# =========================================================
# LOGO DEBUG
# =========================================================

@app.route(
    "/api/logo-status"
)
def api_logo_status():

    try:

        result = {}


        for key, config in LEAGUES.items():

            db_logos, newest = (
                read_league_logos_from_db(
                    key
                )
            )


            result[
                key
            ] = {

                "name":
                    config[
                        "name"
                    ],

                "football_data_code":
                    config.get(
                        "football_data_code"
                    ),

                "cached_logos":
                    len(
                        db_logos
                    ),

                "updated_at":
                    (
                        newest.isoformat()
                        if newest
                        else None
                    )
            }


        return jsonify({
            "success":
                True,

            "football_data_token":
                bool(
                    FOOTBALL_TOKEN
                ),

            "leagues":
                result
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


# =========================================================
# START
# =========================================================

try:

    init_database()

except Exception as error:

    print(
        "Database startup error:",
        error
    )


start_notification_worker()


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )


    app.run(
        host="0.0.0.0",
        port=port
    )
