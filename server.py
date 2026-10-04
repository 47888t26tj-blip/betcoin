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


BETCOIN_WEBAPP_URL = os.environ.get(
    "BETCOIN_WEBAPP_URL",
    ""
).strip()

TELEGRAM_WEBHOOK_URL = os.environ.get(
    "TELEGRAM_WEBHOOK_URL",
    ""
).strip()

BETCOIN_START_IMAGE_URL = os.environ.get(
    "BETCOIN_START_IMAGE_URL",
    ""
).strip()


BETCOIN_BOT_USERNAME = os.environ.get(
    "BETCOIN_BOT_USERNAME",
    ""
).strip().lstrip("@")

REFERRAL_INVITER_REWARD = 500
REFERRAL_FRIEND_REWARD = 300

RENDER_EXTERNAL_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    ""
).strip()

RENDER_EXTERNAL_HOSTNAME = os.environ.get(
    "RENDER_EXTERNAL_HOSTNAME",
    ""
).strip()


FIVE_API_URL = "https://api.5dollarfootballapi.com"
FOOTBALL_DATA_URL = "https://api.football-data.org/v4"


# =========================================================
# ЛИГИ
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

    "nations_league": {
        "ids": [
            11103,
            2020098592,
            80636319,
            2272692175,
            997232971,
            2095840468
        ],
        "name": "UEFA Nations League",
        "short_name": "Лига наций",
        "country": "Europe",
        "flag": "🌍",
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

        LEAGUE_ID_TO_KEY[int(league_id)] = league_key


# =========================================================
# НАСТРОЙКИ
# =========================================================

FIXTURES_CACHE_SECONDS = 1800
STALE_FIXTURES_CACHE_SECONDS = 21600
FOOTBALL_DATA_TIMEOUT_SECONDS = 6
AUTO_FIXTURES_REFRESH_SECONDS = 3600
AUTO_FIXTURES_START_DELAY_SECONDS = 45
ODDS_CACHE_SECONDS = 21600
RESULT_CACHE_SECONDS = 300

SETTLEMENT_CHECK_SECONDS = 300
SETTLEMENT_AFTER_KICKOFF_MINUTES = 100

LIVE_REFRESH_SECONDS = 60
LIVE_PREMATCH_MINUTES = 15
LIVE_POSTMATCH_HOURS = 3
LIVE_MAX_MATCHES_PER_CYCLE = 3

MAX_FIXTURE_DAYS = 14

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

PREDICTION_REWARD_COINS = 200
PREDICTION_REWARD_XP = 25
PREDICTION_LOOKAHEAD_DAYS = 7


# =========================================================
# ⚽ УГАДАЙ СЧЁТ
# =========================================================

SCORE_GAME_EXACT_COINS = 1000
SCORE_GAME_EXACT_XP = 150

SCORE_GAME_OUTCOME_COINS = 150
SCORE_GAME_OUTCOME_XP = 0

SCORE_GAME_LOOKAHEAD_DAYS = 7

SCORE_GAME_MAX_SCORE = 10

SCORE_GAME_REMINDER_FROM_MINUTES = 45
SCORE_GAME_REMINDER_TO_MINUTES = 75


WHEEL_REWARDS = [

    {
        "type": "coins",
        "value": 50,
        "weight": 3000,
        "label": "+50 🪙"
    },

    {
        "type": "coins",
        "value": 100,
        "weight": 2800,
        "label": "+100 🪙"
    },

    {
        "type": "coins",
        "value": 200,
        "weight": 2200,
        "label": "+200 🪙"
    },

    {
        "type": "coins",
        "value": 500,
        "weight": 1200,
        "label": "+500 🪙"
    },

    {
        "type": "coins",
        "value": 1000,
        "weight": 500,
        "label": "+1000 🪙"
    },

    {
        "type": "xp",
        "value": 100,
        "weight": 300,
        "label": "+100 XP"
    }
]


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
        "description": "Выиграть ставку с коэффициентом 3.00+",
        "target": 1,
        "reward": 350
    }
]


# =========================================================
# КЭШ
# =========================================================

league_fixture_cache = {}
league_source_status = {}
fixture_detail_cache = {}
odds_cache = {}
result_cache = {}
live_match_cache = {}
match_center_cache = {}
team_form_cache = {}
standings_cache = {}
match_stats_cache = {}
global_logo_cache = {}


# =========================================================
# RUNTIME / LOCKS
# =========================================================

database_ready = False
database_initializing = False

workers_started = False
runtime_ready = False

workers_lock = threading.Lock()
database_lock = threading.Lock()
runtime_lock = threading.Lock()

five_rate_lock = threading.Lock()
five_rate_timestamps = deque()


# =========================================================
# КОМАНДЫ
# =========================================================

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

    "atletico de madrid": "atletico madrid"
}


# =========================================================
# DATABASE
# =========================================================

def get_db():

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL not found"
        )

    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10,
        options="-c statement_timeout=15000"
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
        CREATE TABLE IF NOT EXISTS referral_pending (

            telegram_id BIGINT PRIMARY KEY,

            inviter_telegram_id BIGINT NOT NULL,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW()
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (

            referred_telegram_id BIGINT PRIMARY KEY
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            inviter_telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            inviter_reward INTEGER NOT NULL
                DEFAULT 500,

            friend_reward INTEGER NOT NULL
                DEFAULT 300,

            activated_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW()
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_referrals_inviter
        ON referrals(inviter_telegram_id)
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
                REFERENCES users(telegram_id)
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
                REFERENCES parlays(id)
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
                REFERENCES users(telegram_id)
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
                REFERENCES users(telegram_id)
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
                REFERENCES users(telegram_id)
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
                REFERENCES users(telegram_id)
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
                REFERENCES users(telegram_id)
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
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            code TEXT NOT NULL
                REFERENCES promo_codes(code)
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
        CREATE TABLE IF NOT EXISTS user_notification_settings (

            telegram_id BIGINT PRIMARY KEY
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            match_day BOOLEAN NOT NULL DEFAULT TRUE,
            favorite_match BOOLEAN NOT NULL DEFAULT TRUE,
            bet_result BOOLEAN NOT NULL DEFAULT TRUE,
            prediction_result BOOLEAN NOT NULL DEFAULT TRUE,
            referral BOOLEAN NOT NULL DEFAULT TRUE,

            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS wheel_spins (

            telegram_id BIGINT PRIMARY KEY
                REFERENCES users(telegram_id)
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
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            reward_type TEXT NOT NULL,

            reward_value INTEGER NOT NULL,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW()
        )
    """)


    # =====================================================
    # 🎯 УГАДАЙ ИСХОД
    # =====================================================

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
                REFERENCES users(telegram_id)
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


    # =====================================================
    # ⚽ УГАДАЙ СЧЁТ
    # =====================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS score_game_rounds (

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
        CREATE TABLE IF NOT EXISTS score_game_picks (

            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            game_date DATE NOT NULL,

            fixture_id BIGINT NOT NULL,

            predicted_home INTEGER NOT NULL,

            predicted_away INTEGER NOT NULL,

            settled BOOLEAN NOT NULL
                DEFAULT FALSE,

            exact_win BOOLEAN,

            outcome_win BOOLEAN,

            final_home INTEGER,

            final_away INTEGER,

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


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_score_game_picks_due

        ON score_game_picks (
            settled,
            fixture_id
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_score_game_picks_user

        ON score_game_picks (
            telegram_id,
            game_date DESC
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS score_game_notifications (

            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            game_date DATE NOT NULL,

            reminder_sent BOOLEAN NOT NULL
                DEFAULT FALSE,

            reminder_sent_at TIMESTAMPTZ,

            result_sent BOOLEAN NOT NULL
                DEFAULT FALSE,

            result_sent_at TIMESTAMPTZ,

            PRIMARY KEY (
                telegram_id,
                game_date
            )
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_score_game_notifications_result

        ON score_game_notifications (
            game_date,
            result_sent
        )
    """)


    # =====================================================
    # 👥 ПРИВАТНЫЕ ЛИГИ ПРОГНОЗИСТОВ
    # =====================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS predictor_leagues (

            id SERIAL PRIMARY KEY,

            owner_telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            name TEXT NOT NULL,

            invite_code TEXT NOT NULL UNIQUE,

            created_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW()
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS predictor_league_members (

            league_id INTEGER NOT NULL
                REFERENCES predictor_leagues(id)
                ON DELETE CASCADE,

            telegram_id BIGINT NOT NULL
                REFERENCES users(telegram_id)
                ON DELETE CASCADE,

            joined_at TIMESTAMPTZ NOT NULL
                DEFAULT NOW(),

            PRIMARY KEY (
                league_id,
                telegram_id
            )
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_predictor_league_members_user

        ON predictor_league_members (
            telegram_id,
            joined_at DESC
        )
    """)


    # =====================================================
    # 🔥 СЕРИЯ ВХОДОВ
    # =====================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_streaks (

            telegram_id BIGINT PRIMARY KEY
                REFERENCES users(telegram_id)
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
                REFERENCES users(telegram_id)
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
        idx_bets_user
        ON bets(telegram_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_parlays_user
        ON parlays(telegram_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_wheel_history_user
        ON wheel_spin_history(
            telegram_id,
            created_at DESC
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_login_streak_claims_user
        ON login_streak_claims(
            telegram_id,
            claim_date DESC
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_prediction_game_picks_due
        ON prediction_game_picks(
            settled,
            fixture_id
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_prediction_game_picks_user
        ON prediction_game_picks(
            telegram_id,
            game_date DESC
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


    cur.execute("""
        INSERT INTO promo_codes (
            code,
            reward_coins,
            reward_xp,
            max_uses,
            active
        )
        VALUES (
            'BETCOIN10K',
            10000,
            0,
            1,
            TRUE
        )
        ON CONFLICT (code)
        DO UPDATE SET
            reward_coins = EXCLUDED.reward_coins,
            reward_xp = EXCLUDED.reward_xp,
            max_uses = EXCLUDED.max_uses,
            active = TRUE
    """)


    conn.commit()

    cur.close()
    conn.close()

    database_ready = True


# =========================================================
# НОРМАЛИЗАЦИЯ
# =========================================================

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
        for char in value
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
        "the"
    }

    return " ".join(
        word
        for word in normalize_club_name(name).split()
        if word not in ignored
    )


def alias_club_name(name):

    normalized = normalize_club_name(
        name
    )

    simplified = simplified_club_name(
        name
    )

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


# =========================================================
# LOGOS
# =========================================================

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
                "logo": row[2]
            }

        cur.close()
        conn.close()

    except Exception as error:

        print(
            "Logo cache error:",
            error,
            flush=True
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


# =========================================================
# LAZY STARTUP
# =========================================================

def ensure_database_ready():

    global database_ready
    global database_initializing

    if database_ready:
        return

    with database_lock:

        if database_ready:
            return

        database_initializing = True

        try:

            init_database()

            rebuild_global_logo_cache()

            database_ready = True

            print(
                "Database initialized successfully",
                flush=True
            )

        finally:

            database_initializing = False


# =========================================================
# TELEGRAM AUTH
# =========================================================

def verify_telegram_init_data(init_data):

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
            in sorted(data.items())
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

        if not user.get("id"):
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
                "error": "Telegram authentication failed"
            }),
            401
        )

    return user, None


# =========================================================
# USER
# =========================================================

def get_or_create_user(tg_user):

    ensure_runtime_ready()

    telegram_id = int(
        tg_user["id"]
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT 1
        FROM users
        WHERE telegram_id = %s
        """,
        (
            telegram_id,
        )
    )

    was_existing = (
        cur.fetchone()
        is not None
    )

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
        ON CONFLICT (telegram_id)
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
        "is_new": (
            not was_existing
        )
    }


def get_user_data(telegram_id):

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
        "xp": row[5]
    }




# =========================================================
# NOTIFICATION SETTINGS
# =========================================================

def get_notification_settings(
    telegram_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO user_notification_settings (
            telegram_id
        )
        VALUES (
            %s
        )
        ON CONFLICT (telegram_id)
        DO NOTHING
        """,
        (
            int(
                telegram_id
            ),
        )
    )

    conn.commit()

    cur.execute(
        """
        SELECT
            match_day,
            favorite_match,
            bet_result,
            prediction_result,
            referral

        FROM user_notification_settings

        WHERE telegram_id = %s
        """,
        (
            int(
                telegram_id
            ),
        )
    )

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:

        return {
            "match_day": True,
            "favorite_match": True,
            "bet_result": True,
            "prediction_result": True,
            "referral": True
        }

    return {
        "match_day":
            bool(
                row[0]
            ),

        "favorite_match":
            bool(
                row[1]
            ),

        "bet_result":
            bool(
                row[2]
            ),

        "prediction_result":
            bool(
                row[3]
            ),

        "referral":
            bool(
                row[4]
            )
    }


def update_notification_settings(
    telegram_id,
    data
):

    current = (
        get_notification_settings(
            telegram_id
        )
    )

    allowed = {
        "match_day",
        "favorite_match",
        "bet_result",
        "prediction_result",
        "referral"
    }

    for key in allowed:

        if key in data:

            current[
                key
            ] = bool(
                data[
                    key
                ]
            )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO user_notification_settings (
            telegram_id,
            match_day,
            favorite_match,
            bet_result,
            prediction_result,
            referral,
            updated_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            NOW()
        )
        ON CONFLICT (telegram_id)
        DO UPDATE SET
            match_day =
                EXCLUDED.match_day,

            favorite_match =
                EXCLUDED.favorite_match,

            bet_result =
                EXCLUDED.bet_result,

            prediction_result =
                EXCLUDED.prediction_result,

            referral =
                EXCLUDED.referral,

            updated_at =
                NOW()
        """,
        (
            int(
                telegram_id
            ),
            current[
                "match_day"
            ],
            current[
                "favorite_match"
            ],
            current[
                "bet_result"
            ],
            current[
                "prediction_result"
            ],
            current[
                "referral"
            ]
        )
    )

    conn.commit()

    cur.close()
    conn.close()

    return current


def notification_enabled(
    telegram_id,
    key
):

    try:

        return bool(
            get_notification_settings(
                telegram_id
            ).get(
                key,
                True
            )
        )

    except Exception:

        return True


# =========================================================
# REFERRALS
# =========================================================

_bot_username_cache = {
    "value": None,
    "checked_at": 0
}


def get_betcoin_bot_username():

    if BETCOIN_BOT_USERNAME:
        return BETCOIN_BOT_USERNAME

    now_ts = time.time()

    cached = (
        _bot_username_cache.get(
            "value"
        )
    )

    checked_at = float(
        _bot_username_cache.get(
            "checked_at",
            0
        )
        or
        0
    )

    if (
        cached
        and
        now_ts - checked_at < 3600
    ):
        return cached

    result = telegram_api_call(
        "getMe"
    )

    username = ""

    if result.get("ok"):

        username = str(
            (
                result.get(
                    "result"
                )
                or
                {}
            ).get(
                "username"
            )
            or
            ""
        ).strip().lstrip("@")

    _bot_username_cache[
        "value"
    ] = username

    _bot_username_cache[
        "checked_at"
    ] = now_ts

    return username


