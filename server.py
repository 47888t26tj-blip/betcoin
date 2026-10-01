import os
import re
import time
import json
import hmac
import hashlib
from urllib.parse import parse_qsl
from datetime import datetime, timedelta, timezone

import requests
import psycopg2
from flask import Flask, jsonify, request
from flask_cors import CORS


app = Flask(__name__)
CORS(app)


API_FOOTBALL_KEY = os.environ.get(
    "API_FOOTBALL_KEY",
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


API_FOOTBALL_URL = (
    "https://v3.football.api-sports.io"
)

FOOTBALL_DATA_URL = (
    "https://api.football-data.org/v4"
)


PREMIER_LEAGUE_ID = 39


FIXTURES_CACHE_SECONDS = 21600
ODDS_LIST_CACHE_SECONDS = 21600
ODDS_DETAIL_CACHE_SECONDS = 10800
RESULT_CACHE_SECONDS = 300


TOTAL_POINTS = [
    1.5,
    2.5,
    3.5,
    4.5
]


HANDICAP_POINTS = [
    -2.5,
    -2.0,
    -1.5,
    -1.0,
    0.0,
    1.0,
    1.5,
    2.0,
    2.5
]


TEAM_TOTAL_POINTS = [
    0.5,
    1.5,
    2.5,
    3.5
]


database_ready = False


fixtures_cache = {
    "time": 0,
    "data": None
}


odds_list_cache = {
    "time": 0,
    "data": {}
}


odds_detail_cache = {}

result_cache = {}


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
                DEFAULT NOW()
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

            score TEXT
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
        idx_parlay_legs_parlay

        ON parlay_legs(parlay_id)
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_parlay_legs_fixture

        ON parlay_legs(fixture_id)
    """)


    conn.commit()

    cur.close()
    conn.close()


    database_ready = True


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


        data_check_string = "\n".join(
            f"{key}={value}"
            for key, value
            in sorted(
                data.items()
            )
        )


        secret_key = hmac.new(
            b"WebAppData",
            TELEGRAM_BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()


        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()


        if not hmac.compare_digest(
            calculated_hash,
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


        user_json = data.get(
            "user"
        )


        if not user_json:
            return None


        user = json.loads(
            user_json
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


# =========================================================
# LEVELS / XP
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


    current_level_xp = (
        xp % 100
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
            current_level_xp,

        "xp_to_next_level":
            100
            -
            current_level_xp
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


    level_reward = 0
    levels_gained = []


    for level_number in range(
        old_level + 1,
        new_level + 1
    ):

        reward = 100


        if (
            level_number % 5
            ==
            0
        ):

            reward += 500


        level_reward += reward


        levels_gained.append({
            "level":
                level_number,

            "reward":
                reward
        })


    if level_reward > 0:

        cursor.execute("""
            UPDATE users

            SET
                balance =
                    balance + %s,

                updated_at =
                    NOW()

            WHERE telegram_id = %s
        """, (
            level_reward,
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
    ] = level_reward


    result[
        "levels_gained"
    ] = levels_gained


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
                login_done =
                    TRUE

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
            "key":
                "login",

            "title":
                "Зайти в приложение",

            "description":
                "Открой BetCoin сегодня",

            "progress":
                1
                if login_done
                else 0,

            "target":
                1,

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
            "key":
                "bets_3",

            "title":
                "Сделать 3 ставки",

            "description":
                "Сделай 3 ставки за сегодня",

            "progress":
                min(
                    bets_count,
                    3
                ),

            "target":
                3,

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
            "key":
                "win_1",

            "title":
                "Выиграть 1 ставку",

            "description":
                "Получи хотя бы один выигрыш сегодня",

            "progress":
                min(
                    wins_count,
                    1
                ),

            "target":
                1,

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
# API FOOTBALL
# =========================================================


def api_headers():

    return {
        "x-apisports-key":
            API_FOOTBALL_KEY,

        "Accept":
            "application/json"
    }


def api_get(
    path,
    params=None
):

    if not API_FOOTBALL_KEY:

        raise RuntimeError(
            "API_FOOTBALL_KEY not found"
        )


    response = requests.get(
        (
            f"{API_FOOTBALL_URL}/"
            f"{path.lstrip('/')}"
        ),

        headers=
            api_headers(),

        params=
            params or {},

        timeout=25
    )


    if (
        response.status_code
        !=
        200
    ):

        raise RuntimeError(
            (
                "API-Football HTTP "
                f"{response.status_code}"
            )
        )


    data = response.json()


    errors = data.get(
        "errors"
    )


    if errors:

        raise RuntimeError(
            f"API-Football: {errors}"
        )


    return data


def current_season():

    now = datetime.now(
        timezone.utc
    )


    if now.month >= 7:

        return now.year


    return now.year - 1


def load_fixtures(
    force=False
):

    if (
        not force

        and

        fixtures_cache[
            "data"
        ]
        is not None

        and

        time.time()
        -
        fixtures_cache[
            "time"
        ]
        <
        FIXTURES_CACHE_SECONDS
    ):

        return fixtures_cache[
            "data"
        ]


    today = datetime.now(
        timezone.utc
    ).date()


    date_to = (
        today
        +
        timedelta(
            days=14
        )
    )


    data = api_get(
        "fixtures",
        {
            "league":
                PREMIER_LEAGUE_ID,

            "season":
                current_season(),

            "from":
                today.isoformat(),

            "to":
                date_to.isoformat()
        }
    )


    result = []


    for item in data.get(
        "response",
        []
    ):

        fixture = item.get(
            "fixture",
            {}
        )


        league = item.get(
            "league",
            {}
        )


        teams = item.get(
            "teams",
            {}
        )


        home = teams.get(
            "home",
            {}
        )


        away = teams.get(
            "away",
            {}
        )


        result.append({
            "fixture_id":
                fixture.get(
                    "id"
                ),

            "date":
                fixture.get(
                    "date"
                ),

            "status":
                (
                    fixture.get(
                        "status"
                    )
                    or
                    {}
                ).get(
                    "short",
                    "NS"
                ),

            "league":
                league.get(
                    "name",
                    "Premier League"
                ),

            "country":
                league.get(
                    "country",
                    "England"
                ),

            "home":
                home.get(
                    "name",
                    "Unknown"
                ),

            "away":
                away.get(
                    "name",
                    "Unknown"
                ),

            "home_logo":
                home.get(
                    "logo",
                    ""
                ),

            "away_logo":
                away.get(
                    "logo",
                    ""
                ),

            "odds":
                None,

            "total_1_5":
                None,

            "total_2_5":
                None,

            "total_3_5":
                None,

            "total_4_5":
                None,

            "btts":
                None,

            "double_chance":
                None,

            "handicaps":
                None,

            "team_totals":
                None
        })


    fixtures_cache[
        "time"
    ] = time.time()


    fixtures_cache[
        "data"
    ] = result


    return result


def parse_float(
    value
):

    try:

        return float(
            str(
                value
            ).replace(
                ",",
                "."
            )
        )


    except Exception:

        return None


def norm(
    value
):

    return re.sub(
        r"\s+",
        " ",
        str(
            value
            or
            ""
        ).strip().lower()
    )


def first_empty_set(
    target,
    key,
    value
):

    if (
        value is not None
        and
        target.get(
            key
        )
        is None
    ):

        target[
            key
        ] = value


def parse_api_football_odds(
    item
):

    result = {
        "odds": {
            "home": None,
            "draw": None,
            "away": None
        },

        "double_chance": {
            "1x": None,
            "12": None,
            "x2": None
        },

        "totals": {
            str(
                point
            ): {
                "over": None,
                "under": None
            }
            for point
            in TOTAL_POINTS
        },

        "btts": {
            "yes": None,
            "no": None
        },

        "handicaps": {
            "home": {
                str(
                    point
                ).rstrip(
                    "0"
                ).rstrip(
                    "."
                ): None
                for point
                in HANDICAP_POINTS
            },

            "away": {
                str(
                    point
                ).rstrip(
                    "0"
                ).rstrip(
                    "."
                ): None
                for point
                in HANDICAP_POINTS
            }
        },

        "team_totals": {
            "home": {
                str(
                    point
                ): {
                    "over": None,
                    "under": None
                }
                for point
                in TEAM_TOTAL_POINTS
            },

            "away": {
                str(
                    point
                ): {
                    "over": None,
                    "under": None
                }
                for point
                in TEAM_TOTAL_POINTS
            }
        },

        "bookmaker":
            None,

        "available_markets":
            []
    }


    bookmakers = item.get(
        "bookmakers",
        []
    )


    if bookmakers:

        result[
            "bookmaker"
        ] = bookmakers[0].get(
            "name"
        )


    for bookmaker in bookmakers:

        for bet in bookmaker.get(
            "bets",
            []
        ):

            bet_name = norm(
                bet.get(
                    "name"
                )
            )


            if (
                bet_name
                and
                bet_name
                not in result[
                    "available_markets"
                ]
            ):

                result[
                    "available_markets"
                ].append(
                    bet_name
                )


            values = bet.get(
                "values",
                []
            )


            if (
                "match winner"
                in bet_name

                or

                bet_name in (
                    "winner",
                    "1x2"
                )
            ):

                for value in values:

                    name = norm(
                        value.get(
                            "value"
                        )
                    )


                    odd = parse_float(
                        value.get(
                            "odd"
                        )
                    )


                    if name in (
                        "home",
                        "1"
                    ):

                        first_empty_set(
                            result[
                                "odds"
                            ],
                            "home",
                            odd
                        )


                    elif name in (
                        "draw",
                        "x"
                    ):

                        first_empty_set(
                            result[
                                "odds"
                            ],
                            "draw",
                            odd
                        )


                    elif name in (
                        "away",
                        "2"
                    ):

                        first_empty_set(
                            result[
                                "odds"
                            ],
                            "away",
                            odd
                        )


            elif (
                "double chance"
                in bet_name
            ):

                for value in values:

                    name = norm(
                        value.get(
                            "value"
                        )
                    ).replace(
                        " ",
                        ""
                    )


                    odd = parse_float(
                        value.get(
                            "odd"
                        )
                    )


                    if name in (
                        "home/draw",
                        "1x",
                        "homedraw"
                    ):

                        first_empty_set(
                            result[
                                "double_chance"
                            ],
                            "1x",
                            odd
                        )


                    elif name in (
                        "home/away",
                        "12",
                        "homeaway"
                    ):

                        first_empty_set(
                            result[
                                "double_chance"
                            ],
                            "12",
                            odd
                        )


                    elif name in (
                        "draw/away",
                        "x2",
                        "drawaway"
                    ):

                        first_empty_set(
                            result[
                                "double_chance"
                            ],
                            "x2",
                            odd
                        )


            elif (
                "both teams"
                in bet_name

                and

                (
                    "score"
                    in bet_name

                    or

                    "scor"
                    in bet_name
                )
            ):

                for value in values:

                    name = norm(
                        value.get(
                            "value"
                        )
                    )


                    odd = parse_float(
                        value.get(
                            "odd"
                        )
                    )


                    if name == "yes":

                        first_empty_set(
                            result[
                                "btts"
                            ],
                            "yes",
                            odd
                        )


                    elif name == "no":

                        first_empty_set(
                            result[
                                "btts"
                            ],
                            "no",
                            odd
                        )


            elif (
                (
                    "over/under"
                    in bet_name

                    or

                    "goals over"
                    in bet_name
                )

                and

                "home"
                not in bet_name

                and

                "away"
                not in bet_name

                and

                "team"
                not in bet_name
            ):

                for value in values:

                    text = norm(
                        value.get(
                            "value"
                        )
                    )


                    match = re.search(
                        (
                            r"(over|under)"
                            r"\s*"
                            r"([0-9]+(?:\.[0-9]+)?)"
                        ),
                        text
                    )


                    if not match:
                        continue


                    side = match.group(
                        1
                    )


                    line = parse_float(
                        match.group(
                            2
                        )
                    )


                    if line in TOTAL_POINTS:

                        key = str(
                            line
                        )


                        first_empty_set(
                            result[
                                "totals"
                            ][key],
                            side,
                            parse_float(
                                value.get(
                                    "odd"
                                )
                            )
                        )


            elif (
                "asian handicap"
                in bet_name

                or

                bet_name
                ==
                "handicap result"
            ):

                for value in values:

                    text = norm(
                        value.get(
                            "value"
                        )
                    )


                    match = re.search(
                        (
                            r"(home|away)"
                            r"\s*"
                            r"([+-]?[0-9]+(?:\.[0-9]+)?)"
                        ),
                        text
                    )


                    if not match:
                        continue


                    side = match.group(
                        1
                    )


                    line = parse_float(
                        match.group(
                            2
                        )
                    )


                    if line in HANDICAP_POINTS:

                        key = str(
                            line
                        ).rstrip(
                            "0"
                        ).rstrip(
                            "."
                        )


                        first_empty_set(
                            result[
                                "handicaps"
                            ][side],
                            key,
                            parse_float(
                                value.get(
                                    "odd"
                                )
                            )
                        )


            elif (
                "home team total"
                in bet_name

                or

                "home total"
                in bet_name
            ):

                for value in values:

                    text = norm(
                        value.get(
                            "value"
                        )
                    )


                    match = re.search(
                        (
                            r"(over|under)"
                            r"\s*"
                            r"([0-9]+(?:\.[0-9]+)?)"
                        ),
                        text
                    )


                    if not match:
                        continue


                    side = match.group(
                        1
                    )


                    line = parse_float(
                        match.group(
                            2
                        )
                    )


                    if line in TEAM_TOTAL_POINTS:

                        first_empty_set(
                            result[
                                "team_totals"
                            ][
                                "home"
                            ][
                                str(
                                    line
                                )
                            ],
                            side,
                            parse_float(
                                value.get(
                                    "odd"
                                )
                            )
                        )


            elif (
                "away team total"
                in bet_name

                or

                "away total"
                in bet_name
            ):

                for value in values:

                    text = norm(
                        value.get(
                            "value"
                        )
                    )


                    match = re.search(
                        (
                            r"(over|under)"
                            r"\s*"
                            r"([0-9]+(?:\.[0-9]+)?)"
                        ),
                        text
                    )


                    if not match:
                        continue


                    side = match.group(
                        1
                    )


                    line = parse_float(
                        match.group(
                            2
                        )
                    )


                    if line in TEAM_TOTAL_POINTS:

                        first_empty_set(
                            result[
                                "team_totals"
                            ][
                                "away"
                            ][
                                str(
                                    line
                                )
                            ],
                            side,
                            parse_float(
                                value.get(
                                    "odd"
                                )
                            )
                        )


    if all(
        value is None
        for value
        in result[
            "odds"
        ].values()
    ):

        result[
            "odds"
        ] = None


    if all(
        value is None
        for value
        in result[
            "double_chance"
        ].values()
    ):

        result[
            "double_chance"
        ] = None


    if all(
        value is None
        for value
        in result[
            "btts"
        ].values()
    ):

        result[
            "btts"
        ] = None


    if all(
        value is None
        for side
        in result[
            "handicaps"
        ].values()
        for value
        in side.values()
    ):

        result[
            "handicaps"
        ] = None


    if all(
        value is None
        for team
        in result[
            "team_totals"
        ].values()
        for line
        in team.values()
        for value
        in line.values()
    ):

        result[
            "team_totals"
        ] = None


    return result


def fetch_fixture_odds(
    fixture_id,
    force=False
):

    cache_key = str(
        int(
            fixture_id
        )
    )


    cached = odds_detail_cache.get(
        cache_key
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
        ODDS_DETAIL_CACHE_SECONDS
    ):

        return cached[
            "data"
        ]


    data = api_get(
        "odds",
        {
            "fixture":
                int(
                    fixture_id
                )
        }
    )


    response_items = data.get(
        "response",
        []
    )


    if not response_items:

        parsed = {
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


    else:

        parsed = parse_api_football_odds(
            response_items[0]
        )


    odds_detail_cache[
        cache_key
    ] = {
        "time":
            time.time(),

        "data":
            parsed
    }


    return parsed


def load_list_odds(
    force=False
):

    if (
        not force
        and
        odds_list_cache[
            "data"
        ]
        and
        time.time()
        -
        odds_list_cache[
            "time"
        ]
        <
        ODDS_LIST_CACHE_SECONDS
    ):

        return odds_list_cache[
            "data"
        ]


    by_fixture = {}


    page = 1

    max_pages = 4


    while (
        page
        <=
        max_pages
    ):

        data = api_get(
            "odds",
            {
                "league":
                    PREMIER_LEAGUE_ID,

                "season":
                    current_season(),

                "page":
                    page
            }
        )


        for item in data.get(
            "response",
            []
        ):

            fixture_id = (
                item.get(
                    "fixture"
                )
                or
                {}
            ).get(
                "id"
            )


            if fixture_id:

                parsed = (
                    parse_api_football_odds(
                        item
                    )
                )


                by_fixture[
                    int(
                        fixture_id
                    )
                ] = parsed


                odds_detail_cache[
                    str(
                        int(
                            fixture_id
                        )
                    )
                ] = {
                    "time":
                        time.time(),

                    "data":
                        parsed
                }


        total_pages = int(
            (
                data.get(
                    "paging"
                )
                or
                {}
            ).get(
                "total"
            )
            or
            1
        )


        if page >= total_pages:
            break


        page += 1


    odds_list_cache[
        "time"
    ] = time.time()


    odds_list_cache[
        "data"
    ] = by_fixture


    return by_fixture


def get_cached_fixture(
    fixture_id
):

    fixture_id = int(
        fixture_id
    )


    for match in load_fixtures():

        if (
            int(
                match.get(
                    "fixture_id"
                )
                or
                0
            )
            ==
            fixture_id
        ):

            return match


    return None


def match_is_open(
    status
):

    return status in (
        "NS",
        "TBD"
    )


def canonical_market_odd(
    parsed,
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


    if selection == "П1":

        return (
            (
                parsed.get(
                    "odds"
                )
                or
                {}
            ).get(
                "home"
            ),
            "П1"
        )


    if selection == "X":

        return (
            (
                parsed.get(
                    "odds"
                )
                or
                {}
            ).get(
                "draw"
            ),
            "X"
        )


    if selection == "П2":

        return (
            (
                parsed.get(
                    "odds"
                )
                or
                {}
            ).get(
                "away"
            ),
            "П2"
        )


    if selection in (
        "1X",
        "12",
        "X2"
    ):

        key = {
            "1X": "1x",
            "12": "12",
            "X2": "x2"
        }[
            selection
        ]


        return (
            (
                parsed.get(
                    "double_chance"
                )
                or
                {}
            ).get(
                key
            ),
            selection
        )


    if selection == "ОЗ Да":

        return (
            (
                parsed.get(
                    "btts"
                )
                or
                {}
            ).get(
                "yes"
            ),
            selection
        )


    if selection == "ОЗ Нет":

        return (
            (
                parsed.get(
                    "btts"
                )
                or
                {}
            ).get(
                "no"
            ),
            selection
        )


    total_match = re.fullmatch(
        r"Т([БМ])\s*([0-9.]+)",
        selection
    )


    if total_match:

        line = parse_float(
            total_match.group(
                2
            )
        )


        if line not in TOTAL_POINTS:

            return (
                None,
                selection
            )


        side = (
            "over"
            if total_match.group(
                1
            )
            ==
            "Б"
            else
            "under"
        )


        odd = (
            parsed.get(
                "totals"
            )
            or
            {}
        ).get(
            str(
                line
            ),
            {}
        ).get(
            side
        )


        return (
            odd,
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


        line = parse_float(
            handicap_match.group(
                2
            )
        )


        if line not in HANDICAP_POINTS:

            return (
                None,
                selection
            )


        side = (
            "home"
            if team_number == 1
            else
            "away"
        )


        key = str(
            line
        ).rstrip(
            "0"
        ).rstrip(
            "."
        )


        odd = (
            parsed.get(
                "handicaps"
            )
            or
            {}
        ).get(
            side,
            {}
        ).get(
            key
        )


        signed = (
            f"+{key}"
            if line > 0
            else
            key
        )


        return (
            odd,
            f"Ф{team_number}({signed})"
        )


    team_total_match = re.fullmatch(
        r"ИТ([БМ])([12])\(([0-9.]+)\)",
        selection
    )


    if team_total_match:

        direction = (
            "over"
            if team_total_match.group(
                1
            )
            ==
            "Б"
            else
            "under"
        )


        team_number = int(
            team_total_match.group(
                2
            )
        )


        line = parse_float(
            team_total_match.group(
                3
            )
        )


        if line not in TEAM_TOTAL_POINTS:

            return (
                None,
                selection
            )


        side = (
            "home"
            if team_number == 1
            else
            "away"
        )


        odd = (
            parsed.get(
                "team_totals"
            )
            or
            {}
        ).get(
            side,
            {}
        ).get(
            str(
                line
            ),
            {}
        ).get(
            direction
        )


        return (
            odd,
            (
                f"ИТ"
                f"{team_total_match.group(1)}"
                f"{team_number}"
                f"({line})"
            )
        )


    return (
        None,
        selection
    )


def resolve_canonical_bet(
    fixture_id,
    selection
):

    match = get_cached_fixture(
        fixture_id
    )


    if not match:

        raise ValueError(
            "Матч не найден"
        )


    if not match_is_open(
        match.get(
            "status"
        )
    ):

        raise ValueError(
            "На этот матч уже нельзя ставить"
        )


    parsed = fetch_fixture_odds(
        fixture_id
    )


    (
        odd,
        canonical_selection
    ) = canonical_market_odd(
        parsed,
        selection
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

        "match": (
            f"{match['home']} — "
            f"{match['away']}"
        ),

        "selection":
            canonical_selection,

        "odd":
            odd,

        "provider":
            "api-football"
    }


# =========================================================
# SETTLEMENT
# =========================================================


def get_api_fixture_result(
    fixture_id
):

    fixture_id = int(
        fixture_id
    )


    cached = result_cache.get(
        fixture_id
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


    data = api_get(
        "fixtures",
        {
            "id":
                fixture_id
        }
    )


    items = data.get(
        "response",
        []
    )


    if not items:
        return None


    item = items[0]


    fixture = item.get(
        "fixture",
        {}
    )


    teams = item.get(
        "teams",
        {}
    )


    goals = item.get(
        "goals",
        {}
    )


    result = {
        "fixture_id":
            fixture_id,

        "status": (
            fixture.get(
                "status"
            )
            or
            {}
        ).get(
            "short"
        ),

        "home":
            (
                teams.get(
                    "home"
                )
                or
                {}
            ).get(
                "name"
            ),

        "away":
            (
                teams.get(
                    "away"
                )
                or
                {}
            ).get(
                "name"
            ),

        "home_score":
            goals.get(
                "home"
            ),

        "away_score":
            goals.get(
                "away"
            )
    }


    result_cache[
        fixture_id
    ] = {
        "time":
            time.time(),

        "data":
            result
    }


    return result


def get_legacy_result(
    fixture_id
):

    if not FOOTBALL_TOKEN:
        return None


    response = requests.get(
        (
            f"{FOOTBALL_DATA_URL}/"
            f"matches/{int(fixture_id)}"
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
        data.get(
            "score"
        )
        or
        {}
    ).get(
        "fullTime"
    ) or {}


    return {
        "fixture_id":
            int(
                fixture_id
            ),

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


def is_finished(
    provider,
    status
):

    if provider == "api-football":

        return status in (
            "FT",
            "AET",
            "PEN"
        )


    return status == "FINISHED"


def get_result(
    provider,
    fixture_id
):

    try:

        if provider == "api-football":

            return get_api_fixture_result(
                fixture_id
            )


        return get_legacy_result(
            fixture_id
        )


    except Exception:

        return None


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

    total_goals = (
        home_score
        +
        away_score
    )


    direct_results = {
        "П1":
            home_score
            >
            away_score,

        "X":
            home_score
            ==
            away_score,

        "П2":
            away_score
            >
            home_score,

        "1X":
            home_score
            >=
            away_score,

        "12":
            home_score
            !=
            away_score,

        "X2":
            away_score
            >=
            home_score,

        "ОЗ Да":
            (
                home_score > 0
                and
                away_score > 0
            ),

        "ОЗ Нет":
            (
                home_score == 0
                or
                away_score == 0
            )
    }


    if selection in direct_results:

        return (
            "win"
            if direct_results[
                selection
            ]
            else
            "loss"
        )


    total_match = re.fullmatch(
        r"Т([БМ])\s*([0-9.]+)",
        selection
    )


    if total_match:

        kind = (
            "over"
            if total_match.group(
                1
            )
            ==
            "Б"
            else
            "under"
        )


        line = float(
            total_match.group(
                2
            )
        )


        return compare_total(
            total_goals,
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


    team_total_match = re.fullmatch(
        r"ИТ([БМ])([12])\(([0-9.]+)\)",
        selection
    )


    if team_total_match:

        kind = (
            "over"
            if team_total_match.group(
                1
            )
            ==
            "Б"
            else
            "under"
        )


        team_number = int(
            team_total_match.group(
                2
            )
        )


        line = float(
            team_total_match.group(
                3
            )
        )


        goals = (
            home_score
            if team_number == 1
            else
            away_score
        )


        return compare_total(
            goals,
            line,
            kind
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

                    WHERE
                        telegram_id = %s
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

        FOR UPDATE
    """, (
        telegram_id,
    ))


    parlays = cur.fetchall()


    for (
        parlay_id,
        amount
    ) in parlays:

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


            cur.execute("""
                UPDATE parlay_legs

                SET
                    status = %s,
                    score = %s

                WHERE id = %s
            """, (
                leg_status,
                (
                    f"{int(home_score)}:"
                    f"{int(away_score)}"
                ),
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
            1.0000001
        ):

            final_status = "Возврат"

            payout = int(
                amount
            )


        else:

            final_status = "Выиграла"

            payout = int(
                int(
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
                total_odd = %s,
                possible = %s,
                settled_at = NOW()

            WHERE
                id = %s
                AND
                settled = FALSE
        """, (
            final_status,
            effective_odd,
            payout,
            parlay_id
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

                    WHERE
                        telegram_id = %s
                """, (
                    payout,
                    telegram_id
                ))


            if final_status == "Выиграла":

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
# USER BETS
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

            "created_at": (
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


    result = []


    for row in cur.fetchall():

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

            "created_at": (
                row[6].isoformat()
                if row[6]
                else None
            ),

            "settled_at": (
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


    single_bets = int(
        cur.fetchone()[0]
    )


    cur.execute("""
        SELECT COUNT(*)

        FROM parlays

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))


    parlay_bets = int(
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


    single_wins = int(
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


    high_single = int(
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


    progress_values = {
        "bets_10":
            single_bets
            +
            parlay_bets,

        "wins_5":
            single_wins
            +
            parlay_wins,

        "level_5":
            level,

        "xp_500":
            user_xp,

        "high_odd_win":
            1
            if
            (
                high_single
                +
                high_parlay
            )
            >
            0
            else 0
    }


    result = []


    for achievement in ACHIEVEMENTS:

        progress = progress_values.get(
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
            or 0
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
                    or 0
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

    me = None


    if current_telegram_id is not None:

        cur.execute("""
            SELECT
                u.telegram_id,
                u.first_name,
                u.username,
                u.balance,
                u.xp,

                (
                    SELECT
                        COUNT(*) + 1

                    FROM users other

                    WHERE
                        other.xp > u.xp

                        OR (
                            other.xp = u.xp
                            AND
                            other.balance > u.balance
                        )

                        OR (
                            other.xp = u.xp
                            AND
                            other.balance = u.balance
                            AND
                            other.telegram_id < u.telegram_id
                        )
                )

            FROM users u

            WHERE
                u.telegram_id = %s
        """, (
            current_telegram_id,
        ))


        row = cur.fetchone()


        if row:

            player_xp = int(
                row[4]
                or
                0
            )


            player_level = calculate_level(
                player_xp
            )


            my_rank = int(
                row[5]
            )


            me = {
                "rank":
                    my_rank,

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
            }


    cur.close()
    conn.close()


    return {
        "players":
            players,

        "my_rank":
            my_rank,

        "me":
            me
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


    total_bets = int(
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
        (
            wins
            +
            losses
        )
        >
        0

        else
        0
    )


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
            total_bets,

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
                or 0
            ),

        "active_parlays":
            int(
                parlay[1]
                or 0
            ),

        "parlay_wins":
            int(
                parlay[2]
                or 0
            ),

        "parlay_losses":
            int(
                parlay[3]
                or 0
            ),

        "parlay_refunds":
            int(
                parlay[4]
                or 0
            ),

        "parlay_total_won":
            int(
                parlay[5]
                or 0
            )
    }


# =========================================================
# ROUTES
# =========================================================


@app.route("/")
def home():

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
            "API-Football",

        "parlays":
            True,

        "optimized_odds":
            True,

        "server_side_validation":
            True
    })


@app.route(
    "/api/matches"
)
def matches_route():

    try:

        fixtures = [
            dict(
                item
            )
            for item
            in load_fixtures()
        ]


        warning = None


        try:

            by_fixture = load_list_odds()


        except Exception as error:

            by_fixture = {}

            warning = str(
                error
            )


        for match in fixtures:

            parsed = by_fixture.get(
                int(
                    match[
                        "fixture_id"
                    ]
                )
            )


            if parsed:

                match[
                    "odds"
                ] = parsed.get(
                    "odds"
                )


        return jsonify({
            "success":
                True,

            "count":
                len(
                    fixtures
                ),

            "matches":
                fixtures,

            "odds_warning":
                warning
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
def match_detail_route(
    fixture_id
):

    try:

        match = get_cached_fixture(
            fixture_id
        )


        if not match:

            return jsonify({
                "success":
                    False,

                "error":
                    "Матч не найден"
            }), 404


        parsed = fetch_fixture_odds(
            fixture_id
        )


        result = dict(
            match
        )


        result[
            "odds"
        ] = parsed.get(
            "odds"
        )


        result[
            "double_chance"
        ] = parsed.get(
            "double_chance"
        )


        result[
            "btts"
        ] = parsed.get(
            "btts"
        )


        result[
            "handicaps"
        ] = parsed.get(
            "handicaps"
        )


        result[
            "team_totals"
        ] = parsed.get(
            "team_totals"
        )


        result[
            "bookmaker"
        ] = parsed.get(
            "bookmaker"
        )


        result[
            "available_extra_markets"
        ] = parsed.get(
            "available_markets",
            []
        )


        totals = parsed.get(
            "totals"
        ) or {}


        for line in TOTAL_POINTS:

            key = str(
                line
            )


            value = totals.get(
                key,
                {}
            )


            result[
                f"total_{key.replace('.', '_')}"
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


        return jsonify({
            "success":
                True,

            **result
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
def session_route():

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

                "next_claim": (
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


@app.route(
    "/api/bets",
    methods=[
        "POST"
    ]
)
def create_bet():

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
                    "Не удалось проверить коэффициент: "
                    f"{error}"
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


        balance = int(
            cur.fetchone()[0]
        )


        if amount > balance:

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

            WHERE
                telegram_id = %s
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
                'api-football'
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


@app.route(
    "/api/parlays",
    methods=[
        "POST"
    ]
)
def create_parlay():

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


    fixture_ids = set()

    validated = []


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


            if fixture_id in fixture_ids:

                return jsonify({
                    "success":
                        False,

                    "error":
                        "Нельзя добавить два исхода одного матча"
                }), 400


            fixture_ids.add(
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
                    "Не удалось проверить экспресс: "
                    f"{error}"
                )
        }), 503


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


        balance = int(
            cur.fetchone()[0]
        )


        if amount > balance:

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

            WHERE
                telegram_id = %s
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
                    'api-football'
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


@app.route(
    "/api/leaderboard",
    methods=[
        "POST"
    ]
)
def leaderboard_route():

    telegram_user, error = (
        require_telegram_user()
    )


    if error:
        return error


    try:

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
    "/api/daily-reward",
    methods=[
        "POST"
    ]
)
def daily_reward_route():

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


        now = datetime.now(
            timezone.utc
        )


        last_claim = row[1]


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


            conn.rollback()

            cur.close()
            conn.close()


            return jsonify({
                "success":
                    False,

                "error":
                    "Бонус уже получен",

                "seconds_left":
                    seconds_left,

                "next_claim":
                    next_claim.isoformat()
            }), 400


        reward = 300


        cur.execute("""
            UPDATE users

            SET
                balance =
                    balance + %s,

                last_daily_claim =
                    %s,

                updated_at =
                    NOW()

            WHERE telegram_id = %s
        """, (
            reward,
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


        leaderboard = get_leaderboard(
            telegram_id,
            50
        )


        return jsonify({
            "success":
                True,

            "reward":
                reward,

            "balance":
                final_balance,

            "xp_gained":
                15,

            **xp_result,

            "achievements":
                get_achievements(
                    telegram_id
                ),

            "my_rank":
                leaderboard[
                    "my_rank"
                ],

            "next_claim": (
                now
                +
                timedelta(
                    hours=24
                )
            ).isoformat(),

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


@app.route(
    "/api/tasks/claim",
    methods=[
        "POST"
    ]
)
def claim_task_route():

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
                    or 0
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
                    or 0
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

                WHERE
                    telegram_id = %s
            """, (
                reward,
                telegram_id
            ))


            cur.execute("""
                SELECT xp

                FROM users

                WHERE telegram_id = %s
            """, (
                telegram_id,
            ))


            xp_result = xp_info(
                int(
                    cur.fetchone()[0]
                    or
                    0
                )
            )


            xp_result[
                "level_reward"
            ] = 0


            xp_result[
                "levels_gained"
            ] = []


        else:

            xp_result = add_xp(
                telegram_id,
                reward,
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

            "task_key":
                task_key,

            "reward_type":
                reward_type,

            "reward":
                reward,

            "balance":
                final_balance,

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


@app.route(
    "/api/achievements/claim",
    methods=[
        "POST"
    ]
)
def claim_achievement_route():

    telegram_user, error = (
        require_telegram_user()
    )


    if error:
        return error


    body = request.get_json(
        silent=True
    ) or {}


    achievement_key = str(
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
            if item[
                "key"
            ]
            ==
            achievement_key
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


    try:

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
                if item[
                    "key"
                ]
                ==
                achievement_key
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
            achievement_key
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

            WHERE
                telegram_id = %s

            RETURNING balance
        """, (
            reward,
            telegram_id
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

            "achievement_key":
                achievement_key,

            "reward":
                reward,

            "balance":
                final_balance,

            "achievements":
                get_achievements(
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


@app.route(
    "/api/settle",
    methods=[
        "POST"
    ]
)
def settle_route():

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


        leaderboard = get_leaderboard(
            telegram_id,
            50
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


if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )


    app.run(
        host="0.0.0.0",
        port=port
    )
