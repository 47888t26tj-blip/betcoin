import os
import re
import time
import json
import hmac
import hashlib
import secrets
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


FIVE_API_URL = (
    "https://api.5dollarfootballapi.com"
)


FOOTBALL_DATA_URL = (
    "https://api.football-data.org/v4"
)


LEAGUES = {

    "premier_league": {
        "ids": [
            4160026622
        ],
        "name":
            "Premier League",
        "short_name":
            "АПЛ",
        "country":
            "England",
        "flag":
            "🏴",
        "football_data_code":
            "PL"
    },

    "la_liga": {
        "ids": [
            4212821298
        ],
        "name":
            "La Liga",
        "short_name":
            "Ла Лига",
        "country":
            "Spain",
        "flag":
            "🇪🇸",
        "football_data_code":
            "PD"
    },

    "serie_a": {
        "ids": [
            3405541143
        ],
        "name":
            "Serie A",
        "short_name":
            "Серия А",
        "country":
            "Italy",
        "flag":
            "🇮🇹",
        "football_data_code":
            "SA"
    },

    "bundesliga": {
        "ids": [
            686337048
        ],
        "name":
            "Bundesliga",
        "short_name":
            "Бундеслига",
        "country":
            "Germany",
        "flag":
            "🇩🇪",
        "football_data_code":
            "BL1"
    },

    "ligue_1": {
        "ids": [
            3614399544
        ],
        "name":
            "Ligue 1",
        "short_name":
            "Лига 1",
        "country":
            "France",
        "flag":
            "🇫🇷",
        "football_data_code":
            "FL1"
    },

    "champions_league": {
        "ids": [
            2187079931,
            1318331555
        ],
        "name":
            "UEFA Champions League",
        "short_name":
            "Лига чемпионов",
        "country":
            "Europe",
        "flag":
            "🏆",
        "football_data_code":
            "CL"
    },

    "europa_league": {
        "ids": [
            2629778952,
            2515803737
        ],
        "name":
            "UEFA Europa League",
        "short_name":
            "Лига Европы",
        "country":
            "Europe",
        "flag":
            "🟠",
        "football_data_code":
            "EL"
    },

    "conference_league": {
        "ids": [
            51996766,
            2009834352
        ],
        "name":
            "UEFA Conference League",
        "short_name":
            "Лига конференций",
        "country":
            "Europe",
        "flag":
            "🟢",
        "football_data_code":
            None
    },

    "championship": {
        "ids": [
            1161691669
        ],
        "name":
            "Championship",
        "short_name":
            "Чемпионшип",
        "country":
            "England",
        "flag":
            "🏴",
        "football_data_code":
            "ELC"
    },

    "eredivisie": {
        "ids": [
            137325260
        ],
        "name":
            "Eredivisie",
        "short_name":
            "Эредивизи",
        "country":
            "Netherlands",
        "flag":
            "🇳🇱",
        "football_data_code":
            "DED"
    },

    "primeira_liga": {
        "ids": [
            650171110
        ],
        "name":
            "Primeira Liga",
        "short_name":
            "Португалия",
        "country":
            "Portugal",
        "flag":
            "🇵🇹",
        "football_data_code":
            "PPL"
    },

    "mls": {
        "ids": [
            2221499861
        ],
        "name":
            "Major League Soccer",
        "short_name":
            "MLS",
        "country":
            "USA",
        "flag":
            "🇺🇸",
        "football_data_code":
            None
    },

    "saudi_pro_league": {
        "ids": [
            1796782054
        ],
        "name":
            "Saudi Pro League",
        "short_name":
            "Саудовская лига",
        "country":
            "Saudi Arabia",
        "flag":
            "🇸🇦",
        "football_data_code":
            None
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
            int(
                league_id
            )
        ] = league_key


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
    4.5
]


WHEEL_COOLDOWN_HOURS = 24


WHEEL_REWARDS = [

    {
        "type":
            "coins",
        "value":
            50,
        "weight":
            3000,
        "label":
            "+50 🪙"
    },

    {
        "type":
            "coins",
        "value":
            100,
        "weight":
            2800,
        "label":
            "+100 🪙"
    },

    {
        "type":
            "coins",
        "value":
            200,
        "weight":
            2200,
        "label":
            "+200 🪙"
    },

    {
        "type":
            "coins",
        "value":
            500,
        "weight":
            1200,
        "label":
            "+500 🪙"
    },

    {
        "type":
            "coins",
        "value":
            1000,
        "weight":
            500,
        "label":
            "+1000 🪙"
    },

    {
        "type":
            "xp",
        "value":
            100,
        "weight":
            300,
        "label":
            "+100 XP"
    }
]


PREDICTION_REWARD_COINS = 200

PREDICTION_REWARD_XP = 25

PREDICTION_LOOKAHEAD_DAYS = 7


# ==========================================
# 🔥 СЕРИЯ ВХОДОВ
# ==========================================

LOGIN_STREAK_REWARDS = {

    1: {
        "coins": 100,
        "xp": 0
    },

    2: {
        "coins": 150,
        "xp": 0
    },

    3: {
        "coins": 200,
        "xp": 0
    },

    4: {
        "coins": 250,
        "xp": 0
    },

    5: {
        "coins": 300,
        "xp": 0
    },

    6: {
        "coins": 400,
        "xp": 0
    },

    7: {
        "coins": 700,
        "xp": 100
    }
}


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

    "cologne":
        "1 fc koln",

    "koln":
        "1 fc koln",

    "fc koln":
        "1 fc koln",

    "rennes":
        "stade rennais",

    "benfica":
        "sl benfica",

    "sporting lisbon":
        "sporting cp",

    "porto":
        "fc porto",

    "braga":
        "sc braga",

    "salzburg":
        "red bull salzburg",

    "rb salzburg":
        "red bull salzburg",

    "sparta prague":
        "sparta praha",

    "lech":
        "lech poznan",

    "omonia":
        "omonia nicosia",

    "celje":
        "nk celje",

    "hapoel":
        "hapoel beer sheva",

    "aek":
        "aek athens",

    "inter milan":
        "inter",

    "internazionale":
        "inter",

    "ac milan":
        "milan",

    "fc barcelona":
        "barcelona",

    "real madrid cf":
        "real madrid",

    "atletico de madrid":
        "atletico madrid"
}