def save_pending_referral(
    referred_telegram_id,
    inviter_telegram_id
):

    referred_telegram_id = int(
        referred_telegram_id
    )

    inviter_telegram_id = int(
        inviter_telegram_id
    )

    if (
        referred_telegram_id
        ==
        inviter_telegram_id
    ):
        return False

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT 1
        FROM users
        WHERE telegram_id = %s
        """,
        (
            inviter_telegram_id,
        )
    )

    inviter_exists = (
        cur.fetchone()
        is not None
    )

    if not inviter_exists:

        cur.close()
        conn.close()
        return False

    cur.execute(
        """
        SELECT 1
        FROM referrals
        WHERE referred_telegram_id = %s
        """,
        (
            referred_telegram_id,
        )
    )

    already_referred = (
        cur.fetchone()
        is not None
    )

    if already_referred:

        cur.close()
        conn.close()
        return False

    cur.execute(
        """
        INSERT INTO referral_pending (
            telegram_id,
            inviter_telegram_id
        )
        VALUES (
            %s,
            %s
        )
        ON CONFLICT (telegram_id)
        DO NOTHING
        """,
        (
            referred_telegram_id,
            inviter_telegram_id
        )
    )

    conn.commit()

    saved = (
        cur.rowcount
        >
        0
    )

    cur.close()
    conn.close()

    return saved


def activate_pending_referral(
    telegram_id,
    is_new_user
):

    telegram_id = int(
        telegram_id
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT inviter_telegram_id
        FROM referral_pending
        WHERE telegram_id = %s
        """,
        (
            telegram_id,
        )
    )

    row = cur.fetchone()

    if not row:

        cur.close()
        conn.close()

        return {
            "activated": False
        }

    inviter_id = int(
        row[0]
    )

    if (
        not is_new_user
        or
        inviter_id == telegram_id
    ):

        cur.execute(
            """
            DELETE FROM referral_pending
            WHERE telegram_id = %s
            """,
            (
                telegram_id,
            )
        )

        conn.commit()

        cur.close()
        conn.close()

        return {
            "activated": False
        }

    cur.execute(
        """
        INSERT INTO referrals (
            referred_telegram_id,
            inviter_telegram_id,
            inviter_reward,
            friend_reward
        )
        VALUES (
            %s,
            %s,
            %s,
            %s
        )
        ON CONFLICT (referred_telegram_id)
        DO NOTHING
        """,
        (
            telegram_id,
            inviter_id,
            REFERRAL_INVITER_REWARD,
            REFERRAL_FRIEND_REWARD
        )
    )

    inserted = (
        cur.rowcount
        >
        0
    )

    if inserted:

        cur.execute(
            """
            UPDATE users
            SET
                balance =
                    balance
                    +
                    %s,

                updated_at =
                    NOW()

            WHERE telegram_id = %s
            """,
            (
                REFERRAL_INVITER_REWARD,
                inviter_id
            )
        )

        cur.execute(
            """
            UPDATE users
            SET
                balance =
                    balance
                    +
                    %s,

                updated_at =
                    NOW()

            WHERE telegram_id = %s
            """,
            (
                REFERRAL_FRIEND_REWARD,
                telegram_id
            )
        )

    cur.execute(
        """
        DELETE FROM referral_pending
        WHERE telegram_id = %s
        """,
        (
            telegram_id,
        )
    )

    conn.commit()

    cur.close()
    conn.close()

    if inserted:

        try:

            send_telegram_message(
                inviter_id,
                (
                    "🎁 Новый друг в BetCoin!\n\n"
                    f"+{REFERRAL_INVITER_REWARD} 🪙 за приглашение."
                )
            )

        except Exception as error:

            print(
                "Referral notification error:",
                error,
                flush=True
            )

    return {
        "activated":
            inserted,

        "inviter_id":
            inviter_id
    }


def get_referral_info(
    telegram_id
):

    telegram_id = int(
        telegram_id
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*)
        FROM referrals
        WHERE inviter_telegram_id = %s
        """,
        (
            telegram_id,
        )
    )

    invited_count = int(
        (
            cur.fetchone()
            or
            [0]
        )[0]
        or
        0
    )

    cur.close()
    conn.close()

    username = (
        get_betcoin_bot_username()
    )

    referral_link = (
        (
            "https://t.me/"
            +
            username
            +
            "?start=ref_"
            +
            str(
                telegram_id
            )
        )
        if username
        else
        ""
    )

    return {
        "link":
            referral_link,

        "invited_count":
            invited_count,

        "inviter_reward":
            REFERRAL_INVITER_REWARD,

        "friend_reward":
            REFERRAL_FRIEND_REWARD
    }


# =========================================================
# XP
# =========================================================

def calculate_level(xp):

    return (
        int(xp or 0)
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


def xp_info(xp):

    xp = int(
        xp or 0
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
        "xp": xp,
        "level": level,
        "league": get_league(level),
        "current_level_xp": current,
        "xp_to_next_level": 100 - current
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
        else
        0
    )

    old_level = calculate_level(
        old_xp
    )

    new_xp = (
        old_xp
        +
        int(amount)
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

    result["level_reward"] = reward

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
            "key": "login",
            "title": "Зайти в приложение",
            "description": "Открой BetCoin сегодня",
            "progress": 1 if row[0] else 0,
            "target": 1,
            "completed": bool(row[0]),
            "claimed": bool(row[3]),
            "reward_type": "xp",
            "reward": 50
        },

        {
            "key": "bets_3",
            "title": "Сделать 3 ставки",
            "description": "Сделай 3 ставки за сегодня",
            "progress": min(
                int(row[1] or 0),
                3
            ),
            "target": 3,
            "completed": int(row[1] or 0) >= 3,
            "claimed": bool(row[4]),
            "reward_type": "coins",
            "reward": 100
        },

        {
            "key": "win_1",
            "title": "Выиграть 1 ставку",
            "description": "Получи один выигрыш сегодня",
            "progress": min(
                int(row[2] or 0),
                1
            ),
            "target": 1,
            "completed": int(row[2] or 0) >= 1,
            "claimed": bool(row[5]),
            "reward_type": "coins",
            "reward": 150
        }
    ]


# =========================================================
# 5 DOLLAR API
# =========================================================

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
                len(five_rate_timestamps)
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
    attempts=2,
    timeout_seconds=20
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
                FIVE_API_URL + path,
                headers=five_headers(),
                params=params or {},
                timeout=timeout_seconds
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

                payload = response.text[:300]

            raise RuntimeError(
                "5DollarFootballAPI HTTP "
                +
                str(response.status_code)
                +
                ": "
                +
                str(payload)
            )

        return response.json()

    raise RuntimeError(
        last_error
        or
        "5DollarFootballAPI request failed"
    )


# =========================================================
# FOOTBALL PARSING
# =========================================================

def parse_match_datetime(value):

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

        if raw.endswith("Z"):

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


def first_snapshot(market):

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


def extract_bookmakers(payload):

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
        payload.get("bookmakers"),
        list
    ):

        return payload["bookmakers"]

    data = payload.get(
        "data"
    )

    if (
        isinstance(data, dict)
        and
        isinstance(
            data.get("bookmakers"),
            list
        )
    ):

        return data["bookmakers"]

    if {
        "1x2",
        "asian_handicap",
        "goal_line",
        "goal_line_fixed",
        "btts"
    } & set(payload.keys()):

        return [
            {
                "name": "Bet 365",
                "slug": "bet365",
                "odds": payload
            }
        ]

    return []


def parse_odds_response(payload):

    result = {
        "odds": None,
        "totals": {},
        "btts": None,
        "handicaps": None,
        "bookmaker": None,
        "available_markets": []
    }

    bookmakers = extract_bookmakers(
        payload
    )

    if not bookmakers:

        return result

    bookmaker = next(
        (
            item
            for item in bookmakers
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

    result["bookmaker"] = (
        bookmaker.get("name")
        or
        "Bet 365"
    )

    odds = (
        bookmaker.get("odds")
        or
        {}
    )

    if not isinstance(
        odds,
        dict
    ):

        return result

    result["available_markets"] = list(
        odds.keys()
    )

    snapshot = first_snapshot(
        odds.get("1x2")
    )

    if isinstance(
        snapshot,
        dict
    ):

        result["odds"] = {
            "home": snapshot.get("home"),
            "draw": snapshot.get("draw"),
            "away": snapshot.get("away")
        }

    snapshot = first_snapshot(
        odds.get("btts")
    )

    if isinstance(
        snapshot,
        dict
    ):

        result["btts"] = {
            "yes": snapshot.get("yes"),
            "no": snapshot.get("no")
        }

    fixed_lines = (
        odds.get("goal_line_fixed")
        or
        odds.get("goalline_fixed")
        or
        []
    )

    if isinstance(
        fixed_lines,
        dict
    ):

        fixed_lines = (
            fixed_lines.get("lines")
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
                    item.get("line")
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

            result["totals"][str(line)] = {
                "over": snapshot.get("over"),
                "under": snapshot.get("under")
            }

    snapshot = first_snapshot(
        odds.get("goal_line")
    )

    if isinstance(
        snapshot,
        dict
    ):

        try:

            line = float(
                snapshot.get("line")
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

            result["totals"][str(line)] = {
                "over": snapshot.get("over"),
                "under": snapshot.get("under")
            }

    snapshot = first_snapshot(
        odds.get("asian_handicap")
    )

    if isinstance(
        snapshot,
        dict
    ):

        try:

            home_line = float(
                snapshot.get("line")
            )

        except Exception:

            home_line = None

        if home_line is not None:

            away_line = -home_line

            home_key = (
                str(home_line)
                .rstrip("0")
                .rstrip(".")
            )

            away_key = (
                str(away_line)
                .rstrip("0")
                .rstrip(".")
            )

            result["handicaps"] = {

                "home": {
                    home_key:
                        snapshot.get("home")
                },

                "away": {
                    away_key:
                        snapshot.get("away")
                },

                "main_home_line":
                    home_line,

                "main_away_line":
                    away_line
            }

    return result


def get_league_key_by_id(league_id):

    try:

        return LEAGUE_ID_TO_KEY.get(
            int(league_id)
        )

    except Exception:

        return None


def make_match_from_item(
    item,
    fallback_league_key=None
):

    teams = (
        item.get("teams")
        or
        {}
    )

    home = (
        teams.get("home")
        or
        {}
    )

    away = (
        teams.get("away")
        or
        {}
    )

    league = (
        item.get("league")
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
        LEAGUES.get(league_key)
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

    goals = (
        item.get("goals")
        or
        {}
    )

    parsed = parse_odds_response(
        item.get("odds")
    )

    match = {

        "fixture_id":
            item.get("id"),

        "date":
            item.get("kickoff_utc"),

        "status":
            item.get("status"),

        "status_code":
            item.get("status_code"),

        "league":
            (
                league.get("name")
                or
                league_config.get("name")
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
            home.get("id"),

        "away_team_id":
            away.get("id"),

        "home_logo":
            (
                home.get("logo")
                or
                find_logo_fast(
                    home_name
                )
            ),

        "away_logo":
            (
                away.get("logo")
                or
                find_logo_fast(
                    away_name
                )
            ),

        "home_score":
            goals.get("home"),

        "away_score":
            goals.get("away"),

        "odds":
            parsed.get("odds"),

        "btts":
            parsed.get("btts"),

        "handicaps":
            parsed.get("handicaps"),

        "bookmaker":
            parsed.get("bookmaker"),

        "available_extra_markets":
            parsed.get(
                "available_markets",
                []
            )
    }

    totals = (
        parsed.get("totals")
        or
        {}
    )

    for line in TOTAL_POINTS:

        field = (
            "total_"
            +
            str(line).replace(
                ".",
                "_"
            )
        )

        value = totals.get(
            str(line),
            {}
        )

        if (
            value.get("over")
            is not None
            or
            value.get("under")
            is not None
        ):

            match[field] = {
                "point": line,
                "over": value.get("over"),
                "under": value.get("under")
            }

        else:

            match[field] = None

    return match


FOOTBALL_DATA_FIXTURE_OFFSET = 9000000000000


def football_data_get(
    path,
    params=None
):

    if not FOOTBALL_TOKEN:

        raise RuntimeError(
            "FOOTBALL_DATA_TOKEN not configured"
        )

    response = requests.get(
        FOOTBALL_DATA_URL
        +
        path,

        headers={
            "X-Auth-Token":
                FOOTBALL_TOKEN
        },

        params=(
            params
            or
            {}
        ),

        timeout=
            FOOTBALL_DATA_TIMEOUT_SECONDS
    )

    if not response.ok:

        raise RuntimeError(
            "Football-Data HTTP "
            +
            str(
                response.status_code
            )
        )

    return response.json()


def make_match_from_football_data(
    item,
    league_key
):

    league_config = (
        LEAGUES.get(
            league_key
        )
        or
        {}
    )

    home = (
        item.get(
            "homeTeam"
        )
        or
        {}
    )

    away = (
        item.get(
            "awayTeam"
        )
        or
        {}
    )

    competition = (
        item.get(
            "competition"
        )
        or
        {}
    )

    score = (
        item.get(
            "score"
        )
        or
        {}
    )

    full_time = (
        score.get(
            "fullTime"
        )
        or
        {}
    )

    raw_id = int(
        item.get(
            "id"
        )
        or
        0
    )

    fixture_id = (
        FOOTBALL_DATA_FIXTURE_OFFSET
        +
        raw_id
    )

    match = {

        "fixture_id":
            fixture_id,

        "provider":
            "football-data",

        "provider_fixture_id":
            raw_id,

        "date":
            item.get(
                "utcDate"
            ),

        "status":
            item.get(
                "status"
            ),

        "status_code":
            item.get(
                "status"
            ),

        "league":
            (
                competition.get(
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
            None,

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
            (
                home.get(
                    "name"
                )
                or
                "Unknown"
            ),

        "away":
            (
                away.get(
                    "name"
                )
                or
                "Unknown"
            ),

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
                    "crest"
                )
                or
                find_logo_fast(
                    home.get(
                        "name",
                        ""
                    )
                )
            ),

        "away_logo":
            (
                away.get(
                    "crest"
                )
                or
                find_logo_fast(
                    away.get(
                        "name",
                        ""
                    )
                )
            ),

        "home_score":
            full_time.get(
                "home"
            ),

        "away_score":
            full_time.get(
                "away"
            ),

        "odds":
            None,

        "btts":
            None,

        "handicaps":
            None,

        "bookmaker":
            None,

        "available_extra_markets":
            []
    }

    for line in TOTAL_POINTS:

        match[
            "total_"
            +
            str(
                line
            ).replace(
                ".",
                "_"
            )
        ] = None

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

    return match


def load_football_data_fixtures(
    league_key
):

    league = (
        LEAGUES.get(
            league_key
        )
        or
        {}
    )

    code = league.get(
        "football_data_code"
    )

    if not code:

        return []

    now = datetime.now(
        timezone.utc
    )

    data = football_data_get(
        f"/competitions/{code}/matches",
        {
            "dateFrom":
                now.date().isoformat(),

            "dateTo":
                (
                    now
                    +
                    timedelta(
                        days=
                            MAX_FIXTURE_DAYS
                    )
                ).date().isoformat()
        }
    )

    result = []

    for item in (
        data.get(
            "matches"
        )
        or
        []
    ):

        try:

            result.append(
                make_match_from_football_data(
                    item,
                    league_key
                )
            )

        except Exception as error:

            print(
                "Football-Data parse error:",
                league_key,
                error,
                flush=True
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


def usable_stale_league_cache(
    league_key
):

    cached = (
        league_fixture_cache.get(
            league_key
        )
    )

    if not cached:

        return None

    age = (
        time.time()
        -
        float(
            cached.get(
                "time",
                0
            )
        )
    )

    data = (
        cached.get(
            "data"
        )
        or
        []
    )

    if (
        data
        and
        age
        <=
        STALE_FIXTURES_CACHE_SECONDS
    ):

        return {
            "age":
                age,

            "data":
                data
        }

    return None


def fetch_league_id_fixtures(
    league_key,
    league_id,
    start_ts,
    end_ts
):

    data = five_get(
        f"/v1/leagues/{league_id}/fixtures",
        {
            "status": "scheduled",
            "start_time": start_ts,
            "end_time": end_ts,
            "include": "odds",
            "order": "asc",
            "page": 1,
            "per_page": 50
        },
        attempts=1,
        timeout_seconds=8
    )

    result = []

    for item in (
        data.get("data")
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
                error,
                flush=True
            )

    return result


def schedule_league_refresh(
    league_key
):

    with league_refresh_lock:

        if league_key in league_refreshing:

            return

        league_refreshing.add(
            league_key
        )


    def worker():

        try:

            load_league_fixtures(
                league_key,
                True
            )

        except Exception as error:

            print(
                "Background league refresh error:",
                league_key,
                error,
                flush=True
            )

        finally:

            with league_refresh_lock:

                league_refreshing.discard(
                    league_key
                )


    threading.Thread(
        target=
            worker,

        daemon=
            True,

        name=
            f"league-refresh-{league_key}"
    ).start()


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
    ):

        cache_age = (
            time.time()
            -
            cached[
                "time"
            ]
        )


        if (
            cache_age
            <
            FIXTURES_CACHE_SECONDS
        ):

            league_source_status[
                league_key
            ] = {
                "source":
                    "cache",

                "stale":
                    False,

                "refreshing":
                    False,

                "message":
                    None
            }

            return cached[
                "data"
            ]


        if (
            cache_age
            <=
            STALE_FIXTURES_CACHE_SECONDS
            and
            cached.get(
                "data"
            )
            is not None
        ):

            league_source_status[
                league_key
            ] = {
                "source":
                    "cache",

                "stale":
                    True,

                "refreshing":
                    True,

                "message":
                    "Показаны сохранённые матчи • обновляем в фоне"
            }

            schedule_league_refresh(
                league_key
            )

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
    ]["ids"]

    with ThreadPoolExecutor(
        max_workers=max(
            1,
            min(
                2,
                len(ids)
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

            for league_id in ids
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
                    error,
                    flush=True
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


    primary_result = list(
        unique.values()
    )

    primary_result.sort(
        key=
            lambda match:
                match.get(
                    "date"
                )
                or
                ""
    )


    if primary_result:

        for match in primary_result:

            fixture_id = int(
                match[
                    "fixture_id"
                ]
            )

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

        league_fixture_cache[
            league_key
        ] = {
            "time":
                time.time(),

            "data":
                primary_result
        }

        league_source_status[
            league_key
        ] = {
            "source":
                "five-dollar",

            "stale":
                False,

            "refreshing":
                False,

            "message":
                None
        }

        return primary_result


    stale = (
        usable_stale_league_cache(
            league_key
        )
    )

    if stale:

        league_source_status[
            league_key
        ] = {
            "source":
                "cache",

            "stale":
                True,

            "refreshing":
                False,

            "message":
                "Основной источник временно не дал матчи — показаны сохранённые данные"
        }

        return stale[
            "data"
        ]


    fallback_error = None

    if FOOTBALL_TOKEN:

        try:

            fallback = (
                load_football_data_fixtures(
                    league_key
                )
            )

            if fallback:

                league_fixture_cache[
                    league_key
                ] = {
                    "time":
                        time.time(),

                    "data":
                        fallback
                }

                league_source_status[
                    league_key
                ] = {
                    "source":
                        "football-data",

                    "stale":
                        False,

                    "refreshing":
                        False,

                    "message":
                        "Основной источник недоступен — используется резервное расписание без коэффициентов"
                }

                return fallback

        except Exception as error:

            fallback_error = str(
                error
            )

            print(
                "Football-Data fallback error:",
                league_key,
                error,
                flush=True
            )


    if successful > 0:

        league_fixture_cache[
            league_key
        ] = {
            "time":
                time.time(),

            "data":
                []
        }

        league_source_status[
            league_key
        ] = {
            "source":
                "five-dollar",

            "stale":
                False,

            "refreshing":
                False,

            "message":
                None
        }

        return []


    league_source_status[
        league_key
    ] = {
        "source":
            "error",

        "stale":
            False,

        "refreshing":
            False,

        "message":
            "Не удалось получить данные ни из основного, ни из резервного источника"
    }


    messages = []

    if request_errors:

        messages.append(
            request_errors[
                0
            ]
        )

    if fallback_error:

        messages.append(
            fallback_error
        )

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
            " | ".join(
                messages
            )
            if messages
            else
            ""
        )
    )


def load_default_fixtures(
    force=False
):

    result = []
    failed = []
    succeeded = []

    with ThreadPoolExecutor(
        max_workers=max(
            1,
            min(
                5,
                len(
                    DEFAULT_LEAGUES
                )
            )
        )
    ) as executor:

        future_map = {

            executor.submit(
                load_league_fixtures,
                league_key,
                force
            ):
                league_key

            for league_key in DEFAULT_LEAGUES
        }

        for future in as_completed(
            future_map
        ):

            league_key = future_map[
                future
            ]

            try:

                items = (
                    future.result()
                )

                succeeded.append(
                    league_key
                )

                result.extend(
                    items
                )

            except Exception as error:

                failed.append(
                    league_key
                )

                print(
                    "Top5 load error:",
                    league_key,
                    error,
                    flush=True
                )

    unique = {}

    for match in result:

        try:

            unique[
                int(
                    match[
                        "fixture_id"
                    ]
                )
            ] = match

        except Exception:

            continue

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

    # Если часть лиг не загрузилась, это не ошибка всей вкладки.
    if failed:

        league_source_status[
            "top5"
        ] = {
            "source":
                (
                    "mixed"
                    if result
                    else
                    "partial"
                ),

            "stale":
                False,

            "refreshing":
                False,

            "message":
                (
                    "Часть лиг временно не обновилась"
                    if result
                    else
                    "Матчи временно загружаются дольше обычного"
                )
        }

    elif result:

        league_source_status[
            "top5"
        ] = {
            "source":
                "five-dollar",

            "stale":
                False,

            "refreshing":
                False,

            "message":
                None
        }

    return result


def get_top5_source_status():

    explicit = (
        league_source_status.get(
            "top5"
        )
    )

    if explicit:

        return explicit


    statuses = [
        league_source_status.get(
            key,
            {}
        )
        for key
        in DEFAULT_LEAGUES
    ]


    if any(
        item.get(
            "source"
        )
        ==
        "football-data"
        for item
        in statuses
    ):

        return {
            "source":
                "mixed",

            "stale":
                False,

            "refreshing":
                False,

            "message":
                "Часть матчей загружена из резервного источника"
        }


    if any(
        item.get(
            "refreshing"
        )
        for item
        in statuses
    ):

        return {
            "source":
                "cache",

            "stale":
                True,

            "refreshing":
                True,

            "message":
                "Показаны сохранённые матчи • обновляем в фоне"
        }


    if any(
        item.get(
            "stale"
        )
        for item
        in statuses
    ):

        return {
            "source":
                "cache",

            "stale":
                True,

            "refreshing":
                False,

            "message":
                "Часть матчей показана из сохранённого кэша"
        }


    return {
        "source":
            "five-dollar",

        "stale":
            False,

        "refreshing":
            False,

        "message":
            None
    }


def get_all_cached_matches():

    unique = {}

    for cache in league_fixture_cache.values():

        for match in (
            cache.get("data")
            or
            []
        ):

            fixture_id = match.get(
                "fixture_id"
            )

            if fixture_id:

                unique[
                    int(fixture_id)
                ] = match

    return list(
        unique.values()
    )


def find_cached_fixture(
    fixture_id
):

    key = str(
        int(fixture_id)
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

        return cached["data"]

    return None


def fetch_fixture_odds(
    fixture_id,
    force=False
):

    key = str(
        int(fixture_id)
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

        return cached["data"]

    data = five_get(
        f"/v1/fixtures/{int(fixture_id)}/odds"
    )

    parsed = parse_odds_response(
        data
    )

    odds_cache[key] = {
        "time": time.time(),
        "data": parsed
    }

    return parsed


def apply_parsed_odds_to_match(
    match,
    parsed
):

    match["odds"] = parsed.get(
        "odds"
    )

    match["btts"] = parsed.get(
        "btts"
    )

    match["handicaps"] = parsed.get(
        "handicaps"
    )

    match["bookmaker"] = parsed.get(
        "bookmaker"
    )

    totals = (
        parsed.get("totals")
        or
        {}
    )

    for line in TOTAL_POINTS:

        field = (
            "total_"
            +
            str(line).replace(
                ".",
                "_"
            )
        )

        value = totals.get(
            str(line),
            {}
        )

        if (
            value.get("over")
            is not None
            or
            value.get("under")
            is not None
        ):

            match[field] = {
                "point": line,
                "over": value.get("over"),
                "under": value.get("under")
            }

        else:

            match[field] = None

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
                not match.get("odds")
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
        f"/v1/fixtures/{int(fixture_id)}"
    )

    item = (
        data.get("data")
        or
        {}
    )

    match = make_match_from_item(
        item
    )

    if (
        with_odds
        and
        not match.get("odds")
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
            int(fixture_id)
        )
    ] = {
        "time": time.time(),
        "data": match
    }

    return match



# =========================================================
# MATCH CENTER 2.0
# =========================================================

def _team_outcome(item, team_id):
    teams = item.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    goals = item.get("goals") or {}
    hs, aw = goals.get("home"), goals.get("away")
    is_home = int(home.get("id") or 0) == int(team_id)
    if hs is None or aw is None:
        outcome = None
    else:
        ts, os = (hs, aw) if is_home else (aw, hs)
        outcome = "W" if ts > os else ("L" if ts < os else "D")
    return {
        "fixture_id": item.get("id"),
        "date": item.get("kickoff_utc"),
        "home": home.get("name", "Unknown"),
        "away": away.get("name", "Unknown"),
        "home_id": home.get("id"),
        "away_id": away.get("id"),
        "home_score": hs,
        "away_score": aw,
        "outcome": outcome,
    }


def get_team_form(team_id):
    team_id = int(team_id)
    key = str(team_id)
    cached = team_form_cache.get(key)
    if cached and time.time() - cached["time"] < 900:
        return cached["data"]

    data = five_get(
        f"/v1/teams/{team_id}/fixtures",
        {"status": "finished", "order": "desc", "page": 1, "per_page": 20},
        attempts=1,
        timeout_seconds=7
    )

    items = []
    for item in (data.get("data") or []):
        try:
            items.append(_team_outcome(item, team_id))
        except Exception:
            pass

    result = {"recent": items[:5], "all_recent": items}
    team_form_cache[key] = {"time": time.time(), "data": result}
    return result


def get_league_standings(league_id):
    if not league_id:
        return []
    key = str(int(league_id))
    cached = standings_cache.get(key)
    if cached and time.time() - cached["time"] < 1800:
        return cached["data"]

    data = five_get(
        "/v1/standings",
        {"league": int(league_id), "type": "total"},
        attempts=1,
        timeout_seconds=7
    )
    payload = data.get("data") or {}
    table = payload.get("table") or []
    standings_cache[key] = {"time": time.time(), "data": table}
    return table


def get_match_statistics(fixture_id):
    fixture_id = int(fixture_id)
    key = str(fixture_id)
    cached = match_stats_cache.get(key)
    if cached and time.time() - cached["time"] < 60:
        return cached["data"]

    data = five_get(
        f"/v1/fixtures/{fixture_id}/statistics",
        attempts=1,
        timeout_seconds=6
    )
    payload = data.get("data") or {}
    stats = payload.get("statistics") or {}
    match_stats_cache[key] = {"time": time.time(), "data": stats}
    return stats


def _standing_for(table, team_id, team_name):
    wanted_id = int(team_id or 0)
    wanted_name = normalize_team_name(team_name)
    for row in (table or []):
        team = row.get("team") or {}
        row_id = int(team.get("id") or 0)
        row_name = normalize_team_name(team.get("name", ""))
        if (wanted_id and row_id == wanted_id) or (wanted_name and row_name == wanted_name):
            return {
                "position": row.get("position"),
                "played": row.get("played"),
                "win": row.get("win"),
                "draw": row.get("draw"),
                "lose": row.get("lose"),
                "points": row.get("points"),
            }
    return None


def get_match_center_data(fixture_id):
    fixture_id = int(fixture_id)
    key = str(fixture_id)
    cached = match_center_cache.get(key)
    if cached and time.time() - cached["time"] < 300:
        return cached["data"]

    match = get_fixture(fixture_id, False)

    if match.get("provider") == "football-data":
        return {
            "home_form": [], "away_form": [], "h2h": [],
            "standings": {"home": None, "away": None},
            "statistics": None,
            "availability": {"form": False, "standings": False, "statistics": False},
        }

    home_id = match.get("home_team_id")
    away_id = match.get("away_team_id")
    league_id = match.get("league_id")

    result = {
        "home_form": [], "away_form": [], "h2h": [],
        "standings": {"home": None, "away": None},
        "statistics": None,
        "availability": {"form": False, "standings": False, "statistics": False},
    }

    values = {}
    tasks = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        if home_id:
            tasks[executor.submit(get_team_form, home_id)] = "home_form"
        if away_id:
            tasks[executor.submit(get_team_form, away_id)] = "away_form"
        if league_id:
            tasks[executor.submit(get_league_standings, league_id)] = "standings"

        for future in as_completed(tasks):
            name = tasks[future]
            try:
                values[name] = future.result()
            except Exception as error:
                print("Match center section error:", name, error, flush=True)

    home_data = values.get("home_form")
    away_data = values.get("away_form")
    table = values.get("standings")

    if home_data:
        result["home_form"] = home_data.get("recent") or []
        result["availability"]["form"] = True
        for item in (home_data.get("all_recent") or []):
            if int(away_id or 0) in {int(item.get("home_id") or 0), int(item.get("away_id") or 0)}:
                result["h2h"].append(item)
                if len(result["h2h"]) >= 3:
                    break

    if away_data:
        result["away_form"] = away_data.get("recent") or []
        result["availability"]["form"] = True

    if table:
        result["standings"]["home"] = _standing_for(table, home_id, match.get("home", ""))
        result["standings"]["away"] = _standing_for(table, away_id, match.get("away", ""))
        if result["standings"]["home"] or result["standings"]["away"]:
            result["availability"]["standings"] = True

    kickoff = parse_match_datetime(match.get("date"))
    if kickoff and datetime.now(timezone.utc) >= kickoff:
        try:
            stats = get_match_statistics(fixture_id)
            if stats:
                result["statistics"] = stats
                result["availability"]["statistics"] = True
        except Exception as error:
            print("Match statistics error:", fixture_id, error, flush=True)

    match_center_cache[key] = {"time": time.time(), "data": result}
    return result


# =========================================================
# BET MARKETS
# =========================================================

def normalize_line_key(line):

    return (
        str(
            float(line)
        )
        .rstrip("0")
        .rstrip(".")
    )


def match_market_odd(
    match,
    selection
):

    selection = re.sub(
        r"\s+",
        " ",
        str(
            selection or ""
        ).strip()
    )

    odds = (
        match.get("odds")
        or
        {}
    )

    if selection == "П1":
        return odds.get("home"), "П1"

    if selection == "X":
        return odds.get("draw"), "X"

    if selection == "П2":
        return odds.get("away"), "П2"

    btts = (
        match.get("btts")
        or
        {}
    )

    if selection == "ОЗ Да":
        return btts.get("yes"), "ОЗ Да"

    if selection == "ОЗ Нет":
        return btts.get("no"), "ОЗ Нет"

    total_match = re.fullmatch(
        r"Т([БМ])\s*([0-9.]+)",
        selection
    )

    if total_match:

        line = float(
            total_match.group(2)
        )

        field = (
            "total_"
            +
            str(line).replace(
                ".",
                "_"
            )
        )

        market = (
            match.get(field)
            or
            {}
        )

        side = (
            "over"
            if
            total_match.group(1)
            ==
            "Б"
            else
            "under"
        )

        return (
            market.get(side),
            f"Т{total_match.group(1)} {line}"
        )

    handicap_match = re.fullmatch(
        r"Ф([12])\(([-+]?[0-9.]+)\)",
        selection
    )

    if handicap_match:

        team_number = int(
            handicap_match.group(1)
        )

        line = float(
            handicap_match.group(2)
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
                match.get("handicaps")
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
            f"Ф{team_number}({signed})"
        )

    return None, selection


def resolve_canonical_bet(
    fixture_id,
    selection
):

    match = get_fixture(
        fixture_id,
        True
    )

    kickoff = parse_match_datetime(
        match.get("date")
    )

    if (
        kickoff
        and
        datetime.now(timezone.utc)
        >=
        kickoff
    ):

        raise ValueError(
            "Матч уже начался. Ставки закрыты"
        )

    odd, canonical = match_market_odd(
        match,
        selection
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

        odd, canonical = match_market_odd(
            temp,
            selection
        )

    if odd is None:

        raise ValueError(
            "Этот исход сейчас недоступен"
        )

    odd = round(
        float(odd),
        4
    )

    return {
        "fixture_id": int(fixture_id),
        "match": f"{match['home']} — {match['away']}",
        "selection": canonical,
        "odd": odd,
        "provider": "five-dollar",
        "kickoff_at": kickoff
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
            total_match.group(2)
        )

        if total_match.group(1) == "Б":

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
            handicap_match.group(1)
        )

        handicap = float(
            handicap_match.group(2)
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


# =========================================================
# LIVE / RESULTS
# =========================================================

def is_finished_status(status):

    value = (
        str(
            status or ""
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

    value = str(
        status or ""
    ).strip().lower()

    code = str(
        status_code or ""
    ).strip().lower()

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

    return live, finished


def get_result(fixture_id):

    key = str(
        int(fixture_id)
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

        return cached["data"]

    try:

        data = get_fixture(
            fixture_id,
            False,
            True
        )

        result_cache[key] = {
            "time": time.time(),
            "data": data
        }

        return data

    except Exception as error:

        print(
            "Result fetch error:",
            fixture_id,
            error,
            flush=True
        )

        return None


# =========================================================
# 🔥 LOGIN STREAK
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
        timedelta(days=1)
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
        row[0] or 0
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
            if current_day >= 7
            else
            current_day + 1
        )

        available = False
        streak_broken = False

    elif last_claim_date == yesterday:

        next_day = (
            1
            if current_day >= 7
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

        reward = LOGIN_STREAK_REWARDS[
            day
        ]

        rewards.append({

            "day":
                day,

            "coins":
                int(
                    reward["coins"]
                ),

            "xp":
                int(
                    reward["xp"]
                ),

            "completed":
                (
                    claimed_today
                    and
                    day <= current_day
                ),

            "current":
                (
                    not claimed_today
                    and
                    day == next_day
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

        "next_reward": {
            "coins":
                int(
                    LOGIN_STREAK_REWARDS[
                        next_day
                    ]["coins"]
                ),

            "xp":
                int(
                    LOGIN_STREAK_REWARDS[
                        next_day
                    ]["xp"]
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
        timedelta(days=1)
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
            row[0] or 0
        )

        last_claim_date = (
            row[1]
            if row
            else
            None
        )

        if last_claim_date == today:

            raise ValueError(
                "Награда за сегодня уже получена"
            )

        if last_claim_date == yesterday:

            new_day = (
                1
                if current_day >= 7
                else
                current_day + 1
            )

        else:

            new_day = 1

        reward = LOGIN_STREAK_REWARDS[
            new_day
        ]

        reward_coins = int(
            reward["coins"]
        )

        reward_xp = int(
            reward["xp"]
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

        inserted = cur.fetchone()

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

    fresh = get_user_data(
        telegram_id
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
                fresh["balance"]
            ),

        **xp_info(
            fresh["xp"]
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

    matches_list = get_all_cached_matches()

    if not matches_list:

        matches_list = load_default_fixtures(
            False
        )

    candidates = []

    for match in matches_list:

        kickoff = parse_match_datetime(
            match.get("date")
        )

        if not kickoff:
            continue

        if (
            kickoff
            <=
            now
            +
            timedelta(minutes=15)
        ):
            continue

        # Игра "Угадай исход" работает только
        # с матчами, которые начинаются сегодня.
        if (
            kickoff.astimezone(
                timezone.utc
            ).date()
            !=
            prediction_game_date()
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
                item.get("date")
                or
                ""
    )

    today = str(
        prediction_game_date()
    )

    digest = hashlib.sha256(
        today.encode("utf-8")
    ).hexdigest()

    index = (
        int(
            digest[:8],
            16
        )
        %
        len(candidates)
    )

    return candidates[index]


def ensure_prediction_round():

    today = prediction_game_date()

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

        saved_kickoff = row[6]

        # Старые версии могли записать на сегодняшний
        # игровой день матч из будущего. Такой раунд
        # больше не считаем доступным.
        if (
            saved_kickoff
            and
            saved_kickoff.astimezone(
                timezone.utc
            ).date()
            ==
            today
        ):

            cur.close()
            conn.close()

            return {
                "game_date": row[0],
                "fixture_id": int(row[1]),
                "match_name": row[2],
                "home_team": row[3],
                "away_team": row[4],
                "league_name": row[5],
                "kickoff_at": row[6]
            }

        cur.close()
        conn.close()

        return None

    cur.close()
    conn.close()

    match = choose_prediction_match()

    if not match:
        return None

    kickoff = parse_match_datetime(
        match.get("date")
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
        int(match["fixture_id"]),
        match_name,
        match.get("home"),
        match.get("away"),
        match.get("league"),
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
        "game_date": row[0],
        "fixture_id": int(row[1]),
        "match_name": row[2],
        "home_team": row[3],
        "away_team": row[4],
        "league_name": row[5],
        "kickoff_at": row[6]
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
        int(limit)
    ))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    for row in rows:

        (
            telegram_id,
            game_date,
            fixture_id,
            prediction
        ) = row

        match = get_result(
            fixture_id
        )

        if not match:
            continue

        if not is_finished_status(
            match.get("status")
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

        home_score = int(
            home_score
        )

        away_score = int(
            away_score
        )

        actual_result = prediction_actual_result(
            home_score,
            away_score
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

    game = ensure_prediction_round()

    if not game:

        return {
            "available": False,
            "message": "Сегодня матчей нет — возвращайся завтра ⚽",
            "reward_coins": PREDICTION_REWARD_COINS,
            "reward_xp": PREDICTION_REWARD_XP
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
        game["game_date"]
    ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    kickoff = game[
        "kickoff_at"
    ]

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

        "available": True,

        "game_date":
            game["game_date"].isoformat(),

        "fixture_id":
            game["fixture_id"],

        "match_name":
            game["match_name"],

        "home_team":
            game["home_team"],

        "away_team":
            game["away_team"],

        "league":
            game["league_name"],

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
                bool(row[1]),

            "won":
                row[2],

            "final_score":
                row[3],

            "actual_result":
                row[4],

            "reward_coins":
                (
                    int(row[5] or 0)
                    if row[1]
                    else
                    PREDICTION_REWARD_COINS
                ),

            "reward_xp":
                (
                    int(row[6] or 0)
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
        prediction or ""
    ).strip().upper()

    if prediction not in {
        "П1",
        "X",
        "П2"
    }:

        raise ValueError(
            "Выбери П1, X или П2"
        )

    game = ensure_prediction_round()

    if not game:

        raise ValueError(
            "Сейчас нет доступного матча"
        )

    kickoff = game[
        "kickoff_at"
    ]

    if (
        not kickoff
        or
        datetime.now(timezone.utc)
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
            game["game_date"],
            game["fixture_id"],
            prediction
        ))

        inserted = cur.fetchone()

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
# ⚽ УГАДАЙ СЧЁТ
# =========================================================

def score_game_date():

    return datetime.now(
        timezone.utc
    ).date()


def score_result_type(
    home_score,
    away_score
):

    if home_score > away_score:
        return "П1"

    if home_score < away_score:
        return "П2"

    return "X"


def choose_score_game_match():

    now = datetime.now(
        timezone.utc
    )

    matches_list = get_all_cached_matches()

    if not matches_list:

        matches_list = load_default_fixtures(
            False
        )

    candidates = []

    for match in matches_list:

        kickoff = parse_match_datetime(
            match.get("date")
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

        # Игра "Точный счёт" работает только
        # с матчами, которые начинаются сегодня.
        if (
            kickoff.astimezone(
                timezone.utc
            ).date()
            !=
            score_game_date()
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
                item.get("date")
                or
                ""
    )

    today_key = (
        "score-game-"
        +
        str(
            score_game_date()
        )
    )

    digest = hashlib.sha256(
        today_key.encode(
            "utf-8"
        )
    ).hexdigest()

    index = (
        int(
            digest[:8],
            16
        )
        %
        len(candidates)
    )

    chosen = candidates[
        index
    ]

    if (
        len(candidates) > 1
    ):

        prediction_round = None

        try:

            prediction_round = (
                ensure_prediction_round()
            )

        except Exception:

            prediction_round = None

        if (
            prediction_round
            and
            int(
                prediction_round[
                    "fixture_id"
                ]
            )
            ==
            int(
                chosen[
                    "fixture_id"
                ]
            )
        ):

            chosen = candidates[
                (
                    index
                    +
                    1
                )
                %
                len(
                    candidates
                )
            ]

    return chosen


def ensure_score_game_round():

    today = score_game_date()

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

        FROM score_game_rounds

        WHERE game_date = %s
    """, (
        today,
    ))

    row = cur.fetchone()

    if row:

        saved_kickoff = row[6]

        # Не показываем сохранённый раунд, если сам матч
        # фактически проходит не сегодня.
        if (
            saved_kickoff
            and
            saved_kickoff.astimezone(
                timezone.utc
            ).date()
            ==
            today
        ):

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

        return None

    cur.close()
    conn.close()

    match = choose_score_game_match()

    if not match:

        return None

    kickoff = parse_match_datetime(
        match.get(
            "date"
        )
    )

    match_name = (
        f"{match.get('home')} — "
        f"{match.get('away')}"
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO score_game_rounds (
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

        FROM score_game_rounds

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


def settle_score_game_picks(
    limit=30
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            p.telegram_id,
            p.game_date,
            p.fixture_id,
            p.predicted_home,
            p.predicted_away

        FROM score_game_picks p

        JOIN score_game_rounds r
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

    rows = cur.fetchall()

    cur.close()
    conn.close()

    for row in rows:

        (
            telegram_id,
            game_date,
            fixture_id,
            predicted_home,
            predicted_away
        ) = row

        match = get_result(
            fixture_id
        )

        if not match:

            continue

        if not is_finished_status(
            match.get(
                "status"
            )
        ):

            continue

        final_home = match.get(
            "home_score"
        )

        final_away = match.get(
            "away_score"
        )

        if (
            final_home is None
            or
            final_away is None
        ):

            continue

        final_home = int(
            final_home
        )

        final_away = int(
            final_away
        )

        predicted_home = int(
            predicted_home
        )

        predicted_away = int(
            predicted_away
        )

        exact_win = (
            predicted_home
            ==
            final_home
            and
            predicted_away
            ==
            final_away
        )

        predicted_result = (
            score_result_type(
                predicted_home,
                predicted_away
            )
        )

        actual_result = (
            score_result_type(
                final_home,
                final_away
            )
        )

        outcome_win = (
            not exact_win
            and
            predicted_result
            ==
            actual_result
        )

        if exact_win:

            reward_coins = (
                SCORE_GAME_EXACT_COINS
            )

            reward_xp = (
                SCORE_GAME_EXACT_XP
            )

        elif outcome_win:

            reward_coins = (
                SCORE_GAME_OUTCOME_COINS
            )

            reward_xp = (
                SCORE_GAME_OUTCOME_XP
            )

        else:

            reward_coins = 0
            reward_xp = 0

        conn = get_db()
        cur = conn.cursor()

        try:

            cur.execute("""
                UPDATE score_game_picks

                SET
                    settled = TRUE,

                    exact_win = %s,

                    outcome_win = %s,

                    final_home = %s,

                    final_away = %s,

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
                exact_win,
                outcome_win,
                final_home,
                final_away,
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


def get_score_game(
    telegram_id
):

    settle_score_game_picks(
        10
    )

    game = ensure_score_game_round()

    if not game:

        return {

            "available":
                False,

            "message":
                "Сегодня матчей нет — возвращайся завтра ⚽",

            "exact_reward_coins":
                SCORE_GAME_EXACT_COINS,

            "exact_reward_xp":
                SCORE_GAME_EXACT_XP,

            "outcome_reward_coins":
                SCORE_GAME_OUTCOME_COINS
        }

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            predicted_home,
            predicted_away,
            settled,
            exact_win,
            outcome_win,
            final_home,
            final_away,
            reward_coins,
            reward_xp,
            created_at

        FROM score_game_picks

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

    cur.execute("""
        SELECT
            COUNT(*)::INTEGER
        FROM score_game_picks
        WHERE game_date = %s
    """, (
        game[
            "game_date"
        ],
    ))

    predictions_count_row = (
        cur.fetchone()
    )

    predictions_count = int(
        predictions_count_row[0]
        or
        0
    )

    cur.close()
    conn.close()

    score_stats = (
        get_score_game_stats(
            telegram_id
        )
    )

    kickoff = game[
        "kickoff_at"
    ]

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

        "predicted_home":
            None,

        "predicted_away":
            None,

        "settled":
            False,

        "exact_win":
            None,

        "outcome_win":
            None,

        "final_home":
            None,

        "final_away":
            None,

        "reward_coins":
            0,

        "reward_xp":
            0,

        "exact_reward_coins":
            SCORE_GAME_EXACT_COINS,

        "exact_reward_xp":
            SCORE_GAME_EXACT_XP,

        "outcome_reward_coins":
            SCORE_GAME_OUTCOME_COINS,

        "predictions_count":
            predictions_count,

        "current_streak":
            int(
                score_stats.get(
                    "current_streak",
                    0
                )
                or
                0
            ),

        "best_streak":
            int(
                score_stats.get(
                    "best_streak",
                    0
                )
                or
                0
            )
    }

    if row:

        result.update({

            "predicted_home":
                int(
                    row[0]
                ),

            "predicted_away":
                int(
                    row[1]
                ),

            "settled":
                bool(
                    row[2]
                ),

            "exact_win":
                row[3],

            "outcome_win":
                row[4],

            "final_home":
                (
                    int(
                        row[5]
                    )
                    if row[5] is not None
                    else
                    None
                ),

            "final_away":
                (
                    int(
                        row[6]
                    )
                    if row[6] is not None
                    else
                    None
                ),

            "reward_coins":
                int(
                    row[7]
                    or
                    0
                ),

            "reward_xp":
                int(
                    row[8]
                    or
                    0
                ),

            "picked_at":
                (
                    row[9].isoformat()
                    if row[9]
                    else
                    None
                )
        })

    return result



def get_score_game_history(
    telegram_id,
    limit=50
):

    settle_score_game_picks(
        30
    )

    try:

        limit = int(
            limit
        )

    except Exception:

        limit = 50

    limit = max(
        1,
        min(
            limit,
            100
        )
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            p.game_date,
            p.fixture_id,

            r.match_name,
            r.home_team,
            r.away_team,
            r.league_name,
            r.kickoff_at,

            p.predicted_home,
            p.predicted_away,

            p.settled,
            p.exact_win,
            p.outcome_win,

            p.final_home,
            p.final_away,

            p.reward_coins,
            p.reward_xp,

            p.created_at,
            p.settled_at

        FROM score_game_picks p

        LEFT JOIN score_game_rounds r
            ON
                r.game_date =
                    p.game_date
                AND
                r.fixture_id =
                    p.fixture_id

        WHERE
            p.telegram_id = %s

        ORDER BY
            p.game_date DESC,
            p.created_at DESC

        LIMIT %s
    """, (
        telegram_id,
        limit
    ))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    history = []

    for row in rows:

        settled = bool(
            row[9]
        )

        exact_win = row[10]
        outcome_win = row[11]

        if not settled:

            status = "pending"
            status_text = "Ожидает"

        elif exact_win is True:

            status = "exact"
            status_text = "Точный счёт"

        elif outcome_win is True:

            status = "outcome"
            status_text = "Исход угадан"

        else:

            status = "lost"
            status_text = "Не угадано"

        history.append({

            "game_date":
                (
                    row[0].isoformat()
                    if row[0]
                    else
                    None
                ),

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

            "league":
                row[5],

            "kickoff_at":
                (
                    row[6].isoformat()
                    if row[6]
                    else
                    None
                ),

            "predicted_home":
                int(
                    row[7]
                ),

            "predicted_away":
                int(
                    row[8]
                ),

            "settled":
                settled,

            "exact_win":
                exact_win,

            "outcome_win":
                outcome_win,

            "final_home":
                (
                    int(
                        row[12]
                    )
                    if row[12] is not None
                    else
                    None
                ),

            "final_away":
                (
                    int(
                        row[13]
                    )
                    if row[13] is not None
                    else
                    None
                ),

            "reward_coins":
                int(
                    row[14]
                    or
                    0
                ),

            "reward_xp":
                int(
                    row[15]
                    or
                    0
                ),

            "picked_at":
                (
                    row[16].isoformat()
                    if row[16]
                    else
                    None
                ),

            "settled_at":
                (
                    row[17].isoformat()
                    if row[17]
                    else
                    None
                ),

            "status":
                status,

            "status_text":
                status_text
        })

    return history


def get_score_game_stats(telegram_id):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE settled = FALSE) AS pending,
            COUNT(*) FILTER (WHERE settled = TRUE) AS settled,
            COUNT(*) FILTER (WHERE settled = TRUE AND exact_win = TRUE) AS exact_wins,
            COUNT(*) FILTER (WHERE settled = TRUE AND exact_win IS NOT TRUE AND outcome_win = TRUE) AS outcome_wins,
            COUNT(*) FILTER (WHERE settled = TRUE AND exact_win IS NOT TRUE AND outcome_win IS NOT TRUE) AS losses
        FROM score_game_picks
        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    row = cur.fetchone()

    cur.execute("""
        SELECT DISTINCT game_date
        FROM score_game_picks
        WHERE telegram_id = %s
        ORDER BY game_date ASC
    """, (
        telegram_id,
    ))

    prediction_dates = [
        item[0]
        for item in cur.fetchall()
        if item[0] is not None
    ]

    cur.close()
    conn.close()

    total = int(row[0] or 0)
    pending = int(row[1] or 0)
    settled = int(row[2] or 0)
    exact_wins = int(row[3] or 0)
    outcome_wins = int(row[4] or 0)
    losses = int(row[5] or 0)

    successful = exact_wins + outcome_wins

    success_rate = (
        round(
            successful * 100 / settled,
            1
        )
        if settled > 0
        else 0
    )

    exact_rate = (
        round(
            exact_wins * 100 / settled,
            1
        )
        if settled > 0
        else 0
    )

    best_streak = 0
    running_streak = 0
    previous_date = None

    for prediction_date in prediction_dates:

        if (
            previous_date is not None
            and
            prediction_date
            ==
            previous_date
            +
            timedelta(days=1)
        ):

            running_streak += 1

        else:

            running_streak = 1

        best_streak = max(
            best_streak,
            running_streak
        )

        previous_date = prediction_date

    current_streak = 0

    if prediction_dates:

        today = score_game_date()
        latest_date = prediction_dates[-1]

        if latest_date in (
            today,
            today - timedelta(days=1)
        ):

            current_streak = 1
            expected_date = latest_date - timedelta(days=1)

            for prediction_date in reversed(
                prediction_dates[:-1]
            ):

                if prediction_date == expected_date:

                    current_streak += 1
                    expected_date -= timedelta(days=1)

                elif prediction_date < expected_date:

                    break

    achievements = [
        {
            "key": "first_exact",
            "icon": "🎯",
            "title": "В яблочко",
            "description": "Угадать первый точный счёт",
            "progress": min(exact_wins, 1),
            "target": 1,
            "unlocked": exact_wins >= 1
        },
        {
            "key": "exact_3",
            "icon": "🏹",
            "title": "Снайпер",
            "description": "Угадать 3 точных счёта",
            "progress": min(exact_wins, 3),
            "target": 3,
            "unlocked": exact_wins >= 3
        },
        {
            "key": "predictions_10",
            "icon": "📋",
            "title": "Прогнозист",
            "description": "Сделать 10 прогнозов",
            "progress": min(total, 10),
            "target": 10,
            "unlocked": total >= 10
        },
        {
            "key": "predictions_50",
            "icon": "🧠",
            "title": "Эксперт",
            "description": "Сделать 50 прогнозов",
            "progress": min(total, 50),
            "target": 50,
            "unlocked": total >= 50
        },
        {
            "key": "streak_5",
            "icon": "🔥",
            "title": "На серии",
            "description": "Делать прогнозы 5 дней подряд",
            "progress": min(best_streak, 5),
            "target": 5,
            "unlocked": best_streak >= 5
        },
        {
            "key": "successful_5",
            "icon": "✅",
            "title": "Чую результат",
            "description": "Угадать исход или точный счёт 5 раз",
            "progress": min(successful, 5),
            "target": 5,
            "unlocked": successful >= 5
        }
    ]

    return {
        "total": total,
        "pending": pending,
        "settled": settled,
        "exact_wins": exact_wins,
        "outcome_wins": outcome_wins,
        "losses": losses,
        "successful": successful,
        "success_rate": success_rate,
        "exact_rate": exact_rate,
        "current_streak": current_streak,
        "best_streak": best_streak,
        "achievements": achievements
    }


def get_score_game_leaderboard(
    telegram_id,
    limit=50
):

    try:
        limit = int(limit)
    except Exception:
        limit = 50

    limit = max(
        1,
        min(
            limit,
            100
        )
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        WITH distinct_dates AS (
            SELECT DISTINCT
                telegram_id,
                game_date
            FROM score_game_picks
        ),

        numbered_dates AS (
            SELECT
                telegram_id,
                game_date,
                game_date
                -
                (
                    ROW_NUMBER() OVER (
                        PARTITION BY telegram_id
                        ORDER BY game_date
                    )
                )::INTEGER
                AS streak_group
            FROM distinct_dates
        ),

        streaks AS (
            SELECT
                telegram_id,
                COUNT(*)::INTEGER AS streak_length
            FROM numbered_dates
            GROUP BY
                telegram_id,
                streak_group
        ),

        best_streaks AS (
            SELECT
                telegram_id,
                MAX(streak_length)::INTEGER AS best_streak
            FROM streaks
            GROUP BY telegram_id
        ),

        aggregated AS (
            SELECT
                u.telegram_id,
                COALESCE(
                    NULLIF(u.first_name, ''),
                    NULLIF(u.username, ''),
                    'Игрок'
                ) AS display_name,
                COALESCE(u.xp, 0)::INTEGER AS xp,

                COUNT(p.*)::INTEGER AS total,

                COUNT(*) FILTER (
                    WHERE p.settled = TRUE
                )::INTEGER AS settled,

                COUNT(*) FILTER (
                    WHERE
                        p.settled = TRUE
                        AND
                        p.exact_win = TRUE
                )::INTEGER AS exact_wins,

                COUNT(*) FILTER (
                    WHERE
                        p.settled = TRUE
                        AND
                        p.exact_win IS NOT TRUE
                        AND
                        p.outcome_win = TRUE
                )::INTEGER AS outcome_wins

            FROM users u

            JOIN score_game_picks p
                ON p.telegram_id = u.telegram_id

            GROUP BY
                u.telegram_id,
                u.first_name,
                u.username,
                u.xp
        ),

        metrics AS (
            SELECT
                a.*,

                (
                    a.exact_wins
                    +
                    a.outcome_wins
                )::INTEGER AS successful,

                CASE
                    WHEN a.settled > 0
                    THEN ROUND(
                        (
                            a.exact_wins
                            +
                            a.outcome_wins
                        )
                        *
                        100.0
                        /
                        a.settled,
                        1
                    )
                    ELSE 0
                END AS success_rate,

                COALESCE(
                    bs.best_streak,
                    0
                )::INTEGER AS best_streak

            FROM aggregated a

            LEFT JOIN best_streaks bs
                ON bs.telegram_id = a.telegram_id
        ),

        ranked AS (
            SELECT
                *,

                ROW_NUMBER() OVER (
                    ORDER BY
                        exact_wins DESC,
                        successful DESC,
                        success_rate DESC,
                        best_streak DESC,
                        settled DESC,
                        total DESC,
                        xp DESC,
                        telegram_id ASC
                )::INTEGER AS leaderboard_rank

            FROM metrics
        )

        SELECT
            leaderboard_rank,
            telegram_id,
            display_name,
            total,
            settled,
            exact_wins,
            outcome_wins,
            successful,
            success_rate,
            best_streak

        FROM ranked

        WHERE
            leaderboard_rank <= %s
            OR
            telegram_id = %s

        ORDER BY leaderboard_rank ASC
    """, (
        limit,
        telegram_id
    ))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    players = []
    my_entry = None

    for row in rows:

        item = {
            "rank": int(row[0]),
            "telegram_id": int(row[1]),
            "first_name": row[2] or "Игрок",
            "total": int(row[3] or 0),
            "settled": int(row[4] or 0),
            "exact_wins": int(row[5] or 0),
            "outcome_wins": int(row[6] or 0),
            "successful": int(row[7] or 0),
            "success_rate": float(row[8] or 0),
            "best_streak": int(row[9] or 0)
        }

        if item["rank"] <= limit:
            players.append(item)

        if int(item["telegram_id"]) == int(telegram_id):
            my_entry = item

    return {
        "players": players,
        "my_rank": (
            my_entry["rank"]
            if my_entry
            else None
        ),
        "me": my_entry
    }



def _predictor_league_code():

    alphabet = (
        "ABCDEFGHJKLMNPQRSTUVWXYZ"
        "23456789"
    )

    for _ in range(30):

        code = "".join(
            secrets.choice(
                alphabet
            )
            for _ in range(6)
        )

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT 1
            FROM predictor_leagues
            WHERE invite_code = %s
        """, (
            code,
        ))

        exists = cur.fetchone()

        cur.close()
        conn.close()

        if not exists:
            return code

    raise RuntimeError(
        "Не удалось создать код лиги"
    )


def get_predictor_leagues(
    telegram_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            l.id,
            l.name,
            l.invite_code,
            l.owner_telegram_id,
            l.created_at,
            COUNT(m2.telegram_id)::INTEGER AS members_count

        FROM predictor_leagues l

        JOIN predictor_league_members mine
            ON mine.league_id = l.id
            AND mine.telegram_id = %s

        LEFT JOIN predictor_league_members m2
            ON m2.league_id = l.id

        GROUP BY
            l.id,
            l.name,
            l.invite_code,
            l.owner_telegram_id,
            l.created_at

        ORDER BY
            l.created_at DESC
    """, (
        telegram_id,
    ))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {
            "id": int(row[0]),
            "name": row[1],
            "invite_code": row[2],
            "owner_telegram_id": int(row[3]),
            "is_owner": (
                int(row[3])
                ==
                int(telegram_id)
            ),
            "created_at": (
                row[4].isoformat()
                if row[4]
                else None
            ),
            "members_count": int(
                row[5]
                or
                0
            )
        }
        for row in rows
    ]


def create_predictor_league(
    telegram_id,
    name
):

    name = str(
        name
        or
        ""
    ).strip()

    if len(name) < 2:
        raise ValueError(
            "Название лиги слишком короткое"
        )

    if len(name) > 32:
        raise ValueError(
            "Название лиги — максимум 32 символа"
        )

    code = _predictor_league_code()

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO predictor_leagues (
                owner_telegram_id,
                name,
                invite_code
            )
            VALUES (
                %s,
                %s,
                %s
            )
            RETURNING id
        """, (
            telegram_id,
            name,
            code
        ))

        league_id = int(
            cur.fetchone()[0]
        )

        cur.execute("""
            INSERT INTO predictor_league_members (
                league_id,
                telegram_id
            )
            VALUES (
                %s,
                %s
            )
            ON CONFLICT DO NOTHING
        """, (
            league_id,
            telegram_id
        ))

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()

    return {
        "league_id": league_id,
        "invite_code": code
    }


def join_predictor_league(
    telegram_id,
    invite_code
):

    code = str(
        invite_code
        or
        ""
    ).strip().upper()

    if not code:
        raise ValueError(
            "Введи код приглашения"
        )

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
            SELECT
                id,
                name
            FROM predictor_leagues
            WHERE invite_code = %s
        """, (
            code,
        ))

        row = cur.fetchone()

        if not row:
            raise ValueError(
                "Лига с таким кодом не найдена"
            )

        league_id = int(
            row[0]
        )

        cur.execute("""
            INSERT INTO predictor_league_members (
                league_id,
                telegram_id
            )
            VALUES (
                %s,
                %s
            )
            ON CONFLICT DO NOTHING
        """, (
            league_id,
            telegram_id
        ))

        joined = (
            cur.rowcount
            ==
            1
        )

        conn.commit()

        return {
            "league_id": league_id,
            "name": row[1],
            "joined": joined
        }

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()


def leave_predictor_league(
    telegram_id,
    league_id
):

    league_id = int(
        league_id
    )

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
            SELECT
                owner_telegram_id
            FROM predictor_leagues
            WHERE id = %s
        """, (
            league_id,
        ))

        row = cur.fetchone()

        if not row:
            raise ValueError(
                "Лига не найдена"
            )

        if (
            int(row[0])
            ==
            int(telegram_id)
        ):
            raise ValueError(
                "Создатель не может выйти из лиги"
            )

        cur.execute("""
            DELETE FROM predictor_league_members
            WHERE
                league_id = %s
                AND
                telegram_id = %s
        """, (
            league_id,
            telegram_id
        ))

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()



def delete_predictor_league(
    telegram_id,
    league_id
):

    league_id = int(
        league_id
    )

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
            SELECT
                owner_telegram_id
            FROM predictor_leagues
            WHERE id = %s
        """, (
            league_id,
        ))

        row = cur.fetchone()

        if not row:
            raise ValueError(
                "Лига не найдена"
            )

        if (
            int(row[0])
            !=
            int(telegram_id)
        ):
            raise ValueError(
                "Удалить лигу может только её создатель"
            )

        cur.execute("""
            DELETE FROM predictor_leagues
            WHERE
                id = %s
                AND
                owner_telegram_id = %s
        """, (
            league_id,
            telegram_id
        ))

        if cur.rowcount != 1:
            raise ValueError(
                "Не удалось удалить лигу"
            )

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()
        conn.close()



def get_predictor_league_leaderboard(
    telegram_id,
    league_id
):

    league_id = int(
        league_id
    )

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            l.id,
            l.name,
            l.invite_code,
            l.owner_telegram_id
        FROM predictor_leagues l

        JOIN predictor_league_members m
            ON m.league_id = l.id

        WHERE
            l.id = %s
            AND
            m.telegram_id = %s
    """, (
        league_id,
        telegram_id
    ))

    league_row = cur.fetchone()

    if not league_row:

        cur.close()
        conn.close()

        raise ValueError(
            "Ты не состоишь в этой лиге"
        )

    cur.execute("""
        WITH distinct_dates AS (
            SELECT DISTINCT
                p.telegram_id,
                p.game_date
            FROM score_game_picks p

            JOIN predictor_league_members lm
                ON lm.telegram_id = p.telegram_id
                AND lm.league_id = %s
        ),

        numbered_dates AS (
            SELECT
                telegram_id,
                game_date,
                game_date
                -
                (
                    ROW_NUMBER() OVER (
                        PARTITION BY telegram_id
                        ORDER BY game_date
                    )
                )::INTEGER AS streak_group
            FROM distinct_dates
        ),

        streaks AS (
            SELECT
                telegram_id,
                COUNT(*)::INTEGER AS streak_length
            FROM numbered_dates
            GROUP BY
                telegram_id,
                streak_group
        ),

        best_streaks AS (
            SELECT
                telegram_id,
                MAX(streak_length)::INTEGER AS best_streak
            FROM streaks
            GROUP BY telegram_id
        ),

        aggregated AS (
            SELECT
                u.telegram_id,

                COALESCE(
                    NULLIF(u.first_name, ''),
                    NULLIF(u.username, ''),
                    'Игрок'
                ) AS display_name,

                COUNT(p.*)::INTEGER AS total,

                COUNT(*) FILTER (
                    WHERE p.settled = TRUE
                )::INTEGER AS settled,

                COUNT(*) FILTER (
                    WHERE
                        p.settled = TRUE
                        AND
                        p.exact_win = TRUE
                )::INTEGER AS exact_wins,

                COUNT(*) FILTER (
                    WHERE
                        p.settled = TRUE
                        AND
                        p.exact_win IS NOT TRUE
                        AND
                        p.outcome_win = TRUE
                )::INTEGER AS outcome_wins

            FROM predictor_league_members lm

            JOIN users u
                ON u.telegram_id = lm.telegram_id

            LEFT JOIN score_game_picks p
                ON p.telegram_id = u.telegram_id

            WHERE lm.league_id = %s

            GROUP BY
                u.telegram_id,
                u.first_name,
                u.username
        ),

        metrics AS (
            SELECT
                a.*,

                (
                    a.exact_wins
                    +
                    a.outcome_wins
                )::INTEGER AS successful,

                CASE
                    WHEN a.settled > 0
                    THEN ROUND(
                        (
                            a.exact_wins
                            +
                            a.outcome_wins
                        )
                        *
                        100.0
                        /
                        a.settled,
                        1
                    )
                    ELSE 0
                END AS success_rate,

                COALESCE(
                    bs.best_streak,
                    0
                )::INTEGER AS best_streak

            FROM aggregated a

            LEFT JOIN best_streaks bs
                ON bs.telegram_id = a.telegram_id
        )

        SELECT
            telegram_id,
            display_name,
            total,
            settled,
            exact_wins,
            outcome_wins,
            successful,
            success_rate,
            best_streak

        FROM metrics

        ORDER BY
            exact_wins DESC,
            successful DESC,
            success_rate DESC,
            best_streak DESC,
            settled DESC,
            total DESC,
            telegram_id ASC
    """, (
        league_id,
        league_id
    ))

    rows = cur.fetchall()

    cur.close()
    conn.close()

    players = []

    for index, row in enumerate(
        rows,
        start=1
    ):

        players.append({
            "rank": index,
            "telegram_id": int(row[0]),
            "first_name": row[1] or "Игрок",
            "total": int(row[2] or 0),
            "settled": int(row[3] or 0),
            "exact_wins": int(row[4] or 0),
            "outcome_wins": int(row[5] or 0),
            "successful": int(row[6] or 0),
            "success_rate": float(row[7] or 0),
            "best_streak": int(row[8] or 0)
        })

    return {
        "league": {
            "id": int(league_row[0]),
            "name": league_row[1],
            "invite_code": league_row[2],
            "owner_telegram_id": int(league_row[3]),
            "is_owner": (
                int(league_row[3])
                ==
                int(telegram_id)
            )
        },
        "players": players
    }