ACHIEVEMENTS = [

    {
        "key":
            "bets_10",

        "title":
            "Начало положено",

        "description":
            "Сделать 10 ставок",

        "target":
            10,

        "reward":
            200
    },

    {
        "key":
            "wins_5",

        "title":
            "На победной волне",

        "description":
            "Выиграть 5 ставок",

        "target":
            5,

        "reward":
            300
    },

    {
        "key":
            "level_5",

        "title":
            "Опытный игрок",

        "description":
            "Достичь 5 уровня",

        "target":
            5,

        "reward":
            500
    },

    {
        "key":
            "xp_500",

        "title":
            "500 XP",

        "description":
            "Набрать 500 XP",

        "target":
            500,

        "reward":
            400
    },

    {
        "key":
            "high_odd_win",

        "title":
            "Риск оправдан",

        "description":
            "Выиграть ставку с коэффициентом 3.00+",

        "target":
            1,

        "reward":
            350
    }
]


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
        CREATE TABLE IF NOT EXISTS bets (

            id SERIAL PRIMARY KEY,

            telegram_id BIGINT NOT NULL
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            fixture_id BIGINT NOT NULL,

            match_name TEXT NOT NULL,

            selection TEXT NOT NULL,

            odd DOUBLE PRECISION NOT NULL,

            amount INTEGER NOT NULL,

            possible INTEGER NOT NULL,

            status TEXT NOT NULL
                DEFAULT 'Активна',

            settled BOOLEAN NOT NULL
                DEFAULT FALSE,

            score TEXT,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            provider TEXT NOT NULL
                DEFAULT 'five-dollar',

            result_notified BOOLEAN NOT NULL
                DEFAULT FALSE,

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
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            amount INTEGER NOT NULL,

            total_odd DOUBLE PRECISION NOT NULL,

            possible INTEGER NOT NULL,

            status TEXT NOT NULL
                DEFAULT 'Активна',

            settled BOOLEAN NOT NULL
                DEFAULT FALSE,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            settled_at TIMESTAMPTZ,

            result_notified BOOLEAN NOT NULL
                DEFAULT FALSE,

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
                REFERENCES parlays(
                    id
                )
                ON DELETE CASCADE,

            fixture_id BIGINT NOT NULL,

            match_name TEXT NOT NULL,

            selection TEXT NOT NULL,

            odd DOUBLE PRECISION NOT NULL,

            status TEXT NOT NULL
                DEFAULT 'Активна',

            score TEXT,

            provider TEXT NOT NULL
                DEFAULT 'five-dollar',

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
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            task_date DATE NOT NULL,

            login_done BOOLEAN NOT NULL
                DEFAULT FALSE,

            bets_count INTEGER NOT NULL
                DEFAULT 0,

            wins_count INTEGER NOT NULL
                DEFAULT 0,

            login_claimed BOOLEAN NOT NULL
                DEFAULT FALSE,

            bets_claimed BOOLEAN NOT NULL
                DEFAULT FALSE,

            win_claimed BOOLEAN NOT NULL
                DEFAULT FALSE,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                telegram_id,
                task_date
            )
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS achievement_claims (

            telegram_id BIGINT NOT NULL
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            achievement_key TEXT NOT NULL,

            claimed_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                telegram_id,
                achievement_key
            )
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS match_favorites (

            telegram_id BIGINT NOT NULL
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            fixture_id BIGINT NOT NULL,

            match_name TEXT NOT NULL,

            kickoff_at TIMESTAMPTZ NOT NULL,

            notifications_enabled BOOLEAN NOT NULL
                DEFAULT TRUE,

            notification_sent BOOLEAN NOT NULL
                DEFAULT FALSE,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            updated_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                telegram_id,
                fixture_id
            )
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorite_teams (

            telegram_id BIGINT NOT NULL
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            team_name TEXT NOT NULL,

            normalized_name TEXT NOT NULL,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                telegram_id,
                normalized_name
            )
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorite_team_notifications (

            telegram_id BIGINT NOT NULL
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            fixture_id BIGINT NOT NULL,

            team_name TEXT,

            sent_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

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

            source TEXT NOT NULL
                DEFAULT 'football-data',

            updated_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                league_key,
                normalized_name
            )
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (

            code TEXT PRIMARY KEY,

            reward_coins INTEGER NOT NULL
                DEFAULT 0,

            reward_xp INTEGER NOT NULL
                DEFAULT 0,

            max_uses INTEGER,

            uses_count INTEGER NOT NULL
                DEFAULT 0,

            active BOOLEAN NOT NULL
                DEFAULT TRUE,

            expires_at TIMESTAMPTZ,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW()
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS promo_redemptions (

            telegram_id BIGINT NOT NULL
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            code TEXT NOT NULL
                REFERENCES promo_codes(
                    code
                )
                ON DELETE CASCADE,

            reward_coins INTEGER NOT NULL
                DEFAULT 0,

            reward_xp INTEGER NOT NULL
                DEFAULT 0,

            redeemed_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                telegram_id,
                code
            )
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS wheel_spins (

            telegram_id BIGINT PRIMARY KEY
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            last_spin_at TIMESTAMPTZ,

            last_reward_type TEXT,

            last_reward_value INTEGER,

            updated_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW()
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS wheel_spin_history (

            id SERIAL PRIMARY KEY,

            telegram_id BIGINT NOT NULL
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            reward_type TEXT NOT NULL,

            reward_value INTEGER NOT NULL,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW()
        )
    """)


    # ==========================================
    # 🎯 УГАДАЙ ИСХОД
    # ==========================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS prediction_game_rounds (

            game_date DATE PRIMARY KEY,

            fixture_id BIGINT NOT NULL,

            match_name TEXT NOT NULL,

            home_team TEXT NOT NULL,

            away_team TEXT NOT NULL,

            league_name TEXT,

            kickoff_at TIMESTAMPTZ NOT NULL,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW()
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS prediction_game_picks (

            telegram_id BIGINT NOT NULL
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            game_date DATE NOT NULL,

            fixture_id BIGINT NOT NULL,

            prediction TEXT NOT NULL,

            settled BOOLEAN NOT NULL
                DEFAULT FALSE,

            won BOOLEAN,

            final_score TEXT,

            actual_result TEXT,

            reward_coins INTEGER NOT NULL
                DEFAULT 0,

            reward_xp INTEGER NOT NULL
                DEFAULT 0,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            settled_at TIMESTAMPTZ,

            PRIMARY KEY (
                telegram_id,
                game_date
            )
        )
    """)


    # ==========================================
    # 🔥 7-ДНЕВНАЯ СЕРИЯ ВХОДОВ
    # ==========================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_streaks (

            telegram_id BIGINT PRIMARY KEY
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            streak_day INTEGER NOT NULL
                DEFAULT 0,

            last_claim_date DATE,

            updated_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW()
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_streak_claims (

            telegram_id BIGINT NOT NULL
                REFERENCES users(
                    telegram_id
                )
                ON DELETE CASCADE,

            claim_date DATE NOT NULL,

            streak_day INTEGER NOT NULL,

            reward_coins INTEGER NOT NULL
                DEFAULT 0,

            reward_xp INTEGER NOT NULL
                DEFAULT 0,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                telegram_id,
                claim_date
            )
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_login_streak_claims_user

        ON login_streak_claims (
            telegram_id,
            claim_date DESC
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_prediction_game_picks_due

        ON prediction_game_picks (
            settled,
            fixture_id
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_prediction_game_picks_user

        ON prediction_game_picks (
            telegram_id,
            game_date DESC
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_bets_user

        ON bets (
            telegram_id
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_bets_settlement_due

        ON bets (
            settled,
            status,
            kickoff_at
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_bets_notification

        ON bets (
            settled,
            result_notified
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_parlays_user

        ON parlays (
            telegram_id
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_parlay_legs_due

        ON parlay_legs (
            kickoff_at,
            status
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_parlays_notification

        ON parlays (
            settled,
            result_notified
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


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_favorite_teams_name

        ON favorite_teams (
            normalized_name
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
        idx_wheel_history_user

        ON wheel_spin_history (
            telegram_id,
            created_at DESC
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
        ON CONFLICT (
            code
        )
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
        ON CONFLICT (
            code
        )
        DO NOTHING
    """)


    conn.commit()

    cur.close()

    conn.close()


    database_ready = True


def normalize_club_name(
    name
):

    value = str(
        name
        or
        ""
    ).strip().lower()


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


def simplified_club_name(
    name
):

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
        "the"
    }


    return " ".join(
        word
        for word
        in normalize_club_name(
            name
        ).split()
        if word not in ignored
    )


def alias_club_name(
    name
):

    normalized = normalize_club_name(
        name
    )


    simplified = simplified_club_name(
        name
    )


    return (
        TEAM_NAME_ALIASES.get(
            normalized
        )
        or
        TEAM_NAME_ALIASES.get(
            simplified
        )
        or
        normalized
    )


def favorite_team_key(
    name
):

    return (
        simplified_club_name(
            alias_club_name(
                name
            )
        )
        or
        normalize_club_name(
            name
        )
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

            result[
                row[0]
            ] = {
                "name":
                    row[1],

                "logo":
                    row[2]
            }


        cur.close()

        conn.close()


    except Exception as error:

        print(
            "Logo cache error:",
            error
        )


    global_logo_cache = result


def find_logo_fast(
    team_name
):

    if not global_logo_cache:

        return ""


    attempts = [

        normalize_club_name(
            team_name
        ),

        simplified_club_name(
            team_name
        ),

        alias_club_name(
            team_name
        ),

        simplified_club_name(
            alias_club_name(
                team_name
            )
        )
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


        if len(
            key_simple
        ) < 5:

            continue


        for attempt in attempts:

            attempt_simple = simplified_club_name(
                attempt
            )


            if len(
                attempt_simple
            ) < 5:

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

            team.get(
                "name"
            ),

            team.get(
                "shortName"
            ),

            team.get(
                "tla"
            )
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
        tg_user[
            "id"
        ]
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


def calculate_level(
    xp
):

    return (
        int(
            xp
            or
            0
        )
        //
        100
        +
        1
    )


def get_league(
    level
):

    if level >= 30:

        return {
            "key":
                "master",

            "name":
                "Мастер",

            "icon":
                "👑",

            "min_level":
                30,

            "next_level":
                None
        }


    if level >= 20:

        return {
            "key":
                "diamond",

            "name":
                "Алмаз",

            "icon":
                "💎",

            "min_level":
                20,

            "next_level":
                30
        }


    if level >= 10:

        return {
            "key":
                "gold",

            "name":
                "Золото",

            "icon":
                "🥇",

            "min_level":
                10,

            "next_level":
                20
        }


    if level >= 5:

        return {
            "key":
                "silver",

            "name":
                "Серебро",

            "icon":
                "🥈",

            "min_level":
                5,

            "next_level":
                10
        }


    return {
        "key":
            "bronze",

        "name":
            "Бронза",

        "icon":
            "🥉",

        "min_level":
            1,

        "next_level":
            5
    }


def xp_info(
    xp
):

    xp = int(
        xp
        or
        0
    )


    level = calculate_level(
        xp
    )


    current = (
        xp
        %
        100
    )


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
            100
            -
            current
    }


def add_xp(
    telegram_id,
    amount,
    cursor=None
):

    own_connection = (
        cursor
        is
        None
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
        else
        0
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

            updated_at =
                NOW()

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


        if (
            level_number
            %
            5
            ==
            0
        ):

            level_reward += 500


        reward += level_reward


    if reward > 0:

        cursor.execute("""
            UPDATE users

            SET
                balance =
                    balance
                    +
                    %s,

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
        cursor
        is
        None
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
                bets_count
                +
                1

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
                wins_count
                +
                1

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
            "key":
                "login",

            "title":
                "Зайти в приложение",

            "description":
                "Открой BetCoin сегодня",

            "progress":
                1
                if row[0]
                else
                0,

            "target":
                1,

            "completed":
                bool(
                    row[0]
                ),

            "claimed":
                bool(
                    row[3]
                ),

            "reward_type":
                "xp",

            "reward":
                50
        },

        {
            "key":
                "bets_3",

            "title":
                "Сделать 3 ставки",

            "description":
                "Сделай 3 ставки за сегодня",

            "progress":
                min(
                    int(
                        row[1]
                        or
                        0
                    ),
                    3
                ),

            "target":
                3,

            "completed":
                int(
                    row[1]
                    or
                    0
                )
                >=
                3,

            "claimed":
                bool(
                    row[4]
                ),

            "reward_type":
                "coins",

            "reward":
                100
        },

        {
            "key":
                "win_1",

            "title":
                "Выиграть 1 ставку",

            "description":
                "Получи один выигрыш сегодня",

            "progress":
                min(
                    int(
                        row[2]
                        or
                        0
                    ),
                    1
                ),

            "target":
                1,

            "completed":
                int(
                    row[2]
                    or
                    0
                )
                >=
                1,

            "claimed":
                bool(
                    row[5]
                ),

            "reward_type":
                "coins",

            "reward":
                150
        }
    ]


def five_headers():

    return {
        "Authorization":
            "Bearer "
            +
            FIVE_DOLLAR_FOOTBALL_API_KEY,

        "Accept":
            "application/json"
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

                headers=
                    five_headers(),

                params=
                    params
                    or
                    {},

                timeout=
                    20
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

                retry_after = response.headers.get(
                    "Retry-After"
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

                payload = response.text[
                    :300
                ]


            raise RuntimeError(
                "5DollarFootballAPI HTTP "
                +
                str(
                    response.status_code
                )
                +
                ": "
                +
                str(
                    payload
                )
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
            tzinfo=
                timezone.utc
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
        "btts"
    } & set(
        payload.keys()
    ):

        return [
            {
                "name":
                    "Bet 365",

                "slug":
                    "bet365",

                "odds":
                    payload
            }
        ]


    return []


def parse_odds_response(
    payload
):

    result = {
        "odds":
            None,

        "totals":
            {},

        "btts":
            None,

        "handicaps":
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
                )
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
                )
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
                    )
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

    league_id = (
        league.get(
            "id"
        )
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

    home_name = (
        home.get(
            "name",
            "Unknown"
        )
    )

    away_name = (
        away.get(
            "name",
            "Unknown"
        )
    )

    goals = (
        item.get(
            "goals"
        )
        or
        {}
    )

    parsed = (
        parse_odds_response(
            item.get(
                "odds"
            )
        )
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
            (
                home.get(
                    "logo"
                )
                or
                find_logo_fast(
                    home_name
                )
            ),

        "away_logo":
            (
                away.get(
                    "logo"
                )
                or
                find_logo_fast(
                    away_name
                )
            ),

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


def fetch_league_id_fixtures(
    league_key,
    league_id,
    start_ts,
    end_ts
):

    data = five_get(
        f"/v1/leagues/{league_id}/fixtures",
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

    result = []

    for item in (
        data.get(
            "data"
        )
        or
        []
    ):

        try:

            match = (
                make_match_from_item(
                    item,
                    league_key
                )
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

    cached = (
        league_fixture_cache.get(
            league_key
        )
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

    request_errors = []

    successful = 0

    ids = LEAGUES[
        league_key
    ][
        "ids"
    ]

    with ThreadPoolExecutor(
        max_workers=
            max(
                1,
                min(
                    2,
                    len(
                        ids
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
            in ids
        ]

        for future in as_completed(
            futures
        ):

            try:

                loaded_matches = (
                    future.result()
                )

                successful += 1

                result.extend(
                    loaded_matches
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

    if successful == 0:

        if (
            cached
            and
            cached.get(
                "data"
            )
            is not None
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

                else
                ""
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
                match
        }

    result = list(
        unique.values()
    )

    result.sort(
        key=
            lambda match:
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
        key=
            lambda match:
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

            fixture_id = (
                match.get(
                    "fixture_id"
                )
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

    cached = (
        fixture_detail_cache.get(
            key
        )
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

    cached = (
        odds_cache.get(
            key
        )
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
        f"/v1/fixtures/{int(fixture_id)}/odds"
    )

    parsed = (
        parse_odds_response(
            data
        )
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


def get_fixture(
    fixture_id,
    with_odds=True,
    force=False
):

    if not force:

        cached = (
            find_cached_fixture(
                fixture_id
            )
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

                    parsed = (
                        fetch_fixture_odds(
                            fixture_id
                        )
                    )

                    apply_parsed_odds_to_match(
                        match,
                        parsed
                    )

                except Exception:

                    pass

            return match

    data = five_get(
        f"/v1/fixtures/{int(fixture_id)}"
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

            parsed = (
                fetch_fixture_odds(
                    fixture_id
                )
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
            match
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
            f"Т{total_match.group(1)} {line}"
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
            if
            team_number
            ==
            1
            else
            "away"
        )

        line_key = (
            normalize_line_key(
                line
            )
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
            if
            line > 0
            else
            line_key
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

    kickoff = (
        parse_match_datetime(
            match.get(
                "date"
            )
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

        parsed = (
            fetch_fixture_odds(
                fixture_id,
                True
            )
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
            (
                f"{match['home']} — "
                f"{match['away']}"
            ),

        "selection":
            canonical,

        "odd":
            odd,

        "provider":
            "five-dollar",

        "kickoff_at":
            kickoff
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
            if
            home_score
            >
            away_score
            else
            "loss"
        )

    if selection == "X":

        return (
            "win"
            if
            home_score
            ==
            away_score
            else
            "loss"
        )

    if selection == "П2":

        return (
            "win"
            if
            away_score
            >
            home_score
            else
            "loss"
        )

    if selection == "ОЗ Да":

        return (
            "win"
            if
            home_score > 0
            and
            away_score > 0
            else
            "loss"
        )

    if selection == "ОЗ Нет":

        return (
            "win"
            if
            home_score == 0
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

        if (
            total_match.group(
                1
            )
            ==
            "Б"
        ):

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
        "fulltime"
    }


def live_status_flags(
    status,
    status_code=None
):

    value = (
        str(
            status
            or
            ""
        )
        .strip()
        .lower()
    )

    code = (
        str(
            status_code
            or
            ""
        )
        .strip()
        .lower()
    )

    finished = (
        is_finished_status(
            value
        )
        or
        code in {
            "ft",
            "finished",
            "ended"
        }
    )

    live = (
        not finished
        and
        (
            value in {
                "live",
                "inplay",
                "in_play",
                "first_half",
                "second_half",
                "halftime",
                "half_time"
            }
            or
            code in {
                "1h",
                "2h",
                "ht",
                "live"
            }
        )
    )

    return (
        live,
        finished
    )


def get_result(
    fixture_id
):

    key = str(
        int(
            fixture_id
        )
    )

    cached = (
        result_cache.get(
            key
        )
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
                data
        }

        return data

    except Exception as error:

        print(
            "Result fetch error:",
            fixture_id,
            error
        )

        return None


# =========================================================
# 🔥 СЕРИЯ ВХОДОВ
# =========================================================

def get_login_streak_status(
    telegram_id
):

    today = datetime.now(
        timezone.utc
    ).date()

    yesterday = (
        today
        -
        timedelta(
            days=1
        )
    )

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO login_streaks (
            telegram_id
        )
        VALUES (
            %s
        )
        ON CONFLICT (
            telegram_id
        )
        DO NOTHING
    """, (
        telegram_id,
    ))

    conn.commit()

    cur.execute("""
        SELECT
            streak_day,
            last_claim_date

        FROM login_streaks

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    row = cur.fetchone()

    cur.close()

    conn.close()

    current_day = int(
        row[0]
        or
        0
    )

    last_claim_date = (
        row[1]
        if row
        else
        None
    )

    claimed_today = (
        last_claim_date
        ==
        today
    )

    if claimed_today:

        next_day = (
            1
            if
            current_day >= 7
            else
            current_day + 1
        )

        available = False

        streak_broken = False

    elif (
        last_claim_date
        ==
        yesterday
    ):

        next_day = (
            1
            if
            current_day >= 7
            else
            current_day + 1
        )

        available = True

        streak_broken = False

    else:

        next_day = 1

        available = True

        streak_broken = (
            last_claim_date
            is not None
        )

    rewards = []

    for day in range(
        1,
        8
    ):

        reward = (
            LOGIN_STREAK_REWARDS[
                day
            ]
        )

        rewards.append({

            "day":
                day,

            "coins":
                int(
                    reward[
                        "coins"
                    ]
                ),

            "xp":
                int(
                    reward[
                        "xp"
                    ]
                ),

            "completed":
                (
                    claimed_today
                    and
                    day
                    <=
                    current_day
                ),

            "current":
                (
                    not claimed_today
                    and
                    day
                    ==
                    next_day
                )
        })

    return {

        "available":
            available,

        "claimed_today":
            claimed_today,

        "current_day":
            current_day,

        "next_day":
            next_day,

        "streak_broken":
            streak_broken,

        "last_claim_date":
            (
                last_claim_date.isoformat()
                if last_claim_date
                else
                None
            ),

        "next_reward":
            {
                "coins":
                    int(
                        LOGIN_STREAK_REWARDS[
                            next_day
                        ][
                            "coins"
                        ]
                    ),

                "xp":
                    int(
                        LOGIN_STREAK_REWARDS[
                            next_day
                        ][
                            "xp"
                        ]
                    )
            },

        "rewards":
            rewards
    }


def claim_login_streak(
    telegram_id
):

    today = datetime.now(
        timezone.utc
    ).date()

    yesterday = (
        today
        -
        timedelta(
            days=1
        )
    )

    conn = get_db()

    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO login_streaks (
                telegram_id
            )
            VALUES (
                %s
            )
            ON CONFLICT (
                telegram_id
            )
            DO NOTHING
        """, (
            telegram_id,
        ))

        cur.execute("""
            SELECT
                streak_day,
                last_claim_date

            FROM login_streaks

            WHERE telegram_id = %s

            FOR UPDATE
        """, (
            telegram_id,
        ))

        row = cur.fetchone()

        current_day = int(
            row[0]
            or
            0
        )

        last_claim_date = (
            row[1]
            if row
            else
            None
        )

        if (
            last_claim_date
            ==
            today
        ):

            raise ValueError(
                "Награда за сегодня уже получена"
            )

        if (
            last_claim_date
            ==
            yesterday
        ):

            new_day = (
                1
                if
                current_day >= 7
                else
                current_day + 1
            )

        else:

            new_day = 1

        reward = (
            LOGIN_STREAK_REWARDS[
                new_day
            ]
        )

        reward_coins = int(
            reward[
                "coins"
            ]
        )

        reward_xp = int(
            reward[
                "xp"
            ]
        )

        cur.execute("""
            INSERT INTO login_streak_claims (
                telegram_id,
                claim_date,
                streak_day,
                reward_coins,
                reward_xp
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (
                telegram_id,
                claim_date
            )
            DO NOTHING

            RETURNING streak_day
        """, (
            telegram_id,
            today,
            new_day,
            reward_coins,
            reward_xp
        ))

        inserted = (
            cur.fetchone()
        )

        if not inserted:

            raise ValueError(
                "Награда за сегодня уже получена"
            )

        if reward_coins > 0:

            cur.execute("""
                UPDATE users

                SET
                    balance =
                        balance
                        +
                        %s,

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
            UPDATE login_streaks

            SET
                streak_day = %s,
                last_claim_date = %s,
                updated_at = NOW()

            WHERE telegram_id = %s
        """, (
            new_day,
            today,
            telegram_id
        ))

        conn.commit()

    except Exception:

        conn.rollback()

        raise

    finally:

        cur.close()

        conn.close()

    fresh = (
        get_user_data(
            telegram_id
        )
    )

    return {

        "claimed_day":
            new_day,

        "reward_coins":
            reward_coins,

        "reward_xp":
            reward_xp,

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

        "login_streak":
            get_login_streak_status(
                telegram_id
            )
    }


# =========================================================
# 🎯 УГАДАЙ ИСХОД
# =========================================================

def prediction_game_date():

    return datetime.now(
        timezone.utc
    ).date()


def prediction_actual_result(
    home_score,
    away_score
):

    if home_score > away_score:

        return "П1"

    if home_score < away_score:

        return "П2"

    return "X"


def choose_prediction_match():

    now = datetime.now(
        timezone.utc
    )

    matches_list = (
        get_all_cached_matches()
    )

    if not matches_list:

        matches_list = (
            load_default_fixtures(
                False
            )
        )

    candidates = []

    for match in matches_list:

        kickoff = (
            parse_match_datetime(
                match.get(
                    "date"
                )
            )
        )

        if not kickoff:

            continue

        if (
            kickoff
            <=
            now
            +
            timedelta(
                minutes=15
            )
        ):

            continue

        if (
            kickoff
            >
            now
            +
            timedelta(
                days=
                    PREDICTION_LOOKAHEAD_DAYS
            )
        ):

            continue

        candidates.append(
            match
        )

    if not candidates:

        return None

    candidates.sort(
        key=
            lambda item:
                item.get(
                    "date"
                )
                or
                ""
    )

    today = str(
        prediction_game_date()
    )

    digest = hashlib.sha256(
        today.encode(
            "utf-8"
        )
    ).hexdigest()

    index = (
        int(
            digest[
                :8
            ],
            16
        )
        %
        len(
            candidates
        )
    )

    return candidates[
        index
    ]


def ensure_prediction_round():

    today = (
        prediction_game_date()
    )

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
        SELECT
            game_date,
            fixture_id,
            match_name,
            home_team,
            away_team,
            league_name,
            kickoff_at

        FROM prediction_game_rounds

        WHERE game_date = %s
    """, (
        today,
    ))

    row = cur.fetchone()

    if row:

        cur.close()

        conn.close()

        return {

            "game_date":
                row[0],

            "fixture_id":
                int(
                    row[1]
                ),

            "match_name":
                row[2],

            "home_team":
                row[3],

            "away_team":
                row[4],

            "league_name":
                row[5],

            "kickoff_at":
                row[6]
        }

    cur.close()

    conn.close()

    match = (
        choose_prediction_match()
    )

    if not match:

        return None

    kickoff = (
        parse_match_datetime(
            match.get(
                "date"
            )
        )
    )

    match_name = (
        f"{match.get('home')} — "
        f"{match.get('away')}"
    )

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO prediction_game_rounds (
            game_date,
            fixture_id,
            match_name,
            home_team,
            away_team,
            league_name,
            kickoff_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        ON CONFLICT (
            game_date
        )
        DO NOTHING
    """, (
        today,
        int(
            match[
                "fixture_id"
            ]
        ),
        match_name,
        match.get(
            "home"
        ),
        match.get(
            "away"
        ),
        match.get(
            "league"
        ),
        kickoff
    ))

    conn.commit()

    cur.execute("""
        SELECT
            game_date,
            fixture_id,
            match_name,
            home_team,
            away_team,
            league_name,
            kickoff_at

        FROM prediction_game_rounds

        WHERE game_date = %s
    """, (
        today,
    ))

    row = cur.fetchone()

    cur.close()

    conn.close()

    if not row:

        return None

    return {

        "game_date":
            row[0],

        "fixture_id":
            int(
                row[1]
            ),

        "match_name":
            row[2],

        "home_team":
            row[3],

        "away_team":
            row[4],

        "league_name":
            row[5],

        "kickoff_at":
            row[6]
    }


def settle_prediction_picks(
    limit=30
):

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
        SELECT
            p.telegram_id,
            p.game_date,
            p.fixture_id,
            p.prediction

        FROM prediction_game_picks p

        JOIN prediction_game_rounds r
            ON r.game_date =
                p.game_date

        WHERE
            p.settled = FALSE
            AND
            r.kickoff_at <=
                NOW()
                -
                (%s * INTERVAL '1 minute')

        ORDER BY
            r.kickoff_at ASC

        LIMIT %s
    """, (
        SETTLEMENT_AFTER_KICKOFF_MINUTES,
        int(
            limit
        )
    ))

    rows = (
        cur.fetchall()
    )

    cur.close()

    conn.close()

    for row in rows:

        (
            telegram_id,
            game_date,
            fixture_id,
            prediction
        ) = row

        match = (
            get_result(
                fixture_id
            )
        )

        if not match:

            continue

        if not is_finished_status(
            match.get(
                "status"
            )
        ):

            continue

        home_score = (
            match.get(
                "home_score"
            )
        )

        away_score = (
            match.get(
                "away_score"
            )
        )

        if (
            home_score is None
            or
            away_score is None
        ):

            continue

        home_score = int(
            home_score
        )

        away_score = int(
            away_score
        )

        actual_result = (
            prediction_actual_result(
                home_score,
                away_score
            )
        )

        won = (
            prediction
            ==
            actual_result
        )

        reward_coins = (
            PREDICTION_REWARD_COINS
            if won
            else
            0
        )

        reward_xp = (
            PREDICTION_REWARD_XP
            if won
            else
            0
        )

        score = (
            f"{home_score}:"
            f"{away_score}"
        )

        conn = get_db()

        cur = conn.cursor()

        try:

            cur.execute("""
                UPDATE prediction_game_picks

                SET
                    settled = TRUE,
                    won = %s,
                    final_score = %s,
                    actual_result = %s,
                    reward_coins = %s,
                    reward_xp = %s,
                    settled_at = NOW()

                WHERE
                    telegram_id = %s
                    AND
                    game_date = %s
                    AND
                    settled = FALSE
            """, (
                won,
                score,
                actual_result,
                reward_coins,
                reward_xp,
                telegram_id,
                game_date
            ))

            if cur.rowcount != 1:

                conn.rollback()

                continue

            if reward_coins > 0:

                cur.execute("""
                    UPDATE users

                    SET
                        balance =
                            balance
                            +
                            %s,

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

            conn.commit()

        except Exception:

            conn.rollback()

            raise

        finally:

            cur.close()

            conn.close()


def get_prediction_game(
    telegram_id
):

    settle_prediction_picks(
        10
    )

    game = (
        ensure_prediction_round()
    )

    if not game:

        return {

            "available":
                False,

            "message":
                "Пока нет подходящего матча",

            "reward_coins":
                PREDICTION_REWARD_COINS,

            "reward_xp":
                PREDICTION_REWARD_XP
        }

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
        SELECT
            prediction,
            settled,
            won,
            final_score,
            actual_result,
            reward_coins,
            reward_xp,
            created_at

        FROM prediction_game_picks

        WHERE
            telegram_id = %s
            AND
            game_date = %s
    """, (
        telegram_id,
        game[
            "game_date"
        ]
    ))

    row = cur.fetchone()

    cur.close()

    conn.close()

    kickoff = (
        game[
            "kickoff_at"
        ]
    )

    now = datetime.now(
        timezone.utc
    )

    can_pick = (
        row is None
        and
        kickoff
        and
        now < kickoff
    )

    result = {

        "available":
            True,

        "game_date":
            game[
                "game_date"
            ].isoformat(),

        "fixture_id":
            game[
                "fixture_id"
            ],

        "match_name":
            game[
                "match_name"
            ],

        "home_team":
            game[
                "home_team"
            ],

        "away_team":
            game[
                "away_team"
            ],

        "league":
            game[
                "league_name"
            ],

        "kickoff_at":
            (
                kickoff.isoformat()
                if kickoff
                else
                None
            ),

        "can_pick":
            can_pick,

        "reward_coins":
            PREDICTION_REWARD_COINS,

        "reward_xp":
            PREDICTION_REWARD_XP,

        "pick":
            None,

        "settled":
            False,

        "won":
            None,

        "final_score":
            None,

        "actual_result":
            None
    }

    if row:

        result.update({

            "pick":
                row[0],

            "settled":
                bool(
                    row[1]
                ),

            "won":
                row[2],

            "final_score":
                row[3],

            "actual_result":
                row[4],

            "reward_coins":
                (
                    int(
                        row[5]
                        or
                        0
                    )
                    if row[1]
                    else
                    PREDICTION_REWARD_COINS
                ),

            "reward_xp":
                (
                    int(
                        row[6]
                        or
                        0
                    )
                    if row[1]
                    else
                    PREDICTION_REWARD_XP
                ),

            "picked_at":
                (
                    row[7].isoformat()
                    if row[7]
                    else
                    None
                )
        })

    return result


def make_prediction_pick(
    telegram_id,
    prediction
):

    prediction = str(
        prediction
        or
        ""
    ).strip().upper()

    if prediction not in {
        "П1",
        "X",
        "П2"
    }:

        raise ValueError(
            "Выбери П1, X или П2"
        )

    game = (
        ensure_prediction_round()
    )

    if not game:

        raise ValueError(
            "Сейчас нет доступного матча"
        )

    kickoff = (
        game[
            "kickoff_at"
        ]
    )

    if (
        not kickoff
        or
        datetime.now(
            timezone.utc
        )
        >=
        kickoff
    ):

        raise ValueError(
            "Матч уже начался"
        )

    conn = get_db()

    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO prediction_game_picks (
                telegram_id,
                game_date,
                fixture_id,
                prediction
            )
            VALUES (
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (
                telegram_id,
                game_date
            )
            DO NOTHING

            RETURNING prediction
        """, (
            telegram_id,
            game[
                "game_date"
            ],
            game[
                "fixture_id"
            ],
            prediction
        ))

        inserted = (
            cur.fetchone()
        )

        if not inserted:

            raise ValueError(
                "Ты уже выбрал исход на сегодня"
            )

        conn.commit()

    except Exception:

        conn.rollback()

        raise

    finally:

        cur.close()

        conn.close()

    return get_prediction_game(
        telegram_id
    )


# =========================================================
# КОЛЕСО
# =========================================================

def get_wheel_status(
    telegram_id
):

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO wheel_spins (
            telegram_id
        )
        VALUES (
            %s
        )
        ON CONFLICT (
            telegram_id
        )
        DO NOTHING
    """, (
        telegram_id,
    ))

    conn.commit()

    cur.execute("""
        SELECT
            last_spin_at,
            last_reward_type,
            last_reward_value

        FROM wheel_spins

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    row = cur.fetchone()

    cur.close()

    conn.close()

    last_spin_at = (
        row[0]
        if row
        else
        None
    )

    last_reward_type = (
        row[1]
        if row
        else
        None
    )

    last_reward_value = (
        int(
            row[2]
            or
            0
        )
        if row
        else
        0
    )

    available = True

    seconds_left = 0

    next_spin_at = None

    if last_spin_at:

        next_spin_at = (
            last_spin_at
            +
            timedelta(
                hours=
                    WHEEL_COOLDOWN_HOURS
            )
        )

        now = datetime.now(
            timezone.utc
        )

        if now < next_spin_at:

            available = False

            seconds_left = max(
                0,
                int(
                    (
                        next_spin_at
                        -
                        now
                    ).total_seconds()
                )
            )

    return {

        "available":
            available,

        "seconds_left":
            seconds_left,

        "next_spin_at":
            (
                next_spin_at.isoformat()
                if next_spin_at
                else
                None
            ),

        "last_spin_at":
            (
                last_spin_at.isoformat()
                if last_spin_at
                else
                None
            ),

        "last_reward_type":
            last_reward_type,

        "last_reward_value":
            last_reward_value
    }


def choose_wheel_reward():

    total_weight = sum(
        int(
            item[
                "weight"
            ]
        )
        for item
        in WHEEL_REWARDS
    )

    ticket = secrets.randbelow(
        total_weight
    )

    cursor = 0

    for item in WHEEL_REWARDS:

        cursor += int(
            item[
                "weight"
            ]
        )

        if ticket < cursor:

            return dict(
                item
            )

    return dict(
        WHEEL_REWARDS[0]
    )


def spin_wheel(
    telegram_id
):

    conn = get_db()

    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO wheel_spins (
                telegram_id
            )
            VALUES (
                %s
            )
            ON CONFLICT (
                telegram_id
            )
            DO NOTHING
        """, (
            telegram_id,
        ))

        cur.execute("""
            SELECT
                last_spin_at

            FROM wheel_spins

            WHERE telegram_id = %s

            FOR UPDATE
        """, (
            telegram_id,
        ))

        row = cur.fetchone()

        last_spin_at = (
            row[0]
            if row
            else
            None
        )

        now = datetime.now(
            timezone.utc
        )

        if last_spin_at:

            next_spin_at = (
                last_spin_at
                +
                timedelta(
                    hours=
                        WHEEL_COOLDOWN_HOURS
                )
            )

            if now < next_spin_at:

                raise ValueError(
                    "Колесо уже использовано"
                )

        reward = (
            choose_wheel_reward()
        )

        reward_type = str(
            reward[
                "type"
            ]
        )

        reward_value = int(
            reward[
                "value"
            ]
        )

        if reward_type == "coins":

            cur.execute("""
                UPDATE users

                SET
                    balance =
                        balance
                        +
                        %s,

                    updated_at =
                        NOW()

                WHERE telegram_id = %s
            """, (
                reward_value,
                telegram_id
            ))

        elif reward_type == "xp":

            add_xp(
                telegram_id,
                reward_value,
                cur
            )

        cur.execute("""
            UPDATE wheel_spins

            SET
                last_spin_at = %s,
                last_reward_type = %s,
                last_reward_value = %s,
                updated_at = NOW()

            WHERE telegram_id = %s
        """, (
            now,
            reward_type,
            reward_value,
            telegram_id
        ))

        cur.execute("""
            INSERT INTO wheel_spin_history (
                telegram_id,
                reward_type,
                reward_value
            )
            VALUES (
                %s,
                %s,
                %s
            )
        """, (
            telegram_id,
            reward_type,
            reward_value
        ))

        conn.commit()

    except Exception:

        conn.rollback()

        raise

    finally:

        cur.close()

        conn.close()

    fresh = (
        get_user_data(
            telegram_id
        )
    )

    return {

        "reward_type":
            reward_type,

        "reward_value":
            reward_value,

        "reward_label":
            reward[
                "label"
            ],

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

        "wheel":
            get_wheel_status(
                telegram_id
            )
    }


# =========================================================
# ПРОМОКОДЫ
# =========================================================

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

        promo = (
            cur.fetchone()
        )

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

        if (
            expires_at
            and
            datetime.now(
                timezone.utc
            )
            >=
            expires_at
        ):

            raise ValueError(
                "Срок промокода закончился"
            )

        if (
            max_uses is not None
            and
            int(
                uses_count
                or
                0
            )
            >=
            int(
                max_uses
            )
        ):

            raise ValueError(
                "Лимит активаций закончился"
            )

        reward_coins = int(
            reward_coins
            or
            0
        )

        reward_xp = int(
            reward_xp
            or
            0
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
            reward_coins,
            reward_xp
        ))

        if not cur.fetchone():

            raise ValueError(
                "Ты уже использовал этот промокод"
            )

        if reward_coins > 0:

            cur.execute("""
                UPDATE users

                SET
                    balance =
                        balance
                        +
                        %s

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
                    uses_count
                    +
                    1

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
            )
    }


# =========================================================
# СТАВКИ / ЭКСПРЕССЫ
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
            possible

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

    rows = (
        cur.fetchall()
    )

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
            not is_finished_status(
                match.get(
                    "status"
                )
            )
        ):

            continue

        home_score = (
            match.get(
                "home_score"
            )
        )

        away_score = (
            match.get(
                "away_score"
            )
        )

        if (
            home_score is None
            or
            away_score is None
        ):

            continue

        result = (
            calculate_bet_result(
                selection,
                int(
                    home_score
                ),
                int(
                    away_score
                )
            )
        )

        if result == "win":

            status = (
                "Выиграла"
            )

            payout = int(
                possible
            )

        elif result == "refund":

            status = (
                "Возврат"
            )

            payout = int(
                amount
            )

        else:

            status = (
                "Проиграла"
            )

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

        if (
            cur.rowcount == 1
        ):

            if payout > 0:

                cur.execute("""
                    UPDATE users

                    SET
                        balance =
                            balance
                            +
                            %s

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

    rows = (
        cur.fetchall()
    )

    for (
        parlay_id,
        amount
    ) in rows:

        cur.execute("""
            SELECT
                id,
                fixture_id,
                selection,
                odd,
                status

            FROM parlay_legs

            WHERE parlay_id = %s

            ORDER BY id ASC
        """, (
            parlay_id,
        ))

        legs = (
            cur.fetchall()
        )

        loss = False

        unresolved = False

        total_odd = 1.0

        for leg in legs:

            (
                leg_id,
                fixture_id,
                selection,
                odd,
                status
            ) = leg

            if status == "Проиграла":

                loss = True

                continue

            if status == "Выиграла":

                total_odd *= float(
                    odd
                )

                continue

            if status == "Возврат":

                continue

            match = get_result(
                fixture_id
            )

            if (
                not match
                or
                not is_finished_status(
                    match.get(
                        "status"
                    )
                )
            ):

                unresolved = True

                continue

            home_score = (
                match.get(
                    "home_score"
                )
            )

            away_score = (
                match.get(
                    "away_score"
                )
            )

            if (
                home_score is None
                or
                away_score is None
            ):

                unresolved = True

                continue

            result = (
                calculate_bet_result(
                    selection,
                    int(
                        home_score
                    ),
                    int(
                        away_score
                    )
                )
            )

            if result == "win":

                new_status = (
                    "Выиграла"
                )

                total_odd *= float(
                    odd
                )

            elif result == "refund":

                new_status = (
                    "Возврат"
                )

            else:

                new_status = (
                    "Проиграла"
                )

                loss = True

            cur.execute("""
                UPDATE parlay_legs

                SET
                    status = %s,
                    score = %s

                WHERE id = %s
            """, (
                new_status,
                (
                    f"{int(home_score)}:"
                    f"{int(away_score)}"
                ),
                leg_id
            ))

        if loss:

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

        if unresolved:

            continue

        payout = int(
            float(
                amount
            )
            *
            total_odd
            +
            0.5
        )

        status = (
            "Возврат"
            if
            total_odd <= 1
            else
            "Выиграла"
        )

        if status == "Возврат":

            payout = int(
                amount
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
            status,
            parlay_id
        ))

        if cur.rowcount == 1:

            cur.execute("""
                UPDATE users

                SET
                    balance =
                        balance
                        +
                        %s

                WHERE telegram_id = %s
            """, (
                payout,
                telegram_id
            ))

            if status == "Выиграла":

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

    rows = (
        cur.fetchall()
    )

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
                    else
                    None
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
            created_at

        FROM parlays

        WHERE telegram_id = %s

        ORDER BY id DESC
    """, (
        telegram_id,
    ))

    rows = (
        cur.fetchall()
    )

    result = []

    for row in rows:

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
            row[0],
        ))

        legs = [

            {
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
            }

            for leg
            in cur.fetchall()
        ]

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
                    else
                    None
                ),

            "legs":
                legs
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
                WHERE status = 'Выиграла'
            ),

            COUNT(*) FILTER (
                WHERE status = 'Проиграла'
            )

        FROM bets

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    row = (
        cur.fetchone()
    )

    total = int(
        row[0]
        or
        0
    )

    wins = int(
        row[1]
        or
        0
    )

    losses = int(
        row[2]
        or
        0
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
        if
        wins
        +
        losses
        >
        0
        else
        0
    )

    cur.execute("""
        SELECT COUNT(*)

        FROM parlays

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    parlays = int(
        cur.fetchone()[0]
    )

    cur.execute("""
        SELECT
            COUNT(*),

            COUNT(*) FILTER (
                WHERE won = TRUE
            )

        FROM prediction_game_picks

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    prediction = (
        cur.fetchone()
    )

    cur.close()

    conn.close()

    return {

        "total_bets":
            total,

        "wins":
            wins,

        "losses":
            losses,

        "win_rate":
            win_rate,

        "total_parlays":
            parlays,

        "prediction_games":
            int(
                prediction[0]
                or
                0
            ),

        "prediction_wins":
            int(
                prediction[1]
                or
                0
            )
    }


def get_achievements(
    telegram_id
):

    user = get_user_data(
        telegram_id
    )

    if not user:

        return []

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
            bets_count,

        "wins_5":
            wins,

        "level_5":
            calculate_level(
                user[
                    "xp"
                ]
            ),

        "xp_500":
            int(
                user[
                    "xp"
                ]
                or
                0
            ),

        "high_odd_win":
            high_odd
    }

    return [

        {
            **item,

            "progress":
                min(
                    values.get(
                        item[
                            "key"
                        ],
                        0
                    ),
                    item[
                        "target"
                    ]
                ),

            "completed":
                values.get(
                    item[
                        "key"
                    ],
                    0
                )
                >=
                item[
                    "target"
                ],

            "claimed":
                item[
                    "key"
                ]
                in
                claimed
        }

        for item
        in ACHIEVEMENTS
    ]


# =========================================================
# ИЗБРАННОЕ
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
            kickoff_at

        FROM match_favorites

        WHERE
            telegram_id = %s
            AND
            kickoff_at > NOW()

        ORDER BY kickoff_at ASC
    """, (
        telegram_id,
    ))

    result = [

        {
            "fixture_id":
                int(
                    row[0]
                ),

            "match":
                row[1],

            "date":
                row[2].isoformat()
        }

        for row
        in cur.fetchall()
    ]

    cur.close()

    conn.close()

    return result


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
            kickoff_at =
                EXCLUDED.kickoff_at,

            updated_at =
                NOW()
    """, (
        telegram_id,
        fixture_id,
        (
            f"{match['home']} — "
            f"{match['away']}"
        ),
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
        DO NOTHING
    """, (
        telegram_id,
        team_name,
        favorite_team_key(
            team_name
        )
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


# =========================================================
# LIVE
# =========================================================

def refresh_live_matches_once():

    now = datetime.now(
        timezone.utc
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
            kickoff
            <=
            now
            +
            timedelta(
                minutes=
                    LIVE_PREMATCH_MINUTES
            )
            and
            kickoff
            >=
            now
            -
            timedelta(
                hours=
                    LIVE_POSTMATCH_HOURS
            )
        ):

            candidates.append(
                match
            )

    candidates = candidates[
        :LIVE_MAX_MATCHES_PER_CYCLE
    ]

    for match in candidates:

        try:

            fresh = get_fixture(
                match[
                    "fixture_id"
                ],
                False,
                True
            )

            live, finished = (
                live_status_flags(
                    fresh.get(
                        "status"
                    ),
                    fresh.get(
                        "status_code"
                    )
                )
            )

            live_match_cache[
                str(
                    int(
                        match[
                            "fixture_id"
                        ]
                    )
                )
            ] = {

                **fresh,

                "live":
                    live,

                "finished":
                    finished,

                "updated_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat()
            }

        except Exception as error:

            print(
                "Live error:",
                error
            )


def live_worker():

    time.sleep(
        30
    )

    while True:

        try:

            refresh_live_matches_once()

        except Exception as error:

            print(
                "Live worker:",
                error
            )

        time.sleep(
            LIVE_REFRESH_SECONDS
        )


def settlement_worker():

    time.sleep(
        20
    )

    while True:

        try:

            conn = get_db()

            cur = conn.cursor()

            cur.execute("""
                SELECT telegram_id

                FROM users
            """)

            users = [
                int(
                    row[0]
                )
                for row
                in cur.fetchall()
            ]

            cur.close()

            conn.close()

            for telegram_id in users:

                settle_user_bets(
                    telegram_id
                )

                settle_user_parlays(
                    telegram_id
                )

            settle_prediction_picks(
                30
            )

        except Exception as error:

            print(
                "Settlement worker:",
                error
            )

        time.sleep(
            SETTLEMENT_CHECK_SECONDS
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
                True
        ).start()

        threading.Thread(
            target=
                live_worker,
            daemon=
                True
        ).start()


# =========================================================
# API
# =========================================================

@app.route("/")
def root():

    return jsonify({

        "status":
            "ok",

        "message":
            "BetCoin server is working",

        "prediction_game":
            True,

        "wheel":
            True,

        "login_streak":
            True,

        "games_tab":
            True
    })


@app.route(
    "/api/matches"
)
def api_matches():

    try:

        league_key = (
            request.args.get(
                "league",
                ""
            )
            or
            ""
        )

        if (
            not league_key
            or
            league_key
            ==
            "top5"
        ):

            matches = (
                load_default_fixtures()
            )

        else:

            matches = (
                load_league_fixtures(
                    league_key
                )
            )

        return jsonify({

            "success":
                True,

            "matches":
                matches
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
    "/api/live"
)
def api_live():

    return jsonify({

        "success":
            True,

        "matches":
            list(
                live_match_cache.values()
            )
    })


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

        user = (
            get_or_create_user(
                tg_user
            )
        )

        telegram_id = (
            user[
                "telegram_id"
            ]
        )

        last_claim = (
            user.get(
                "last_daily_claim"
            )
        )

        available = True

        seconds_left = 0

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

            "daily_reward": {

                "amount":
                    300,

                "available":
                    available,

                "seconds_left":
                    max(
                        0,
                        seconds_left
                    )
            },

            "login_streak":
                get_login_streak_status(
                    telegram_id
                ),

            "wheel":
                get_wheel_status(
                    telegram_id
                ),

            "prediction_game":
                get_prediction_game(
                    telegram_id
                ),

            "leaderboard": {
                "my_rank":
                    None
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


@app.route(
    "/api/login-streak/claim",
    methods=[
        "POST"
    ]
)
def api_login_streak_claim():

    tg_user, error = (
        require_telegram_user()
    )

    if error:

        return error

    try:

        user = get_or_create_user(
            tg_user
        )

        result = claim_login_streak(
            user[
                "telegram_id"
            ]
        )

        return jsonify({
            "success":
                True,
            **result
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
    "/api/games/prediction",
    methods=[
        "POST"
    ]
)
def api_prediction_game():

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

        "game":
            get_prediction_game(
                user[
                    "telegram_id"
                ]
            )
    })


@app.route(
    "/api/games/prediction/pick",
    methods=[
        "POST"
    ]
)
def api_prediction_pick():

    tg_user, error = (
        require_telegram_user()
    )

    if error:

        return error

    body = (
        request.get_json(
            silent=True
        )
        or
        {}
    )

    try:

        user = get_or_create_user(
            tg_user
        )

        game = (
            make_prediction_pick(
                user[
                    "telegram_id"
                ],
                body.get(
                    "prediction"
                )
            )
        )

        return jsonify({

            "success":
                True,

            "game":
                game
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


@app.route(
    "/api/wheel/status",
    methods=[
        "POST"
    ]
)
def api_wheel_status():

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

        "wheel":
            get_wheel_status(
                user[
                    "telegram_id"
                ]
            )
    })


@app.route(
    "/api/wheel/spin",
    methods=[
        "POST"
    ]
)
def api_wheel_spin():

    tg_user, error = (
        require_telegram_user()
    )

    if error:

        return error

    try:

        user = get_or_create_user(
            tg_user
        )

        return jsonify({
            "success":
                True,
            **spin_wheel(
                user[
                    "telegram_id"
                ]
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

    body = (
        request.get_json(
            silent=True
        )
        or
        {}
    )

    try:

        user = get_or_create_user(
            tg_user
        )

        return jsonify({
            "success":
                True,
            **redeem_promo_code(
                user[
                    "telegram_id"
                ],
                body.get(
                    "code"
                )
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

    body = (
        request.get_json(
            silent=True
        )
        or
        {}
    )

    try:

        fixture_id = int(
            body[
                "fixture_id"
            ]
        )

        amount = int(
            body[
                "amount"
            ]
        )

        selection = str(
            body[
                "selection"
            ]
        )

        canonical = (
            resolve_canonical_bet(
                fixture_id,
                selection
            )
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

        balance = int(
            cur.fetchone()[0]
        )

        if (
            amount <= 0
            or
            amount > balance
        ):

            raise ValueError(
                "Недостаточно монет"
            )

        possible = int(
            amount
            *
            canonical[
                "odd"
            ]
            +
            0.5
        )

        cur.execute("""
            UPDATE users

            SET
                balance =
                    balance
                    -
                    %s

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
                %s
            )
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
            canonical[
                "odd"
            ],
            amount,
            possible,
            canonical[
                "kickoff_at"
            ]
        ))

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

            "balance":
                fresh[
                    "balance"
                ],

            "bets":
                get_user_bets(
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

    body = (
        request.get_json(
            silent=True
        )
        or
        {}
    )

    try:

        amount = int(
            body[
                "amount"
            ]
        )

        legs = (
            body.get(
                "legs"
            )
            or
            []
        )

        if len(
            legs
        ) < 2:

            raise ValueError(
                "Нужно минимум 2 события"
            )

        validated = [

            resolve_canonical_bet(
                int(
                    leg[
                        "fixture_id"
                    ]
                ),
                leg[
                    "selection"
                ]
            )

            for leg
            in legs
        ]

        if (
            len({
                item[
                    "fixture_id"
                ]
                for item
                in validated
            })
            !=
            len(
                validated
            )
        ):

            raise ValueError(
                "Нельзя добавить два исхода одного матча"
            )

        total_odd = 1.0

        for item in validated:

            total_odd *= float(
                item[
                    "odd"
                ]
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

        balance = int(
            cur.fetchone()[0]
        )

        if (
            amount <= 0
            or
            amount > balance
        ):

            raise ValueError(
                "Недостаточно монет"
            )

        cur.execute("""
            UPDATE users

            SET
                balance =
                    balance
                    -
                    %s

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

        parlay_id = (
            cur.fetchone()[0]
        )

        for item in validated:

            cur.execute("""
                INSERT INTO parlay_legs (
                    parlay_id,
                    fixture_id,
                    match_name,
                    selection,
                    odd,
                    kickoff_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
            """, (
                parlay_id,
                item[
                    "fixture_id"
                ],
                item[
                    "match"
                ],
                item[
                    "selection"
                ],
                item[
                    "odd"
                ],
                item[
                    "kickoff_at"
                ]
            ))

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

            "balance":
                fresh[
                    "balance"
                ],

            "parlays":
                get_user_parlays(
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

    body = (
        request.get_json(
            silent=True
        )
        or
        {}
    )

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

    if body.get(
        "favorite",
        True
    ):

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

    body = (
        request.get_json(
            silent=True
        )
        or
        {}
    )

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
            "team_name"
        )
        or
        ""
    )

    if body.get(
        "favorite",
        True
    ):

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
            )
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

        level = calculate_level(
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
                ),

            "xp":
                int(
                    row[3]
                ),

            "level":
                level,

            "league":
                get_league(
                    level
                )
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
            my_rank
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
                balance
                +
                300,

            last_daily_claim =
                %s

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
            fresh[
                "balance"
            ],

        **xp_info(
            fresh[
                "xp"
            ]
        )
    })


@app.route(
    "/api/tasks/claim",
    methods=[
        "POST"
    ]
)
def api_tasks_claim():

    tg_user, error = (
        require_telegram_user()
    )

    if error:

        return error

    body = (
        request.get_json(
            silent=True
        )
        or
        {}
    )

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
        telegram_id
    )

    target = next(
        (
            item
            for item
            in tasks
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

    columns = {

        "login":
            "login_claimed",

        "bets_3":
            "bets_claimed",

        "win_1":
            "win_claimed"
    }

    column = columns[
        key
    ]

    conn = get_db()

    cur = conn.cursor()

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

    if (
        target[
            "reward_type"
        ]
        ==
        "coins"
    ):

        cur.execute("""
            UPDATE users

            SET
                balance =
                    balance
                    +
                    %s

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

    return jsonify({
        "success":
            True
    })


@app.route(
    "/api/achievements/claim",
    methods=[
        "POST"
    ]
)
def api_achievements_claim():

    tg_user, error = (
        require_telegram_user()
    )

    if error:

        return error

    body = (
        request.get_json(
            silent=True
        )
        or
        {}
    )

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

    achievements = (
        get_achievements(
            telegram_id
        )
    )

    target = next(
        (
            item
            for item
            in achievements
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
        ON CONFLICT
        DO NOTHING
    """, (
        telegram_id,
        key
    ))

    cur.execute("""
        UPDATE users

        SET
            balance =
                balance
                +
                %s

        WHERE telegram_id = %s
    """, (
        target[
            "reward"
        ],
        telegram_id
    ))

    conn.commit()

    cur.close()

    conn.close()

    return jsonify({
        "success":
            True
    })


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

    settle_prediction_picks(
        10
    )

    fresh = get_user_data(
        telegram_id
    )

    return jsonify({

        "success":
            True,

        "balance":
            fresh[
                "balance"
            ],

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

        "prediction_game":
            get_prediction_game(
                telegram_id
            ),

        "login_streak":
            get_login_streak_status(
                telegram_id
            )
    })


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
        host=
            "0.0.0.0",

        port=
            port,

        threaded=
            True
    )