def make_score_game_pick(
    telegram_id,
    predicted_home,
    predicted_away
):

    try:

        predicted_home = int(
            predicted_home
        )

        predicted_away = int(
            predicted_away
        )

    except Exception:

        raise ValueError(
            "Укажи правильный счёт"
        )

    if (
        predicted_home < 0
        or
        predicted_away < 0
    ):

        raise ValueError(
            "Счёт не может быть отрицательным"
        )

    if (
        predicted_home
        >
        SCORE_GAME_MAX_SCORE
        or
        predicted_away
        >
        SCORE_GAME_MAX_SCORE
    ):

        raise ValueError(
            "Максимум 10 голов у одной команды"
        )

    game = ensure_score_game_round()

    if not game:

        raise ValueError(
            "Сейчас нет доступного матча"
        )

    kickoff = game[
        "kickoff_at"
    ]

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
            INSERT INTO score_game_picks (
                telegram_id,
                game_date,
                fixture_id,
                predicted_home,
                predicted_away
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
                game_date
            )
            DO NOTHING

            RETURNING
                predicted_home,
                predicted_away
        """, (
            telegram_id,
            game[
                "game_date"
            ],
            game[
                "fixture_id"
            ],
            predicted_home,
            predicted_away
        ))

        inserted = cur.fetchone()

        if not inserted:

            raise ValueError(
                "Ты уже указал счёт на сегодня"
            )

        conn.commit()

    except Exception:

        conn.rollback()

        raise

    finally:

        cur.close()
        conn.close()

    return get_score_game(
        telegram_id
    )
# =========================================================
# 🎡 WHEEL
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
            item["weight"]
        )
        for item in WHEEL_REWARDS
    )

    ticket = secrets.randbelow(
        total_weight
    )

    cursor = 0

    for item in WHEEL_REWARDS:

        cursor += int(
            item["weight"]
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

        reward = choose_wheel_reward()

        reward_type = str(
            reward["type"]
        )

        reward_value = int(
            reward["value"]
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

    fresh = get_user_data(
        telegram_id
    )

    return {

        "reward_type":
            reward_type,

        "reward_value":
            reward_value,

        "reward_label":
            reward["label"],

        "balance":
            int(
                fresh["balance"]
            ),

        **xp_info(
            fresh["xp"]
        ),

        "wheel":
            get_wheel_status(
                telegram_id
            )
    }


# =========================================================
# 🎟 PROMO
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

    if (
        len(code)
        >
        32
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
                user["balance"]
            ),

        "xp":
            int(
                user["xp"]
                or
                0
            )
    }


# =========================================================
# СТАВКИ — РАСЧЁТ
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
            not is_finished_status(
                match.get("status")
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
                            balance
                            +
                            %s,

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

    parlays_rows = cur.fetchall()

    for (
        parlay_id,
        amount
    ) in parlays_rows:

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
                not is_finished_status(
                    match.get("status")
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

        if (
            effective_odd
            <=
            1.000001
        ):

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
                        balance
                        +
                        %s,

                    updated_at =
                        NOW()

                WHERE telegram_id = %s
            """, (
                payout,
                telegram_id
            ))

            if (
                final_status
                ==
                "Выиграла"
            ):

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
# ИСТОРИЯ СТАВОК
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
                    else
                    None
                )
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

            for leg in cur.fetchall()
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

            "settled_at":
                (
                    row[7].isoformat()
                    if row[7]
                    else
                    None
                ),

            "legs":
                legs
        })

    cur.close()
    conn.close()

    return result



def get_profile_extra(
    telegram_id
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            COUNT(*)::INTEGER,
            COUNT(*) FILTER (
                WHERE settled = TRUE
            )::INTEGER,
            COUNT(*) FILTER (
                WHERE
                    settled = TRUE
                    AND
                    (
                        exact_win = TRUE
                        OR
                        outcome_win = TRUE
                    )
            )::INTEGER,
            COUNT(*) FILTER (
                WHERE
                    settled = TRUE
                    AND
                    exact_win = TRUE
            )::INTEGER

        FROM score_game_picks

        WHERE telegram_id = %s
        """,
        (
            int(
                telegram_id
            ),
        )
    )

    row = (
        cur.fetchone()
        or
        (
            0,
            0,
            0,
            0
        )
    )

    cur.execute(
        """
        SELECT COUNT(*)::INTEGER
        FROM predictor_league_members
        WHERE telegram_id = %s
        """,
        (
            int(
                telegram_id
            ),
        )
    )

    league_count_row = (
        cur.fetchone()
        or
        (
            0,
        )
    )

    cur.close()
    conn.close()

    total_predictions = int(
        row[0]
        or
        0
    )

    settled_predictions = int(
        row[1]
        or
        0
    )

    successful_predictions = int(
        row[2]
        or
        0
    )

    exact_wins = int(
        row[3]
        or
        0
    )

    success_rate = (
        round(
            successful_predictions
            /
            settled_predictions
            *
            100
        )
        if settled_predictions > 0
        else
        0
    )

    score_stats = (
        get_score_game_stats(
            telegram_id
        )
    )

    if exact_wins >= 25:
        title = "Мастер прогнозов"
    elif exact_wins >= 10:
        title = "Эксперт"
    elif successful_predictions >= 10:
        title = "Аналитик"
    else:
        title = "Новичок"

    return {
        "title":
            title,

        "prediction_total":
            total_predictions,

        "prediction_successful":
            successful_predictions,

        "prediction_exact":
            exact_wins,

        "prediction_success_rate":
            int(
                success_rate
            ),

        "current_streak":
            int(
                score_stats.get(
                    "current_streak",
                    0
                )
                or
                0
            ),

        "best_streak":
            int(
                score_stats.get(
                    "best_streak",
                    0
                )
                or
                0
            ),

        "private_leagues":
            int(
                league_count_row[0]
                or
                0
            )
    }


# =========================================================
# 📊 PROFILE STATS
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
            )

        FROM bets

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    row = cur.fetchone()

    total = int(
        row[0]
        or
        0
    )

    active = int(
        row[1]
        or
        0
    )

    wins = int(
        row[2]
        or
        0
    )

    losses = int(
        row[3]
        or
        0
    )

    refunds = int(
        row[4]
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

    prediction = cur.fetchone()

    cur.execute("""
        SELECT
            COUNT(*),

            COUNT(*) FILTER (
                WHERE exact_win = TRUE
            ),

            COUNT(*) FILTER (
                WHERE outcome_win = TRUE
            )

        FROM score_game_picks

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    score_game = cur.fetchone()

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

        "total_parlays":
            int(
                parlay[0]
                or
                0
            ),

        "parlay_wins":
            int(
                parlay[1]
                or
                0
            ),

        "parlay_losses":
            int(
                parlay[2]
                or
                0
            ),

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
            ),

        "score_games":
            int(
                score_game[0]
                or
                0
            ),

        "score_exact_wins":
            int(
                score_game[1]
                or
                0
            ),

        "score_outcome_wins":
            int(
                score_game[2]
                or
                0
            )
    }


# =========================================================
# 🏅 ACHIEVEMENTS
# =========================================================

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

        FROM bets

        WHERE
            telegram_id = %s
            AND
            status = 'Выиграла'
            AND
            odd >= 3.0
    """, (
        telegram_id,
    ))

    high_odd_win = int(
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
        for row in cur.fetchall()
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
                user["xp"]
            ),

        "xp_500":
            int(
                user["xp"]
                or
                0
            ),

        "high_odd_win":
            high_odd_win
    }

    result = []

    for achievement in ACHIEVEMENTS:

        progress = values.get(
            achievement["key"],
            0
        )

        result.append({

            **achievement,

            "progress":
                min(
                    progress,
                    achievement["target"]
                ),

            "completed":
                progress
                >=
                achievement["target"],

            "claimed":
                achievement["key"]
                in
                claimed
        })

    return result


# =========================================================
# ⭐ FAVORITES
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
                    else
                    None
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
        match.get("date")
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
        f"{match['home']} — {match['away']}",
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
        for row in cur.fetchall()
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


# =========================================================
# 🔴 LIVE
# =========================================================

def refresh_live_matches_once():

    now = datetime.now(
        timezone.utc
    )

    candidates = []

    for match in get_all_cached_matches():

        kickoff = parse_match_datetime(
            match.get("date")
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

    candidates.sort(
        key=
            lambda item:
                item.get("date")
                or
                ""
    )

    candidates = candidates[
        :LIVE_MAX_MATCHES_PER_CYCLE
    ]

    for match in candidates:

        try:

            fresh = get_fixture(
                match["fixture_id"],
                False,
                True
            )

            live, finished = (
                live_status_flags(
                    fresh.get("status"),
                    fresh.get("status_code")
                )
            )

            live_match_cache[
                str(
                    int(
                        match["fixture_id"]
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
                error,
                flush=True
            )



# =========================================================
# 🔔 TELEGRAM УВЕДОМЛЕНИЯ МАТЧА ДНЯ
# =========================================================

_bot_webapp_url_cache = {
    "value": None,
    "checked_at": 0
}


def telegram_api_call(
    method,
    payload=None,
    timeout=12
):

    if not TELEGRAM_BOT_TOKEN:
        return {
            "ok": False
        }

    try:

        response = requests.post(
            (
                "https://api.telegram.org/bot"
                + TELEGRAM_BOT_TOKEN
                + "/"
                + method
            ),
            json=(
                payload
                or
                {}
            ),
            timeout=timeout
        )

        data = response.json()

        if not response.ok:

            print(
                "Telegram API error:",
                method,
                response.status_code,
                str(data)[:500],
                flush=True
            )

        return data

    except Exception as error:

        print(
            "Telegram API exception:",
            method,
            error,
            flush=True
        )

        return {
            "ok": False
        }


def get_bot_webapp_url():

    if BETCOIN_WEBAPP_URL:
        return BETCOIN_WEBAPP_URL

    now_ts = time.time()

    cached_value = (
        _bot_webapp_url_cache.get(
            "value"
        )
    )

    checked_at = float(
        _bot_webapp_url_cache.get(
            "checked_at",
            0
        )
        or
        0
    )

    if (
        cached_value
        and
        now_ts - checked_at < 3600
    ):
        return cached_value

    data = telegram_api_call(
        "getChatMenuButton"
    )

    url = ""

    if data.get("ok"):

        menu_button = (
            data.get("result")
            or
            {}
        )

        if (
            menu_button.get("type")
            ==
            "web_app"
        ):

            url = str(
                (
                    menu_button.get(
                        "web_app"
                    )
                    or
                    {}
                ).get(
                    "url"
                )
                or
                ""
            ).strip()

    _bot_webapp_url_cache[
        "value"
    ] = url

    _bot_webapp_url_cache[
        "checked_at"
    ] = now_ts

    return url


def webapp_url_with_params(
    page=None,
    score_view=None
):

    base = get_bot_webapp_url()

    if not base:
        return ""

    params = []

    if page:
        params.append(
            "page="
            +
            str(page)
        )

    if score_view:
        params.append(
            "score_view="
            +
            str(score_view)
        )

    if not params:
        return base

    separator = (
        "&"
        if "?" in base
        else
        "?"
    )

    return (
        base
        +
        separator
        +
        "&".join(
            params
        )
    )


def betcoin_start_keyboard():

    base_url = (
        webapp_url_with_params()
    )

    if not base_url:
        return None

    match_url = (
        webapp_url_with_params(
            page="games",
            score_view="play"
        )
    )

    rating_url = (
        webapp_url_with_params(
            page="games",
            score_view="leaderboard"
        )
    )

    profile_url = (
        webapp_url_with_params(
            page="profile"
        )
    )

    return {
        "inline_keyboard": [
            [
                {
                    "text":
                        "🎮 Открыть BetCoin",
                    "web_app": {
                        "url":
                            base_url
                    }
                }
            ],
            [
                {
                    "text":
                        "⭐ Матч дня",
                    "web_app": {
                        "url":
                            match_url
                    }
                },
                {
                    "text":
                        "🏆 Рейтинг",
                    "web_app": {
                        "url":
                            rating_url
                    }
                }
            ],
            [
                {
                    "text":
                        "👤 Профиль",
                    "web_app": {
                        "url":
                            profile_url
                    }
                }
            ]
        ]
    }


def send_betcoin_start(
    chat_id,
    first_name=None
):

    name = str(
        first_name
        or
        ""
    ).strip()

    greeting = (
        f", {name}"
        if name
        else
        ""
    )

    text = (
        f"⚽ Добро пожаловать в BetCoin{greeting}!\n\n"
        "Футбольный Mini App с прогнозами, играми и соревнованиями.\n\n"
        "⭐ Матч дня\n"
        "🎯 Точный счёт\n"
        "🏆 Рейтинг прогнозистов\n"
        "👥 Приватные лиги\n\n"
        "Открывай BetCoin и начинай 👇"
    )

    reply_markup = (
        betcoin_start_keyboard()
    )

    payload = {
        "chat_id": int(
            chat_id
        ),
        "text": text,
        "disable_web_page_preview": True
    }

    if reply_markup:

        payload[
            "reply_markup"
        ] = reply_markup

    if BETCOIN_START_IMAGE_URL:

        photo_payload = {
            "chat_id": int(
                chat_id
            ),
            "photo":
                BETCOIN_START_IMAGE_URL,
            "caption": text
        }

        if reply_markup:

            photo_payload[
                "reply_markup"
            ] = reply_markup

        result = telegram_api_call(
            "sendPhoto",
            photo_payload
        )

        if result.get("ok"):
            return True

    result = telegram_api_call(
        "sendMessage",
        payload
    )

    return bool(
        result.get(
            "ok"
        )
    )


def send_betcoin_command_open(
    chat_id,
    title,
    page=None,
    score_view=None
):

    url = webapp_url_with_params(
        page=page,
        score_view=score_view
    )

    payload = {
        "chat_id": int(
            chat_id
        ),
        "text": str(
            title
        )
    }

    if url:

        payload[
            "reply_markup"
        ] = {
            "inline_keyboard": [
                [
                    {
                        "text":
                            "Открыть BetCoin",
                        "web_app": {
                            "url":
                                url
                        }
                    }
                ]
            ]
        }

    result = telegram_api_call(
        "sendMessage",
        payload
    )

    return bool(
        result.get(
            "ok"
        )
    )


def handle_telegram_update(
    update
):

    message = (
        update.get(
            "message"
        )
        or
        {}
    )

    if not message:
        return

    chat = (
        message.get(
            "chat"
        )
        or
        {}
    )

    sender = (
        message.get(
            "from"
        )
        or
        {}
    )

    chat_id = chat.get(
        "id"
    )

    text = str(
        message.get(
            "text"
        )
        or
        ""
    ).strip()

    if not chat_id:
        return

    command = (
        text.split(
            " ",
            1
        )[0]
        .split(
            "@",
            1
        )[0]
        .lower()
    )

    if command == "/start":

        parts = text.split(
            None,
            1
        )

        start_param = (
            parts[1].strip()
            if len(parts) > 1
            else
            ""
        )

        if start_param.startswith(
            "ref_"
        ):

            try:

                inviter_id = int(
                    start_param[
                        4:
                    ]
                )

                save_pending_referral(
                    chat_id,
                    inviter_id
                )

            except (
                TypeError,
                ValueError
            ):

                pass

        send_betcoin_start(
            chat_id,
            sender.get(
                "first_name"
            )
        )

        return

    if command == "/play":

        send_betcoin_command_open(
            chat_id,
            "🎮 Открыть BetCoin",
        )

        return

    if command == "/match":

        send_betcoin_command_open(
            chat_id,
            "⭐ Матч дня",
            page="games",
            score_view="play"
        )

        return

    if command == "/leaders":

        send_betcoin_command_open(
            chat_id,
            "🏆 Рейтинг прогнозистов",
            page="games",
            score_view="leaderboard"
        )

        return

    if command == "/profile":

        send_betcoin_command_open(
            chat_id,
            "👤 Твой профиль BetCoin",
            page="profile"
        )

        return


def setup_telegram_webhook():

    if not TELEGRAM_BOT_TOKEN:
        return False

    webhook_url = (
        TELEGRAM_WEBHOOK_URL
        or
        (
            RENDER_EXTERNAL_URL.rstrip("/")
            +
            "/telegram/webhook"
            if RENDER_EXTERNAL_URL
            else
            (
                "https://"
                +
                RENDER_EXTERNAL_HOSTNAME.strip("/")
                +
                "/telegram/webhook"
                if RENDER_EXTERNAL_HOSTNAME
                else
                ""
            )
        )
    )

    if not webhook_url:
        return False

    result = telegram_api_call(
        "setWebhook",
        {
            "url":
                webhook_url,
            "allowed_updates": [
                "message"
            ],
            "drop_pending_updates":
                False
        }
    )

    if result.get("ok"):

        print(
            "Telegram webhook ready:",
            webhook_url,
            flush=True
        )

        return True

    return False



def send_telegram_message(
    telegram_id,
    text
):

    if not TELEGRAM_BOT_TOKEN:
        return False

    try:

        response = requests.post(
            (
                "https://api.telegram.org/bot"
                + TELEGRAM_BOT_TOKEN
                + "/sendMessage"
            ),
            json={
                "chat_id": int(
                    telegram_id
                ),
                "text": str(
                    text
                ),
                "disable_web_page_preview": True
            },
            timeout=12
        )

        if not response.ok:

            print(
                "Telegram send error:",
                telegram_id,
                response.status_code,
                response.text[:300],
                flush=True
            )

            return False

        data = response.json()

        return bool(
            data.get(
                "ok"
            )
        )

    except Exception as error:

        print(
            "Telegram send exception:",
            telegram_id,
            error,
            flush=True
        )

        return False


def score_game_reminder_worker_once():

    if not TELEGRAM_BOT_TOKEN:
        return 0

    today = score_game_date()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            fixture_id,
            home_team,
            away_team,
            league_name,
            kickoff_at

        FROM score_game_rounds

        WHERE game_date = %s
    """, (
        today,
    ))

    round_row = cur.fetchone()

    if not round_row:

        cur.close()
        conn.close()

        try:
            ensure_score_game_round()
        except Exception:
            pass

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                fixture_id,
                home_team,
                away_team,
                league_name,
                kickoff_at

            FROM score_game_rounds

            WHERE game_date = %s
        """, (
            today,
        ))

        round_row = cur.fetchone()

    if not round_row:

        cur.close()
        conn.close()
        return 0

    (
        fixture_id,
        home_team,
        away_team,
        league_name,
        kickoff_at
    ) = round_row

    now = datetime.now(
        timezone.utc
    )

    minutes_left = (
        kickoff_at
        -
        now
    ).total_seconds() / 60

    if (
        minutes_left
        <
        SCORE_GAME_REMINDER_FROM_MINUTES
        or
        minutes_left
        >
        SCORE_GAME_REMINDER_TO_MINUTES
    ):

        cur.close()
        conn.close()
        return 0

    cur.execute("""
        SELECT
            u.telegram_id,
            COALESCE(
                NULLIF(
                    u.first_name,
                    ''
                ),
                'Игрок'
            )

        FROM users u

        LEFT JOIN score_game_picks p
            ON p.telegram_id =
                u.telegram_id
            AND p.game_date = %s

        LEFT JOIN score_game_notifications n
            ON n.telegram_id =
                u.telegram_id
            AND n.game_date = %s

        WHERE
            p.telegram_id IS NULL
            AND
            COALESCE(
                n.reminder_sent,
                FALSE
            ) = FALSE

        ORDER BY
            u.updated_at DESC

        LIMIT 100
    """, (
        today,
        today
    ))

    users = cur.fetchall()

    cur.close()
    conn.close()

    sent_count = 0

    for (
        telegram_id,
        first_name
    ) in users:

        local_kickoff = (
            kickoff_at.astimezone(
                timezone(
                    timedelta(
                        hours=3
                    )
                )
            )
        )

        text = (
            "⚽ BetCoin — Матч дня\n\n"
            f"{home_team} — {away_team}\n"
            f"{league_name or 'Футбол'}\n"
            f"Начало в {local_kickoff.strftime('%H:%M')}\n\n"
            "До матча около часа, а ты ещё не сделал прогноз на точный счёт 👀\n"
            "Открой BetCoin и сделай прогноз."
        )

        if not send_telegram_message(
            telegram_id,
            text
        ):
            continue

        conn = get_db()
        cur = conn.cursor()

        try:

            cur.execute("""
                INSERT INTO score_game_notifications (
                    telegram_id,
                    game_date,
                    reminder_sent,
                    reminder_sent_at
                )
                VALUES (
                    %s,
                    %s,
                    TRUE,
                    NOW()
                )

                ON CONFLICT (
                    telegram_id,
                    game_date
                )
                DO UPDATE SET
                    reminder_sent = TRUE,
                    reminder_sent_at = NOW()
            """, (
                telegram_id,
                today
            ))

            conn.commit()

            sent_count += 1

        except Exception:

            conn.rollback()
            raise

        finally:

            cur.close()
            conn.close()

    return sent_count


def score_game_result_notifications_once():

    if not TELEGRAM_BOT_TOKEN:
        return 0

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            p.telegram_id,
            p.game_date,
            r.home_team,
            r.away_team,
            p.predicted_home,
            p.predicted_away,
            p.final_home,
            p.final_away,
            p.exact_win,
            p.outcome_win,
            p.reward_coins,
            p.reward_xp

        FROM score_game_picks p

        JOIN score_game_rounds r
            ON r.game_date =
                p.game_date

        LEFT JOIN score_game_notifications n
            ON n.telegram_id =
                p.telegram_id
            AND n.game_date =
                p.game_date

        WHERE
            p.settled = TRUE
            AND
            COALESCE(
                n.result_sent,
                FALSE
            ) = FALSE

        ORDER BY
            p.settled_at ASC

        LIMIT 100
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    sent_count = 0

    for row in rows:

        (
            telegram_id,
            game_date,
            home_team,
            away_team,
            predicted_home,
            predicted_away,
            final_home,
            final_away,
            exact_win,
            outcome_win,
            reward_coins,
            reward_xp
        ) = row

        if exact_win:

            title = (
                "🎯 ТОЧНЫЙ СЧЁТ!"
            )

            reward_text = (
                f"\n+{int(reward_coins or 0)} 🪙"
                f"  +{int(reward_xp or 0)} XP"
            )

        elif outcome_win:

            title = (
                "✅ Исход угадан"
            )

            reward_text = (
                f"\n+{int(reward_coins or 0)} 🪙"
            )

        else:

            title = (
                "❌ Прогноз не сыграл"
            )

            reward_text = ""

        text = (
            "⚽ BetCoin — Матч дня\n\n"
            f"{home_team} — {away_team}\n"
            f"Итог: {final_home}:{final_away}\n"
            f"Твой прогноз: {predicted_home}:{predicted_away}\n\n"
            f"{title}"
            f"{reward_text}\n\n"
            "Открой BetCoin — завтра будет новый Матч дня."
        )

        if not send_telegram_message(
            telegram_id,
            text
        ):
            continue

        conn = get_db()
        cur = conn.cursor()

        try:

            cur.execute("""
                INSERT INTO score_game_notifications (
                    telegram_id,
                    game_date,
                    result_sent,
                    result_sent_at
                )
                VALUES (
                    %s,
                    %s,
                    TRUE,
                    NOW()
                )

                ON CONFLICT (
                    telegram_id,
                    game_date
                )
                DO UPDATE SET
                    result_sent = TRUE,
                    result_sent_at = NOW()
            """, (
                telegram_id,
                game_date
            ))

            conn.commit()

            sent_count += 1

        except Exception:

            conn.rollback()
            raise

        finally:

            cur.close()
            conn.close()

    return sent_count



# =========================================================
# BACKGROUND WORKERS
# =========================================================

def settlement_worker():

    time.sleep(
        20
    )

    while True:

        try:

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
                for row in cur.fetchall()
            ]

            cur.close()
            conn.close()

            for telegram_id in users:

                try:

                    settle_user_bets(
                        telegram_id
                    )

                    settle_user_parlays(
                        telegram_id
                    )

                except Exception as error:

                    print(
                        "User settlement error:",
                        telegram_id,
                        error,
                        flush=True
                    )

            settle_prediction_picks(
                30
            )

            settle_score_game_picks(
                30
            )

            score_game_reminder_worker_once()

            score_game_result_notifications_once()

        except Exception as error:

            print(
                "Settlement worker:",
                error,
                flush=True
            )

        time.sleep(
            SETTLEMENT_CHECK_SECONDS
        )


def fixtures_worker():

    time.sleep(
        AUTO_FIXTURES_START_DELAY_SECONDS
    )

    while True:

        started_at = time.time()

        refreshed = 0
        failed = 0

        for league_key in LEAGUES.keys():

            try:

                fixtures = (
                    load_league_fixtures(
                        league_key,
                        force=True
                    )
                )

                refreshed += len(
                    fixtures
                    or
                    []
                )

            except Exception as error:

                failed += 1

                print(
                    "Fixtures auto refresh:",
                    league_key,
                    error,
                    flush=True
                )

            # Небольшая пауза между лигами,
            # чтобы не ударять по API пачкой запросов.
            time.sleep(
                2
            )

        print(
            "Fixtures auto refresh done:",
            "matches=",
            refreshed,
            "failed_leagues=",
            failed,
            "seconds=",
            round(
                time.time()
                -
                started_at,
                1
            ),
            flush=True
        )

        time.sleep(
            AUTO_FIXTURES_REFRESH_SECONDS
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
                error,
                flush=True
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
                live_worker,
            daemon=
                True,
            name=
                "betcoin-live"
        ).start()


        threading.Thread(
            target=
                fixtures_worker,
            daemon=
                True,
            name=
                "betcoin-fixtures"
        ).start()


def ensure_runtime_ready():

    global runtime_ready

    if runtime_ready:

        return

    with runtime_lock:

        if runtime_ready:

            return

        ensure_database_ready()

        start_workers()

        try:
            setup_telegram_webhook()
        except Exception as error:
            print(
                "Telegram webhook setup error:",
                error,
                flush=True
            )

        runtime_ready = True

        print(
            "BetCoin runtime started successfully",
            flush=True
        )


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

@app.route(
    "/telegram/webhook",
    methods=[
        "POST"
    ]
)
def telegram_webhook():

    try:

        update = (
            request.get_json(
                silent=True
            )
            or
            {}
        )

        handle_telegram_update(
            update
        )

        return jsonify({
            "ok": True
        })

    except Exception as error:

        print(
            "Telegram webhook error:",
            error,
            flush=True
        )

        return jsonify({
            "ok": True
        })




# =========================================================
# TELEGRAM WEBHOOK SETUP / STATUS
# =========================================================

@app.route(
    "/telegram/setup-webhook",
    methods=[
        "GET"
    ]
)
def telegram_setup_webhook():

    if not TELEGRAM_BOT_TOKEN:

        return jsonify({
            "ok": False,
            "error":
                "TELEGRAM_BOT_TOKEN is not set"
        }), 500

    base_url = (
        request.host_url.rstrip("/")
    )

    webhook_url = (
        base_url
        +
        "/telegram/webhook"
    )

    result = telegram_api_call(
        "setWebhook",
        {
            "url":
                webhook_url,
            "allowed_updates": [
                "message"
            ],
            "drop_pending_updates":
                False
        }
    )

    return jsonify({
        "ok":
            bool(
                result.get(
                    "ok"
                )
            ),
        "webhook_url":
            webhook_url,
        "telegram":
            result
    })


@app.route(
    "/telegram/status",
    methods=[
        "GET"
    ]
)
def telegram_webhook_status():

    if not TELEGRAM_BOT_TOKEN:

        return jsonify({
            "ok": False,
            "error":
                "TELEGRAM_BOT_TOKEN is not set"
        }), 500

    result = telegram_api_call(
        "getWebhookInfo"
    )

    return jsonify(
        result
    )


# =========================================================
# ROOT / HEALTH
# =========================================================

@app.route("/")
def root():

    return jsonify({

        "status":
            "ok",

        "message":
            "BetCoin server is working",

        "database_ready":
            database_ready,

        "database_initializing":
            database_initializing,

        "runtime_ready":
            runtime_ready,

        "prediction_game":
            True,

        "score_game":
            True,

        "wheel":
            True,

        "login_streak":
            True,

        "games_tab":
            True,

        "live":
            True
    })


@app.route(
    "/health"
)
def health():

    return jsonify({
        "status": "ok"
    })


# =========================================================
# LEAGUES / MATCHES API
# =========================================================

@app.route(
    "/api/leagues"
)
def api_leagues():

    return jsonify({

        "success":
            True,

        "leagues": [

            {
                "key":
                    key,

                "name":
                    value["name"],

                "short_name":
                    value["short_name"],

                "country":
                    value["country"],

                "flag":
                    value["flag"]
            }

            for key, value
            in LEAGUES.items()
        ]
    })


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
            request.args.get(
                "refresh"
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
                "success": False,
                "error": "Неизвестная лига"
            }), 400

        source_status = (
            get_top5_source_status()
            if (
                not league_key
                or
                league_key
                ==
                "top5"
            )
            else
            (
                league_source_status.get(
                    league_key
                )
                or
                {
                    "source":
                        "five-dollar",

                    "stale":
                        False,

                    "message":
                        None
                }
            )
        )

        return jsonify({

            "success":
                True,

            "count":
                len(
                    fixtures
                ),

            "source":
                source_status.get(
                    "source"
                ),

            "stale":
                bool(
                    source_status.get(
                        "stale"
                    )
                ),

            "refreshing":
                bool(
                    source_status.get(
                        "refreshing"
                    )
                ),

            "notice":
                source_status.get(
                    "message"
                ),

            "matches":
                fixtures
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@app.route(
    "/api/live"
)
def api_live():

    try:

        items = list(
            live_match_cache.values()
        )

        items.sort(
            key=
                lambda item:
                    item.get("date")
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
                items
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
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

        except Exception as error:

            print(
                "Match odds error:",
                error,
                flush=True
            )

        return jsonify({
            "success": True,
            **match
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500



@app.route(
    "/api/match/<int:fixture_id>/center"
)
def api_match_center(fixture_id):
    try:
        return jsonify({"success": True, **get_match_center_data(fixture_id)})
    except Exception as error:
        return jsonify({"success": False, "error": str(error)}), 500


# =========================================================
# SESSION API
# =========================================================

@app.route(
    "/api/session",
    methods=[
        "POST"
    ]
)
def api_session():

    fast_mode = (
        request.args.get(
            "fast"
        )
        ==
        "1"
    )

    tg_user, error = require_telegram_user()

    if error:

        return error

    try:

        user = get_or_create_user(
            tg_user
        )

        telegram_id = user[
            "telegram_id"
        ]

        referral_activation = (
            activate_pending_referral(
                telegram_id,
                bool(
                    user.get(
                        "is_new"
                    )
                )
            )
        )

        if referral_activation.get(
            "activated"
        ):

            refreshed_user = (
                get_user_data(
                    telegram_id
                )
            )

            if refreshed_user:
                user.update(
                    refreshed_user
                )

        if fast_mode:

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

                "fast":
                    True,

                "user": {

                    "telegram_id":
                        telegram_id,

                    "first_name":
                        user["first_name"],

                    "username":
                        user["username"]
                },

                "balance":
                    int(
                        user["balance"]
                    ),

                **xp_info(
                    user["xp"]
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
                        ),

                    "next_claim":
                        (
                            next_claim.isoformat()
                            if next_claim
                            else
                            None
                        )
                }
            })


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
                    user["first_name"],

                "username":
                    user["username"]
            },

            "balance":
                int(
                    user["balance"]
                ),

            **xp_info(
                user["xp"]
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
                "my_rank": None
            },

            "daily_reward": {

                "amount":
                    300,

                "available":
                    available,

                "seconds_left":
                    max(
                        0,
                        seconds_left
                    ),

                "next_claim":
                    (
                        next_claim.isoformat()
                        if next_claim
                        else
                        None
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
                (
                    {
                        "loading": True,
                        "available": False
                    }
                    if fast_mode
                    else
                    get_prediction_game(
                        telegram_id
                    )
                ),

            "referral":
                get_referral_info(
                    telegram_id
                ),

            "notification_settings":
                get_notification_settings(
                    telegram_id
                ),

            "profile_extra":
                get_profile_extra(
                    telegram_id
                ),

            "score_game":
                (
                    {
                        "loading": True,
                        "available": False
                    }
                    if fast_mode
                    else
                    get_score_game(
                        telegram_id
                    )
                )
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# 🔥 LOGIN STREAK API
# =========================================================

@app.route(
    "/api/login-streak/claim",
    methods=[
        "POST"
    ]
)
def api_login_streak_claim():

    tg_user, error = require_telegram_user()

    if error:

        return error

    try:

        user = get_or_create_user(
            tg_user
        )

        result = claim_login_streak(
            user["telegram_id"]
        )

        return jsonify({
            "success": True,
            **result
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# 🎯 PREDICTION GAME API
# =========================================================

@app.route(
    "/api/games/prediction",
    methods=[
        "POST"
    ]
)
def api_prediction_game():

    tg_user, error = require_telegram_user()

    if error:

        return error

    try:

        user = get_or_create_user(
            tg_user
        )

        return jsonify({

            "success":
                True,

            "game":
                get_prediction_game(
                    user["telegram_id"]
                )
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@app.route(
    "/api/games/prediction/pick",
    methods=[
        "POST"
    ]
)
def api_prediction_pick():

    tg_user, error = require_telegram_user()

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

        game = make_prediction_pick(
            user["telegram_id"],
            body.get(
                "prediction"
            )
        )

        return jsonify({
            "success": True,
            "game": game
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# ⚽ SCORE GAME API
# =========================================================

@app.route(
    "/api/games/score",
    methods=[
        "POST"
    ]
)
def api_score_game():

    tg_user, error = require_telegram_user()

    if error:

        return error

    try:

        user = get_or_create_user(
            tg_user
        )

        return jsonify({

            "success":
                True,

            "game":
                get_score_game(
                    user["telegram_id"]
                )
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@app.route(
    "/api/games/score/pick",
    methods=[
        "POST"
    ]
)
def api_score_game_pick():

    tg_user, error = require_telegram_user()

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

        game = make_score_game_pick(
            user["telegram_id"],
            body.get(
                "home_score"
            ),
            body.get(
                "away_score"
            )
        )

        return jsonify({
            "success": True,
            "game": game
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500



@app.route(
    "/api/games/score/history",
    methods=[
        "POST"
    ]
)
def api_score_game_history():

    tg_user, error = require_telegram_user()

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

        history = get_score_game_history(
            user["telegram_id"],
            body.get(
                "limit",
                50
            )
        )

        return jsonify({

            "success":
                True,

            "history":
                history,

            "stats":
                get_score_game_stats(
                    user["telegram_id"]
                )
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@app.route(
    "/api/games/score/leaderboard",
    methods=[
        "POST"
    ]
)
def api_score_game_leaderboard():

    tg_user, error = require_telegram_user()

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

        leaderboard = get_score_game_leaderboard(
            user["telegram_id"],
            body.get(
                "limit",
                50
            )
        )

        return jsonify({
            "success": True,
            **leaderboard
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# 👥 ПРИВАТНЫЕ ЛИГИ ПРОГНОЗИСТОВ API
# =========================================================

@app.route(
    "/api/games/score/leagues",
    methods=[
        "POST"
    ]
)
def api_predictor_leagues():

    tg_user, error = require_telegram_user()

    if error:
        return error

    try:

        user = get_or_create_user(
            tg_user
        )

        return jsonify({
            "success": True,
            "leagues": get_predictor_leagues(
                user["telegram_id"]
            )
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@app.route(
    "/api/games/score/leagues/create",
    methods=[
        "POST"
    ]
)
def api_predictor_league_create():

    tg_user, error = require_telegram_user()

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

        result = create_predictor_league(
            user["telegram_id"],
            body.get(
                "name"
            )
        )

        return jsonify({
            "success": True,
            **result,
            "leagues": get_predictor_leagues(
                user["telegram_id"]
            )
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@app.route(
    "/api/games/score/leagues/join",
    methods=[
        "POST"
    ]
)
def api_predictor_league_join():

    tg_user, error = require_telegram_user()

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

        result = join_predictor_league(
            user["telegram_id"],
            body.get(
                "code"
            )
        )

        return jsonify({
            "success": True,
            **result,
            "leagues": get_predictor_leagues(
                user["telegram_id"]
            )
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@app.route(
    "/api/games/score/leagues/leave",
    methods=[
        "POST"
    ]
)
def api_predictor_league_leave():

    tg_user, error = require_telegram_user()

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

        leave_predictor_league(
            user["telegram_id"],
            body.get(
                "league_id"
            )
        )

        return jsonify({
            "success": True,
            "leagues": get_predictor_leagues(
                user["telegram_id"]
            )
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@app.route(
    "/api/games/score/leagues/delete",
    methods=[
        "POST"
    ]
)
def api_predictor_league_delete():

    tg_user, error = require_telegram_user()

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

        delete_predictor_league(
            user["telegram_id"],
            body.get(
                "league_id"
            )
        )

        return jsonify({
            "success": True,
            "leagues": get_predictor_leagues(
                user["telegram_id"]
            )
        })

    except (ValueError, TypeError) as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500



@app.route(
    "/api/games/score/leagues/leaderboard",
    methods=[
        "POST"
    ]
)
def api_predictor_league_leaderboard():

    tg_user, error = require_telegram_user()

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

        result = get_predictor_league_leaderboard(
            user["telegram_id"],
            body.get(
                "league_id"
            )
        )

        return jsonify({
            "success": True,
            **result
        })

    except (ValueError, TypeError) as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500



# =========================================================
# 🎡 WHEEL API
# =========================================================

@app.route(
    "/api/wheel/status",
    methods=[
        "POST"
    ]
)
def api_wheel_status():

    tg_user, error = require_telegram_user()

    if error:

        return error

    try:

        user = get_or_create_user(
            tg_user
        )

        return jsonify({

            "success":
                True,

            "wheel":
                get_wheel_status(
                    user["telegram_id"]
                )
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


@app.route(
    "/api/wheel/spin",
    methods=[
        "POST"
    ]
)
def api_wheel_spin():

    tg_user, error = require_telegram_user()

    if error:

        return error

    try:

        user = get_or_create_user(
            tg_user
        )

        return jsonify({
            "success": True,
            **spin_wheel(
                user["telegram_id"]
            )
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# PROMO API
# =========================================================

@app.route(
    "/api/promo/redeem",
    methods=[
        "POST"
    ]
)
def api_promo_redeem():

    tg_user, error = require_telegram_user()

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

        result = redeem_promo_code(
            user["telegram_id"],
            body.get(
                "code",
                ""
            )
        )

        return jsonify({
            "success": True,
            **result
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# SINGLE BET API
# =========================================================

@app.route(
    "/api/bets",
    methods=[
        "POST"
    ]
)
def api_bets():

    tg_user, error = require_telegram_user()

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

        if amount < 100:

            raise ValueError(
                "Минимальная ставка — 100 монет"
            )

        canonical = resolve_canonical_bet(
            fixture_id,
            selection
        )

        user = get_or_create_user(
            tg_user
        )

        telegram_id = user[
            "telegram_id"
        ]

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
                "success": False,
                "error": "Недостаточно монет"
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
                    balance
                    -
                    %s,

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
            canonical["match"],
            canonical["selection"],
            odd,
            amount,
            possible,
            canonical["kickoff_at"]
        ))

        bet_id = cur.fetchone()[0]

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
                    fresh["balance"]
                ),

            "possible":
                possible,

            "bets":
                get_user_bets(
                    telegram_id
                )
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# PARLAY API
# =========================================================

@app.route(
    "/api/parlays",
    methods=[
        "POST"
    ]
)
def api_parlays():

    tg_user, error = require_telegram_user()

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
            body.get(
                "amount"
            )
        )

        legs = body.get(
            "legs",
            []
        )

        if amount < 100:

            raise ValueError(
                "Минимальная ставка — 100 монет"
            )

        if (
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

        fixture_ids = [

            int(
                leg["fixture_id"]
            )

            for leg in legs
        ]

        if (
            len(
                fixture_ids
            )
            !=
            len(
                set(
                    fixture_ids
                )
            )
        ):

            raise ValueError(
                "Нельзя добавить два исхода одного матча"
            )

        validated = []

        for leg in legs:

            validated.append(
                resolve_canonical_bet(
                    int(
                        leg["fixture_id"]
                    ),
                    str(
                        leg["selection"]
                    )
                )
            )

        total_odd = 1.0

        for leg in validated:

            total_odd *= float(
                leg["odd"]
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

        telegram_id = user[
            "telegram_id"
        ]

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
                "success": False,
                "error": "Недостаточно монет"
            }), 400

        cur.execute("""
            UPDATE users

            SET
                balance =
                    balance
                    -
                    %s,

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
                leg["fixture_id"],
                leg["match"],
                leg["selection"],
                leg["odd"],
                leg["kickoff_at"]
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

            "parlay_id":
                parlay_id,

            "balance":
                int(
                    fresh["balance"]
                ),

            "total_odd":
                total_odd,

            "possible":
                possible,

            "parlays":
                get_user_parlays(
                    telegram_id
                )
        })

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# FAVORITES API
# =========================================================

@app.route(
    "/api/favorites/toggle",
    methods=[
        "POST"
    ]
)
def api_favorites_toggle():

    tg_user, error = require_telegram_user()

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

    telegram_id = user[
        "telegram_id"
    ]

    fixture_id = int(
        body["fixture_id"]
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
            )
    })


@app.route(
    "/api/favorite-teams/toggle",
    methods=[
        "POST"
    ]
)
def api_favorite_teams_toggle():

    tg_user, error = require_telegram_user()

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

    telegram_id = user[
        "telegram_id"
    ]

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
            )
    })



# =========================================================
# 🔔 NOTIFICATION SETTINGS API
# =========================================================

@app.route(
    "/api/notification-settings",
    methods=[
        "POST"
    ]
)
def api_notification_settings():

    tg_user, error = require_telegram_user()

    if error:
        return error

    user = get_or_create_user(
        tg_user
    )

    body = (
        request.get_json(
            silent=True
        )
        or
        {}
    )

    settings = (
        update_notification_settings(
            user[
                "telegram_id"
            ],
            body
        )
    )

    return jsonify({
        "success":
            True,

        "settings":
            settings
    })


# =========================================================
# 🏆 LEADERBOARD
# =========================================================

@app.route(
    "/api/leaderboard",
    methods=[
        "POST"
    ]
)
def api_leaderboard():

    tg_user, error = require_telegram_user()

    if error:
        return error

    user = get_or_create_user(
        tg_user
    )

    body = (
        request.get_json(
            silent=True
        )
        or
        {}
    )

    mode = str(
        body.get(
            "mode",
            "xp"
        )
        or
        "xp"
    ).strip().lower()

    if mode not in {
        "xp",
        "coins",
        "exact",
        "weekly"
    }:
        mode = "xp"

    telegram_id = int(
        user[
            "telegram_id"
        ]
    )

    conn = get_db()
    cur = conn.cursor()

    if mode == "weekly":

        cur.execute(
            """
            WITH weekly AS (

                SELECT
                    u.telegram_id,
                    u.first_name,
                    u.balance,
                    u.xp,

                    (
                        COUNT(
                            CASE
                                WHEN
                                    p.settled = TRUE
                                    AND
                                    p.created_at >=
                                        NOW()
                                        -
                                        INTERVAL '7 days'
                                THEN 1
                            END
                        )
                    )::INTEGER
                    AS weekly_predictions,

                    (
                        COUNT(
                            CASE
                                WHEN
                                    p.settled = TRUE
                                    AND
                                    p.created_at >=
                                        NOW()
                                        -
                                        INTERVAL '7 days'
                                    AND
                                    (
                                        p.exact_win = TRUE
                                        OR
                                        p.outcome_win = TRUE
                                    )
                                THEN 1
                            END
                        )
                    )::INTEGER
                    AS weekly_success

                FROM users u

                LEFT JOIN score_game_picks p
                    ON p.telegram_id =
                        u.telegram_id

                GROUP BY
                    u.telegram_id,
                    u.first_name,
                    u.balance,
                    u.xp
            ),

            positions AS (

                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        ORDER BY
                            weekly_success DESC,
                            weekly_predictions DESC,
                            xp DESC,
                            telegram_id ASC
                    ) AS rank

                FROM weekly
            )

            SELECT
                telegram_id,
                first_name,
                balance,
                xp,
                0 AS exact_wins,
                weekly_success AS successful_predictions,
                weekly_predictions AS settled_predictions,
                rank

            FROM positions

            WHERE
                rank <= 50
                OR
                telegram_id = %s

            ORDER BY rank ASC
            """,
            (
                telegram_id,
            )
        )

    elif mode == "exact":

        cur.execute("""
            WITH ranked AS (

                SELECT
                    u.telegram_id,
                    u.first_name,
                    u.balance,
                    u.xp,

                    COUNT(
                        CASE
                            WHEN
                                p.settled = TRUE
                                AND
                                p.exact_win = TRUE
                            THEN 1
                        END
                    )::INTEGER
                    AS exact_wins,

                    COUNT(
                        CASE
                            WHEN
                                p.settled = TRUE
                                AND
                                (
                                    p.exact_win = TRUE
                                    OR
                                    p.outcome_win = TRUE
                                )
                            THEN 1
                        END
                    )::INTEGER
                    AS successful_predictions,

                    COUNT(
                        CASE
                            WHEN
                                p.settled = TRUE
                            THEN 1
                        END
                    )::INTEGER
                    AS settled_predictions

                FROM users u

                LEFT JOIN score_game_picks p
                    ON p.telegram_id =
                        u.telegram_id

                GROUP BY
                    u.telegram_id,
                    u.first_name,
                    u.balance,
                    u.xp
            ),

            positions AS (

                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        ORDER BY
                            exact_wins DESC,
                            successful_predictions DESC,
                            settled_predictions DESC,
                            xp DESC,
                            telegram_id ASC
                    ) AS rank

                FROM ranked
            )

            SELECT
                telegram_id,
                first_name,
                balance,
                xp,
                exact_wins,
                successful_predictions,
                settled_predictions,
                rank

            FROM positions

            WHERE
                rank <= 50
                OR
                telegram_id = %s

            ORDER BY rank ASC
        """, (
            telegram_id,
        ))

    else:

        order_sql = (
            "balance DESC, xp DESC, telegram_id ASC"
            if mode == "coins"
            else
            "xp DESC, balance DESC, telegram_id ASC"
        )

        cur.execute(
            f"""
            WITH positions AS (

                SELECT
                    telegram_id,
                    first_name,
                    balance,
                    xp,

                    ROW_NUMBER() OVER (
                        ORDER BY
                            {order_sql}
                    ) AS rank

                FROM users
            )

            SELECT
                telegram_id,
                first_name,
                balance,
                xp,
                0 AS exact_wins,
                0 AS successful_predictions,
                0 AS settled_predictions,
                rank

            FROM positions

            WHERE
                rank <= 50
                OR
                telegram_id = %s

            ORDER BY rank ASC
            """,
            (
                telegram_id,
            )
        )

    rows = cur.fetchall()

    players = []
    my_player = None

    for row in rows:

        player_level = calculate_level(
            row[3]
        )

        settled_predictions = int(
            row[6]
            or
            0
        )

        successful_predictions = int(
            row[5]
            or
            0
        )

        success_rate = (
            round(
                successful_predictions
                /
                settled_predictions
                *
                100
            )
            if settled_predictions > 0
            else
            0
        )

        player = {

            "rank":
                int(
                    row[7]
                ),

            "telegram_id":
                int(
                    row[0]
                ),

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
                int(
                    player_level
                ),

            "league":
                get_league(
                    player_level
                ),

            "exact_wins":
                int(
                    row[4]
                    or
                    0
                ),

            "successful_predictions":
                successful_predictions,

            "settled_predictions":
                settled_predictions,

            "success_rate":
                int(
                    success_rate
                ),

            "is_me":
                int(
                    row[0]
                )
                ==
                telegram_id
        }

        if player["is_me"]:
            my_player = player

        if player["rank"] <= 50:
            players.append(
                player
            )

    cur.close()
    conn.close()

    return jsonify({

        "success":
            True,

        "mode":
            mode,

        "players":
            players,

        "my_rank":
            (
                my_player[
                    "rank"
                ]
                if my_player
                else
                None
            ),

        "me":
            my_player
    })


# =========================================================
# 🎁 DAILY REWARD
# =========================================================

@app.route(
    "/api/daily-reward",
    methods=[
        "POST"
    ]
)
def api_daily_reward():

    tg_user, error = require_telegram_user()

    if error:

        return error

    user = get_or_create_user(
        tg_user
    )

    telegram_id = user[
        "telegram_id"
    ]

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

    last_claim = cur.fetchone()[0]

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
            "success": False,
            "error": "Бонус уже получен"
        }), 400

    cur.execute("""
        UPDATE users

        SET
            balance =
                balance
                +
                300,

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
                fresh["balance"]
            ),

        **xp_info(
            fresh["xp"]
        )
    })


# =========================================================
# ✅ TASK CLAIM
# =========================================================

@app.route(
    "/api/tasks/claim",
    methods=[
        "POST"
    ]
)
def api_task_claim():

    tg_user, error = require_telegram_user()

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

    telegram_id = user[
        "telegram_id"
    ]

    tasks = get_daily_tasks(
        telegram_id,
        True
    )

    target = next(
        (
            item

            for item in tasks

            if
            item["key"]
            ==
            key
        ),
        None
    )

    if (
        not target
        or
        not target["completed"]
        or
        target["claimed"]
    ):

        return jsonify({
            "success": False,
            "error": "Награда недоступна"
        }), 400

    column_map = {

        "login":
            "login_claimed",

        "bets_3":
            "bets_claimed",

        "win_1":
            "win_claimed"
    }

    if key not in column_map:

        return jsonify({
            "success": False,
            "error": "Неизвестное задание"
        }), 400

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
            AND
            {column} = FALSE
        """,
        (
            telegram_id,
            task_date()
        )
    )

    if cur.rowcount != 1:

        conn.rollback()

        cur.close()
        conn.close()

        return jsonify({
            "success": False,
            "error": "Награда уже получена"
        }), 400

    if (
        target["reward_type"]
        ==
        "coins"
    ):

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
            target["reward"],
            telegram_id
        ))

    else:

        add_xp(
            telegram_id,
            target["reward"],
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
                fresh["balance"]
            ),

        **xp_info(
            fresh["xp"]
        ),

        "tasks":
            get_daily_tasks(
                telegram_id
            )
    })


# =========================================================
# 🏅 ACHIEVEMENT CLAIM
# =========================================================

@app.route(
    "/api/achievements/claim",
    methods=[
        "POST"
    ]
)
def api_achievement_claim():

    tg_user, error = require_telegram_user()

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

    telegram_id = user[
        "telegram_id"
    ]

    achievements = get_achievements(
        telegram_id
    )

    achievement = next(
        (
            item

            for item in achievements

            if
            item["key"]
            ==
            key
        ),
        None
    )

    if (
        not achievement
        or
        not achievement["completed"]
        or
        achievement["claimed"]
    ):

        return jsonify({
            "success": False,
            "error": "Награда недоступна"
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

        RETURNING achievement_key
    """, (
        telegram_id,
        key
    ))

    if not cur.fetchone():

        conn.rollback()

        cur.close()
        conn.close()

        return jsonify({
            "success": False,
            "error": "Награда уже получена"
        }), 400

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
        achievement["reward"],
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
                fresh["balance"]
            ),

        "achievements":
            get_achievements(
                telegram_id
            )
    })


# =========================================================
# 🔄 MANUAL SETTLE
# =========================================================

@app.route(
    "/api/settle",
    methods=[
        "POST"
    ]
)
def api_settle():

    tg_user, error = require_telegram_user()

    if error:

        return error

    try:

        user = get_or_create_user(
            tg_user
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

        settle_prediction_picks(
            10
        )

        settle_score_game_picks(
            10
        )

        fresh = get_user_data(
            telegram_id
        )

        return jsonify({

            "success":
                True,

            "balance":
                int(
                    fresh["balance"]
                ),

            **xp_info(
                fresh["xp"]
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

            "score_game":
                get_score_game(
                    telegram_id
                ),

            "login_streak":
                get_login_streak_status(
                    telegram_id
                )
        })

    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# LOCAL START
# =========================================================

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
