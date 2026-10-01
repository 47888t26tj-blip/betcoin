import os
import re
import time
import json
import hmac
import hashlib
import requests
import psycopg2

from urllib.parse import parse_qsl
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS


app = Flask(__name__)
CORS(app)


# =========================================================
# ENVIRONMENT
# =========================================================

FOOTBALL_TOKEN = os.environ.get(
    "FOOTBALL_DATA_TOKEN",
    ""
).strip()

ODDS_API_KEY = os.environ.get(
    "ODDS_API_KEY",
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


FOOTBALL_API_URL = "https://api.football-data.org/v4"
ODDS_API_URL = "https://api.the-odds-api.com/v4"


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


CACHE_SECONDS = 600


cache_data = {
    "time": 0,
    "response": None
}


database_ready = False


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
        raise Exception(
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
            balance INTEGER NOT NULL DEFAULT 1000,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
        xp INTEGER NOT NULL DEFAULT 0
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

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        bets_telegram_id_index
        ON bets (telegram_id)
    """)


    cur.execute("""
        CREATE INDEX IF NOT EXISTS
        bets_fixture_id_index
        ON bets (fixture_id)
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


    conn.commit()

    cur.close()
    conn.close()

    database_ready = True


# =========================================================
# XP / LEVELS / LEAGUES
# =========================================================

def calculate_level(xp):

    xp = int(
        xp or 0
    )

    return (
        xp // 100
    ) + 1


def get_league(level):

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


def xp_info(xp):

    xp = int(
        xp or 0
    )


    level = calculate_level(
        xp
    )


    current_level_xp = (
        xp % 100
    )


    league = get_league(
        level
    )


    return {
        "xp":
            xp,

        "level":
            level,

        "current_level_xp":
            current_level_xp,

        "xp_to_next_level":
            100 - current_level_xp,

        "league":
            league
    }


def calculate_level_reward(
    old_level,
    new_level
):

    total_reward = 0
    reached_levels = []


    if new_level <= old_level:

        return {
            "reward": 0,
            "levels": []
        }


    for level_number in range(
        old_level + 1,
        new_level + 1
    ):

        reward = 100


        if (
            level_number % 5
            == 0
        ):

            reward += 500


        total_reward += reward


        reached_levels.append({
            "level":
                level_number,

            "reward":
                reward
        })


    return {
        "reward":
            total_reward,

        "levels":
            reached_levels
    }


def add_xp(
    telegram_id,
    amount,
    cursor=None
):

    own_connection = False
    conn = None


    if cursor is None:

        conn = get_db()
        cursor = conn.cursor()

        own_connection = True


    cursor.execute("""
        SELECT xp

        FROM users

        WHERE telegram_id = %s

        FOR UPDATE
    """, (
        telegram_id,
    ))


    row = cursor.fetchone()


    if not row:

        if own_connection:

            conn.rollback()
            cursor.close()
            conn.close()


        result = xp_info(
            0
        )

        result["level_reward"] = 0
        result["levels_gained"] = []

        return result


    old_xp = int(
        row[0]
        or 0
    )


    old_level = calculate_level(
        old_xp
    )


    new_xp = (
        old_xp
        + int(amount)
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


    reward_data = calculate_level_reward(
        old_level,
        new_level
    )


    level_reward = int(
        reward_data[
            "reward"
        ]
    )


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
    ] = reward_data[
        "levels"
    ]


    return result


# =========================================================
# TELEGRAM AUTH
# =========================================================

def verify_telegram_init_data(
    init_data
):

    if not TELEGRAM_BOT_TOKEN:
        return None

    if not init_data:
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


        now = int(
            time.time()
        )


        if (
            auth_date <= 0
            or
            now - auth_date > 86400
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


def get_telegram_user():

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


    return verify_telegram_init_data(
        init_data
    )


def require_telegram_user():

    user = get_telegram_user()


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


# =========================================================
# USERS
# =========================================================

def get_or_create_user(
    telegram_user
):

    init_database()


    telegram_id = int(
        telegram_user[
            "id"
        ]
    )


    first_name = telegram_user.get(
        "first_name",
        ""
    )


    username = telegram_user.get(
        "username",
        ""
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
        first_name,
        username
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
# LEADERBOARD
# =========================================================

def get_leaderboard(
    current_telegram_id=None,
    limit=50
):

    init_database()


    limit = max(
        1,
        min(
            int(limit),
            100
        )
    )


    conn = get_db()
    cur = conn.cursor()


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


    rows = cur.fetchall()


    leaderboard = []


    for index, row in enumerate(
        rows,
        start=1
    ):

        player_xp = int(
            row[4]
            or 0
        )


        player_level = calculate_level(
            player_xp
        )


        league = get_league(
            player_level
        )


        leaderboard.append({
            "rank":
                index,

            "telegram_id":
                row[0],

            "first_name":
                row[1]
                or "Игрок",

            "username":
                row[2]
                or "",

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
                league
        })


    my_rank = None
    my_player = None


    if current_telegram_id is not None:

        cur.execute("""
            SELECT
                u.telegram_id,
                u.first_name,
                u.username,
                u.balance,
                u.xp,

                (
                    SELECT COUNT(*) + 1

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
                ) AS rank

            FROM users u

            WHERE u.telegram_id = %s
        """, (
            current_telegram_id,
        ))


        row = cur.fetchone()


        if row:

            player_xp = int(
                row[4]
                or 0
            )


            player_level = calculate_level(
                player_xp
            )


            league = get_league(
                player_level
            )


            my_rank = int(
                row[5]
            )


            my_player = {
                "rank":
                    my_rank,

                "telegram_id":
                    row[0],

                "first_name":
                    row[1]
                    or "Игрок",

                "username":
                    row[2]
                    or "",

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
                    league
            }


    cur.close()
    conn.close()


    return {
        "players":
            leaderboard,

        "my_rank":
            my_rank,

        "me":
            my_player
    }


# =========================================================
# DAILY TASKS
# =========================================================

def current_task_date():

    return datetime.now(
        timezone.utc
    ).date()


def ensure_daily_tasks(
    telegram_id,
    cursor=None,
    mark_login=False
):

    own_connection = False
    conn = None


    if cursor is None:

        conn = get_db()
        cursor = conn.cursor()

        own_connection = True


    today = current_task_date()


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
                AND task_date = %s
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
            AND task_date = %s
    """, (
        telegram_id,
        current_task_date()
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
            AND task_date = %s
    """, (
        telegram_id,
        current_task_date()
    ))


def build_daily_tasks(
    row
):

    if not row:
        return []


    login_done = bool(
        row[0]
    )

    bets_count = int(
        row[1]
        or 0
    )

    wins_count = int(
        row[2]
        or 0
    )

    login_claimed = bool(
        row[3]
    )

    bets_claimed = bool(
        row[4]
    )

    win_claimed = bool(
        row[5]
    )


    return [
        {
            "key": "login",
            "title": "Зайти в приложение",
            "description": "Открой BetCoin сегодня",
            "progress": 1 if login_done else 0,
            "target": 1,
            "completed": login_done,
            "claimed": login_claimed,
            "reward_type": "xp",
            "reward": 50
        },

        {
            "key": "bets_3",
            "title": "Сделать 3 ставки",
            "description": "Сделай 3 ставки за сегодня",
            "progress": min(
                bets_count,
                3
            ),
            "target": 3,
            "completed": bets_count >= 3,
            "claimed": bets_claimed,
            "reward_type": "coins",
            "reward": 100
        },

        {
            "key": "win_1",
            "title": "Выиграть 1 ставку",
            "description": "Получи хотя бы один выигрыш сегодня",
            "progress": min(
                wins_count,
                1
            ),
            "target": 1,
            "completed": wins_count >= 1,
            "claimed": win_claimed,
            "reward_type": "coins",
            "reward": 150
        }
    ]


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
            AND task_date = %s
    """, (
        telegram_id,
        current_task_date()
    ))


    row = cur.fetchone()


    conn.commit()

    cur.close()
    conn.close()


    return build_daily_tasks(
        row
    )


# =========================================================
# ACHIEVEMENTS
# =========================================================

def get_achievements(
    telegram_id
):

    init_database()


    conn = get_db()
    cur = conn.cursor()


    cur.execute("""
        SELECT xp

        FROM users

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))


    user_row = cur.fetchone()


    user_xp = int(
        user_row[0]
        if user_row
        else 0
    )


    user_level = calculate_level(
        user_xp
    )


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
            AND status = 'Выиграла'
    """, (
        telegram_id,
    ))


    wins_count = int(
        cur.fetchone()[0]
    )


    cur.execute("""
        SELECT COUNT(*)

        FROM bets

        WHERE
            telegram_id = %s
            AND status = 'Выиграла'
            AND odd >= 3.0
    """, (
        telegram_id,
    ))


    high_odd_wins = int(
        cur.fetchone()[0]
    )


    cur.execute("""
        SELECT achievement_key

        FROM achievement_claims

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))


    claimed_keys = {
        row[0]
        for row
        in cur.fetchall()
    }


    cur.close()
    conn.close()


    result = []


    for achievement in ACHIEVEMENTS:

        key = achievement[
            "key"
        ]


        if key == "bets_10":
            progress = bets_count

        elif key == "wins_5":
            progress = wins_count

        elif key == "level_5":
            progress = user_level

        elif key == "xp_500":
            progress = user_xp

        elif key == "high_odd_win":
            progress = (
                1
                if high_odd_wins > 0
                else 0
            )

        else:
            progress = 0


        target = achievement[
            "target"
        ]


        result.append({
            "key":
                key,

            "title":
                achievement[
                    "title"
                ],

            "description":
                achievement[
                    "description"
                ],

            "progress":
                min(
                    progress,
                    target
                ),

            "target":
                target,

            "completed":
                progress >= target,

            "claimed":
                key in claimed_keys,

            "reward":
                achievement[
                    "reward"
                ]
        })


    return result


# =========================================================
# HELPERS
# =========================================================

def normalize_team(name):

    if not name:
        return ""


    name = str(
        name
    ).lower().strip()


    replacements = {
        "manchester united fc": "manchester united",
        "manchester city fc": "manchester city",
        "arsenal fc": "arsenal",
        "chelsea fc": "chelsea",
        "liverpool fc": "liverpool",
        "tottenham hotspur fc": "tottenham hotspur",
        "newcastle united fc": "newcastle united",
        "west ham united fc": "west ham united",
        "brighton & hove albion fc": "brighton and hove albion",
        "wolverhampton wanderers fc": "wolverhampton wanderers",
        "nottingham forest fc": "nottingham forest",
        "aston villa fc": "aston villa",
        "everton fc": "everton",
        "fulham fc": "fulham",
        "crystal palace fc": "crystal palace"
    }


    if name in replacements:

        name = replacements[
            name
        ]


    name = name.replace(
        "&",
        "and"
    )


    name = re.sub(
        r"\bfc\b",
        "",
        name
    )


    name = re.sub(
        r"\s+",
        " ",
        name
    )


    return name.strip()


def point_key(point):

    number = float(
        point
    )


    if number.is_integer():
        return str(
            int(number)
        )


    return str(
        number
    )


def empty_totals():

    result = {}


    for point in TOTAL_POINTS:

        result[
            point_key(point)
        ] = {
            "over": None,
            "under": None
        }


    return result


def empty_handicaps():

    result = {
        "home": {},
        "away": {}
    }


    for point in HANDICAP_POINTS:

        key = point_key(
            point
        )


        result[
            "home"
        ][key] = None


        result[
            "away"
        ][key] = None


    return result


def empty_team_totals():

    result = {
        "home": {},
        "away": {}
    }


    for point in TEAM_TOTAL_POINTS:

        key = point_key(
            point
        )


        result[
            "home"
        ][key] = {
            "over": None,
            "under": None
        }


        result[
            "away"
        ][key] = {
            "over": None,
            "under": None
        }


    return result


# =========================================================
# FOOTBALL DATA
# =========================================================

def get_football_matches():

    headers = {
        "X-Auth-Token":
            FOOTBALL_TOKEN
    }


    today = datetime.now(
        timezone.utc
    ).date()


    date_to = (
        today
        + timedelta(
            days=14
        )
    )


    params = {
        "dateFrom":
            today.isoformat(),

        "dateTo":
            date_to.isoformat()
    }


    response = requests.get(
        (
            f"{FOOTBALL_API_URL}"
            f"/competitions/PL/matches"
        ),
        headers=headers,
        params=params,
        timeout=20
    )


    response.raise_for_status()


    return (
        response.json(),
        today,
        date_to
    )


def get_single_match(
    fixture_id
):

    headers = {
        "X-Auth-Token":
            FOOTBALL_TOKEN
    }


    response = requests.get(
        (
            f"{FOOTBALL_API_URL}"
            f"/matches/{fixture_id}"
        ),
        headers=headers,
        timeout=20
    )


    response.raise_for_status()


    data = response.json()


    score = data.get(
        "score",
        {}
    )


    full_time = score.get(
        "fullTime",
        {}
    )


    return {
        "fixture_id":
            data.get(
                "id"
            ),

        "status":
            data.get(
                "status"
            ),

        "home":
            data.get(
                "homeTeam",
                {}
            ).get(
                "name"
            ),

        "away":
            data.get(
                "awayTeam",
                {}
            ).get(
                "name"
            ),

        "home_score":
            full_time.get(
                "home"
            ),

        "away_score":
            full_time.get(
                "away"
            ),

        "winner":
            score.get(
                "winner"
            )
    }


# =========================================================
# ODDS
# =========================================================

def get_featured_odds():

    params = {
        "apiKey":
            ODDS_API_KEY,

        "regions":
            "eu",

        "markets":
            "h2h,totals",

        "oddsFormat":
            "decimal",

        "dateFormat":
            "iso"
    }


    response = requests.get(
        (
            f"{ODDS_API_URL}"
            f"/sports/soccer_epl/odds"
        ),
        params=params,
        timeout=20
    )


    response.raise_for_status()

    return response.json()


def find_odds_event(
    home_team,
    away_team,
    odds_events
):

    home_normalized = normalize_team(
        home_team
    )


    away_normalized = normalize_team(
        away_team
    )


    for event in odds_events:

        odds_home = normalize_team(
            event.get(
                "home_team"
            )
        )


        odds_away = normalize_team(
            event.get(
                "away_team"
            )
        )


        if (
            home_normalized == odds_home
            and
            away_normalized == odds_away
        ):

            return event


    return None


def get_main_markets(event):

    if not event:
        return None


    home_normalized = normalize_team(
        event.get(
            "home_team"
        )
    )


    away_normalized = normalize_team(
        event.get(
            "away_team"
        )
    )


    for bookmaker in event.get(
        "bookmakers",
        []
    ):

        h2h_data = None

        totals_data = empty_totals()

        found = False


        for market in bookmaker.get(
            "markets",
            []
        ):

            market_key = market.get(
                "key"
            )


            if market_key == "h2h":

                home_odd = None
                draw_odd = None
                away_odd = None


                for outcome in market.get(
                    "outcomes",
                    []
                ):

                    name = outcome.get(
                        "name"
                    )

                    price = outcome.get(
                        "price"
                    )


                    if name == "Draw":

                        draw_odd = price


                    elif (
                        normalize_team(
                            name
                        )
                        == home_normalized
                    ):

                        home_odd = price


                    elif (
                        normalize_team(
                            name
                        )
                        == away_normalized
                    ):

                        away_odd = price


                if (
                    home_odd is not None
                    and
                    draw_odd is not None
                    and
                    away_odd is not None
                ):

                    h2h_data = {
                        "home": home_odd,
                        "draw": draw_odd,
                        "away": away_odd
                    }

                    found = True


            elif market_key == "totals":

                for outcome in market.get(
                    "outcomes",
                    []
                ):

                    point = outcome.get(
                        "point"
                    )


                    name = outcome.get(
                        "name"
                    )


                    price = outcome.get(
                        "price"
                    )


                    try:

                        point = float(
                            point
                        )

                    except Exception:

                        continue


                    if point not in TOTAL_POINTS:
                        continue


                    key = point_key(
                        point
                    )


                    if name == "Over":

                        totals_data[
                            key
                        ][
                            "over"
                        ] = price

                        found = True


                    elif name == "Under":

                        totals_data[
                            key
                        ][
                            "under"
                        ] = price

                        found = True


        if found:

            return {
                "h2h":
                    h2h_data,

                "totals":
                    totals_data,

                "bookmaker":
                    bookmaker.get(
                        "title",
                        "Bookmaker"
                    )
            }


    return None


def detect_team_side(
    outcome,
    home_normalized,
    away_normalized
):

    name = str(
        outcome.get(
            "name",
            ""
        )
    )


    description = str(
        outcome.get(
            "description",
            ""
        )
    )


    combined = normalize_team(
        name
        + " "
        + description
    )


    if home_normalized in combined:
        return "home"


    if away_normalized in combined:
        return "away"


    return None


def detect_over_under(
    outcome
):

    text = (
        str(
            outcome.get(
                "name",
                ""
            )
        )
        + " "
        + str(
            outcome.get(
                "description",
                ""
            )
        )
    ).lower()


    if "over" in text:
        return "over"


    if "under" in text:
        return "under"


    return None


def get_extra_markets(
    event_id,
    home_team,
    away_team
):

    if not event_id:
        return None


    params = {
        "apiKey":
            ODDS_API_KEY,

        "regions":
            "eu",

        "markets": (
            "btts,"
            "double_chance,"
            "alternate_spreads,"
            "team_totals,"
            "alternate_team_totals"
        ),

        "oddsFormat":
            "decimal",

        "dateFormat":
            "iso"
    }


    try:

        response = requests.get(
            (
                f"{ODDS_API_URL}"
                f"/sports/soccer_epl/"
                f"events/{event_id}/odds"
            ),
            params=params,
            timeout=20
        )


        if response.status_code != 200:
            return None


        data = response.json()


    except Exception:

        return None


    home_normalized = normalize_team(
        home_team
    )


    away_normalized = normalize_team(
        away_team
    )


    result = {
        "btts": None,
        "double_chance": None,
        "handicaps": None,
        "team_totals": None,

        "btts_bookmaker": None,
        "double_chance_bookmaker": None,
        "handicaps_bookmaker": None,
        "team_totals_bookmaker": None,

        "available_extra_markets": []
    }


    for bookmaker in data.get(
        "bookmakers",
        []
    ):

        for market in bookmaker.get(
            "markets",
            []
        ):

            market_key = market.get(
                "key"
            )


            if (
                market_key
                and
                market_key not in result[
                    "available_extra_markets"
                ]
            ):

                result[
                    "available_extra_markets"
                ].append(
                    market_key
                )


            if market_key == "btts":

                yes_odd = None
                no_odd = None


                for outcome in market.get(
                    "outcomes",
                    []
                ):

                    name = str(
                        outcome.get(
                            "name",
                            ""
                        )
                    ).lower()


                    price = outcome.get(
                        "price"
                    )


                    if name == "yes":
                        yes_odd = price

                    elif name == "no":
                        no_odd = price


                if (
                    result["btts"] is None
                    and
                    yes_odd is not None
                    and
                    no_odd is not None
                ):

                    result["btts"] = {
                        "yes": yes_odd,
                        "no": no_odd
                    }


                    result[
                        "btts_bookmaker"
                    ] = bookmaker.get(
                        "title",
                        "Bookmaker"
                    )


            elif market_key == "double_chance":

                one_x = None
                one_two = None
                x_two = None


                for outcome in market.get(
                    "outcomes",
                    []
                ):

                    name = str(
                        outcome.get(
                            "name",
                            ""
                        )
                    )


                    price = outcome.get(
                        "price"
                    )


                    normalized = normalize_team(
                        name
                    )


                    if (
                        home_normalized in normalized
                        and
                        "draw" in normalized
                    ):

                        one_x = price


                    elif (
                        away_normalized in normalized
                        and
                        "draw" in normalized
                    ):

                        x_two = price


                    elif (
                        home_normalized in normalized
                        and
                        away_normalized in normalized
                    ):

                        one_two = price


                if (
                    result[
                        "double_chance"
                    ] is None
                    and
                    (
                        one_x is not None
                        or
                        one_two is not None
                        or
                        x_two is not None
                    )
                ):

                    result[
                        "double_chance"
                    ] = {
                        "1x": one_x,
                        "12": one_two,
                        "x2": x_two
                    }


                    result[
                        "double_chance_bookmaker"
                    ] = bookmaker.get(
                        "title",
                        "Bookmaker"
                    )


            elif market_key == "alternate_spreads":

                if (
                    result[
                        "handicaps"
                    ]
                    is not None
                ):
                    continue


                handicap_data = empty_handicaps()

                found = False


                for outcome in market.get(
                    "outcomes",
                    []
                ):

                    name = normalize_team(
                        outcome.get(
                            "name"
                        )
                    )


                    point = outcome.get(
                        "point"
                    )


                    price = outcome.get(
                        "price"
                    )


                    try:

                        point = float(
                            point
                        )

                    except Exception:

                        continue


                    if point not in HANDICAP_POINTS:
                        continue


                    key = point_key(
                        point
                    )


                    if name == home_normalized:

                        handicap_data[
                            "home"
                        ][key] = price

                        found = True


                    elif name == away_normalized:

                        handicap_data[
                            "away"
                        ][key] = price

                        found = True


                if found:

                    result[
                        "handicaps"
                    ] = handicap_data


                    result[
                        "handicaps_bookmaker"
                    ] = bookmaker.get(
                        "title",
                        "Bookmaker"
                    )


            elif market_key in (
                "team_totals",
                "alternate_team_totals"
            ):

                if (
                    result[
                        "team_totals"
                    ]
                    is None
                ):

                    result[
                        "team_totals"
                    ] = empty_team_totals()


                found = False


                for outcome in market.get(
                    "outcomes",
                    []
                ):

                    try:

                        point = float(
                            outcome.get(
                                "point"
                            )
                        )

                    except Exception:

                        continue


                    price = outcome.get(
                        "price"
                    )


                    if point not in TEAM_TOTAL_POINTS:
                        continue


                    team_side = detect_team_side(
                        outcome,
                        home_normalized,
                        away_normalized
                    )


                    over_under = detect_over_under(
                        outcome
                    )


                    if (
                        not team_side
                        or
                        not over_under
                    ):

                        continue


                    key = point_key(
                        point
                    )


                    result[
                        "team_totals"
                    ][
                        team_side
                    ][
                        key
                    ][
                        over_under
                    ] = price


                    found = True


                if (
                    found
                    and
                    result[
                        "team_totals_bookmaker"
                    ]
                    is None
                ):

                    result[
                        "team_totals_bookmaker"
                    ] = bookmaker.get(
                        "title",
                        "Bookmaker"
                    )


    team_totals = result.get(
        "team_totals"
    )


    if team_totals:

        has_value = False


        for side in (
            "home",
            "away"
        ):

            for line in (
                team_totals[
                    side
                ].values()
            ):

                if (
                    line.get(
                        "over"
                    )
                    is not None
                    or
                    line.get(
                        "under"
                    )
                    is not None
                ):

                    has_value = True


        if not has_value:

            result[
                "team_totals"
            ] = None


            result[
                "team_totals_bookmaker"
            ] = None


    return result


# =========================================================
# BET RESULT
# =========================================================

def compare_total(
    value,
    line,
    bet_type
):

    if bet_type == "over":

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
        + away_score
    )


    if selection == "П1":
        return "win" if home_score > away_score else "loss"

    if selection == "X":
        return "win" if home_score == away_score else "loss"

    if selection == "П2":
        return "win" if away_score > home_score else "loss"

    if selection == "1X":
        return "win" if home_score >= away_score else "loss"

    if selection == "12":
        return "win" if home_score != away_score else "loss"

    if selection == "X2":
        return "win" if away_score >= home_score else "loss"


    if selection == "ОЗ Да":

        return (
            "win"
            if (
                home_score > 0
                and
                away_score > 0
            )
            else "loss"
        )


    if selection == "ОЗ Нет":

        return (
            "win"
            if (
                home_score == 0
                or
                away_score == 0
            )
            else "loss"
        )


    total_match = re.match(
        r"^Т([БМ])\s*([0-9.]+)$",
        selection
    )


    if total_match:

        bet_type = (
            "over"
            if total_match.group(1) == "Б"
            else "under"
        )


        line = float(
            total_match.group(2)
        )


        return compare_total(
            total_goals,
            line,
            bet_type
        )


    handicap_match = re.match(
        r"^Ф([12])\(([-+]?[0-9.]+)\)$",
        selection
    )


    if handicap_match:

        team_number = int(
            handicap_match.group(1)
        )


        handicap = float(
            handicap_match.group(2)
        )


        if team_number == 1:

            result_value = (
                home_score
                + handicap
                - away_score
            )

        else:

            result_value = (
                away_score
                + handicap
                - home_score
            )


        if result_value > 0:
            return "win"

        if result_value < 0:
            return "loss"

        return "refund"


    team_total_match = re.match(
        r"^ИТ([БМ])([12])\(([0-9.]+)\)$",
        selection
    )


    if team_total_match:

        bet_type = (
            "over"
            if team_total_match.group(1) == "Б"
            else "under"
        )


        team_number = int(
            team_total_match.group(2)
        )


        line = float(
            team_total_match.group(3)
        )


        goals = (
            home_score
            if team_number == 1
            else away_score
        )


        return compare_total(
            goals,
            line,
            bet_type
        )


    return None


def settle_user_bets(
    telegram_id
):

    init_database()


    conn = get_db()
    cur = conn.cursor()


    ensure_daily_tasks(
        telegram_id,
        cur,
        True
    )


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
            AND status = 'Активна'
            AND settled = FALSE
    """, (
        telegram_id,
    ))


    rows = cur.fetchall()


    if not rows:

        conn.commit()

        cur.close()
        conn.close()

        return


    match_cache = {}


    for row in rows:

        bet_id = row[0]
        fixture_id = row[1]
        selection = row[2]
        amount = row[3]
        possible = row[4]


        if fixture_id not in match_cache:

            try:

                match_cache[
                    fixture_id
                ] = get_single_match(
                    fixture_id
                )

            except Exception:

                match_cache[
                    fixture_id
                ] = None


        match_data = match_cache[
            fixture_id
        ]


        if not match_data:
            continue


        if (
            match_data.get(
                "status"
            )
            != "FINISHED"
        ):
            continue


        home_score = match_data.get(
            "home_score"
        )


        away_score = match_data.get(
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


        result = calculate_bet_result(
            selection,
            home_score,
            away_score
        )


        if result is None:
            continue


        score = (
            f"{home_score}:"
            f"{away_score}"
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


        else:

            status = "Проиграла"

            payout = 0


        cur.execute("""
            UPDATE bets

            SET
                status = %s,
                settled = TRUE,
                score = %s

            WHERE
                id = %s
                AND settled = FALSE
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
# BET LIST
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


    result = []


    for row in rows:

        result.append({
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

            "created_at": (
                row[10].isoformat()
                if row[10]
                else None
            )
        })


    return result


# =========================================================
# ROOT
# =========================================================

@app.route("/")
def home():

    try:

        init_database()

        db_ok = True

    except Exception:

        db_ok = False


    return jsonify({
        "status": "ok",
        "message": "BetCoin server is working",
        "database": db_ok
    })


# =========================================================
# SESSION
# =========================================================

@app.route(
    "/api/session",
    methods=["POST"]
)
def session():

    telegram_user, error = require_telegram_user()


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


        tasks = get_daily_tasks(
            telegram_id,
            True
        )


        achievements = get_achievements(
            telegram_id
        )


        leaderboard_data = get_leaderboard(
            telegram_id,
            50
        )


        user = get_user_data(
            telegram_id
        )


        bets = get_user_bets(
            telegram_id
        )


        player_xp = xp_info(
            user.get(
                "xp",
                0
            )
        )


        last_daily_claim = user.get(
            "last_daily_claim"
        )


        next_daily_claim = None

        daily_available = True

        daily_seconds_left = 0


        if last_daily_claim:

            next_daily_claim = (
                last_daily_claim
                + timedelta(
                    hours=24
                )
            )


            now = datetime.now(
                timezone.utc
            )


            if now < next_daily_claim:

                daily_available = False


                daily_seconds_left = max(
                    0,
                    int(
                        (
                            next_daily_claim
                            - now
                        ).total_seconds()
                    )
                )


        return jsonify({
            "success": True,


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


            "xp":
                player_xp[
                    "xp"
                ],


            "level":
                player_xp[
                    "level"
                ],


            "league":
                player_xp[
                    "league"
                ],


            "current_level_xp":
                player_xp[
                    "current_level_xp"
                ],


            "xp_to_next_level":
                player_xp[
                    "xp_to_next_level"
                ],


            "bets":
                bets,


            "tasks":
                tasks,


            "achievements":
                achievements,


            "leaderboard": {
                "my_rank":
                    leaderboard_data[
                        "my_rank"
                    ]
            },


            "daily_reward": {
                "amount": 300,

                "available":
                    daily_available,

                "seconds_left":
                    daily_seconds_left,

                "next_claim": (
                    next_daily_claim.isoformat()
                    if next_daily_claim
                    else None
                )
            }
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# LEADERBOARD
# =========================================================

@app.route(
    "/api/leaderboard",
    methods=["POST"]
)
def leaderboard():

    telegram_user, error = require_telegram_user()


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
            "success": True,
            "players": data["players"],
            "my_rank": data["my_rank"],
            "me": data["me"]
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# CREATE BET
# =========================================================

@app.route(
    "/api/bets",
    methods=["POST"]
)
def create_bet():

    telegram_user, error = require_telegram_user()


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


        odd = float(
            body.get(
                "odd"
            )
        )


        match_name = str(
            body.get(
                "match",
                ""
            )
        ).strip()


        selection = str(
            body.get(
                "selection",
                ""
            )
        ).strip()


    except Exception:

        return jsonify({
            "success": False,
            "error": "Invalid bet data"
        }), 400


    if (
        amount <= 0
        or
        odd <= 1
        or
        not match_name
        or
        not selection
    ):

        return jsonify({
            "success": False,
            "error": "Invalid bet data"
        }), 400


    possible = int(
        amount
        * odd
        + 0.5
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
                settled
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
                FALSE
            )

            RETURNING id
        """, (
            telegram_id,
            fixture_id,
            match_name,
            selection,
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


        tasks = get_daily_tasks(
            telegram_id,
            True
        )


        achievements = get_achievements(
            telegram_id
        )


        leaderboard_data = get_leaderboard(
            telegram_id,
            50
        )


        return jsonify({
            "success": True,

            "bet_id":
                bet_id,

            "balance":
                final_balance,

            "possible":
                possible,

            "xp_gained":
                10,

            "xp":
                xp_result["xp"],

            "level":
                xp_result["level"],

            "league":
                xp_result["league"],

            "current_level_xp":
                xp_result[
                    "current_level_xp"
                ],

            "xp_to_next_level":
                xp_result[
                    "xp_to_next_level"
                ],

            "level_reward":
                xp_result[
                    "level_reward"
                ],

            "levels_gained":
                xp_result[
                    "levels_gained"
                ],

            "tasks":
                tasks,

            "achievements":
                achievements,

            "my_rank":
                leaderboard_data[
                    "my_rank"
                ]
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# DAILY REWARD
# =========================================================

@app.route(
    "/api/daily-reward",
    methods=["POST"]
)
def daily_reward():

    telegram_user, error = require_telegram_user()


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


        current_balance = int(
            row[0]
        )


        last_claim = row[1]


        now = datetime.now(
            timezone.utc
        )


        if last_claim:

            next_claim = (
                last_claim
                + timedelta(
                    hours=24
                )
            )


            if now < next_claim:

                seconds_left = max(
                    0,
                    int(
                        (
                            next_claim
                            - now
                        ).total_seconds()
                    )
                )


                conn.rollback()

                cur.close()
                conn.close()


                return jsonify({
                    "success": False,
                    "error": "Бонус уже получен",
                    "seconds_left": seconds_left,
                    "next_claim": next_claim.isoformat()
                }), 400


        reward = 300


        cur.execute("""
            UPDATE users

            SET
                balance =
                    balance + %s,

                last_daily_claim = %s,

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


        achievements = get_achievements(
            telegram_id
        )


        leaderboard_data = get_leaderboard(
            telegram_id,
            50
        )


        return jsonify({
            "success": True,

            "reward":
                reward,

            "balance":
                final_balance,

            "xp_gained":
                15,

            "xp":
                xp_result["xp"],

            "level":
                xp_result["level"],

            "league":
                xp_result["league"],

            "current_level_xp":
                xp_result[
                    "current_level_xp"
                ],

            "xp_to_next_level":
                xp_result[
                    "xp_to_next_level"
                ],

            "level_reward":
                xp_result[
                    "level_reward"
                ],

            "levels_gained":
                xp_result[
                    "levels_gained"
                ],

            "achievements":
                achievements,

            "my_rank":
                leaderboard_data[
                    "my_rank"
                ],

            "next_claim": (
                now
                + timedelta(
                    hours=24
                )
            ).isoformat(),

            "seconds_left":
                86400
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# CLAIM DAILY TASK
# =========================================================

@app.route(
    "/api/tasks/claim",
    methods=["POST"]
)
def claim_daily_task():

    telegram_user, error = require_telegram_user()


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
            "success": False,
            "error": "Неизвестное задание"
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
                AND task_date = %s

            FOR UPDATE
        """, (
            telegram_id,
            current_task_date()
        ))


        row = cur.fetchone()


        login_done = bool(
            row[0]
        )

        bets_count = int(
            row[1] or 0
        )

        wins_count = int(
            row[2] or 0
        )

        login_claimed = bool(
            row[3]
        )

        bets_claimed = bool(
            row[4]
        )

        win_claimed = bool(
            row[5]
        )


        if task_key == "login":

            completed = login_done
            claimed = login_claimed

            reward_type = "xp"
            reward = 50

            claim_column = "login_claimed"


        elif task_key == "bets_3":

            completed = (
                bets_count >= 3
            )

            claimed = bets_claimed

            reward_type = "coins"
            reward = 100

            claim_column = "bets_claimed"


        else:

            completed = (
                wins_count >= 1
            )

            claimed = win_claimed

            reward_type = "coins"
            reward = 150

            claim_column = "win_claimed"


        if not completed:

            conn.rollback()

            cur.close()
            conn.close()


            return jsonify({
                "success": False,
                "error": "Задание ещё не выполнено"
            }), 400


        if claimed:

            conn.rollback()

            cur.close()
            conn.close()


            return jsonify({
                "success": False,
                "error": "Награда уже получена"
            }), 400


        cur.execute(
            f"""
            UPDATE daily_tasks

            SET {claim_column} = TRUE

            WHERE
                telegram_id = %s
                AND task_date = %s
            """,
            (
                telegram_id,
                current_task_date()
            )
        )


        level_reward = 0
        levels_gained = []


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

            xp_result = add_xp(
                telegram_id,
                reward,
                cur
            )


            level_reward = xp_result[
                "level_reward"
            ]


            levels_gained = xp_result[
                "levels_gained"
            ]


        cur.execute("""
            SELECT
                balance,
                xp

            FROM users

            WHERE telegram_id = %s
        """, (
            telegram_id,
        ))


        user_row = cur.fetchone()


        final_balance = int(
            user_row[0]
        )


        final_xp = int(
            user_row[1]
            or 0
        )


        conn.commit()

        cur.close()
        conn.close()


        player_xp = xp_info(
            final_xp
        )


        tasks = get_daily_tasks(
            telegram_id,
            True
        )


        achievements = get_achievements(
            telegram_id
        )


        leaderboard_data = get_leaderboard(
            telegram_id,
            50
        )


        return jsonify({
            "success": True,

            "task_key":
                task_key,

            "reward_type":
                reward_type,

            "reward":
                reward,

            "balance":
                final_balance,

            "xp":
                player_xp["xp"],

            "level":
                player_xp["level"],

            "league":
                player_xp["league"],

            "current_level_xp":
                player_xp[
                    "current_level_xp"
                ],

            "xp_to_next_level":
                player_xp[
                    "xp_to_next_level"
                ],

            "level_reward":
                level_reward,

            "levels_gained":
                levels_gained,

            "tasks":
                tasks,

            "achievements":
                achievements,

            "my_rank":
                leaderboard_data[
                    "my_rank"
                ]
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# CLAIM ACHIEVEMENT
# =========================================================

@app.route(
    "/api/achievements/claim",
    methods=["POST"]
)
def claim_achievement():

    telegram_user, error = require_telegram_user()


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
            if item["key"]
            == achievement_key
        ),
        None
    )


    if not achievement:

        return jsonify({
            "success": False,
            "error": "Неизвестное достижение"
        }), 400


    try:

        user = get_or_create_user(
            telegram_user
        )


        telegram_id = user[
            "telegram_id"
        ]


        achievements = get_achievements(
            telegram_id
        )


        current = next(
            (
                item
                for item
                in achievements
                if item["key"]
                == achievement_key
            ),
            None
        )


        if not current["completed"]:

            return jsonify({
                "success": False,
                "error": "Достижение ещё не выполнено"
            }), 400


        if current["claimed"]:

            return jsonify({
                "success": False,
                "error": "Награда уже получена"
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
                "success": False,
                "error": "Награда уже получена"
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


        final_balance = int(
            cur.fetchone()[0]
        )


        conn.commit()

        cur.close()
        conn.close()


        achievements = get_achievements(
            telegram_id
        )


        leaderboard_data = get_leaderboard(
            telegram_id,
            50
        )


        return jsonify({
            "success": True,

            "achievement_key":
                achievement_key,

            "reward":
                reward,

            "balance":
                final_balance,

            "achievements":
                achievements,

            "my_rank":
                leaderboard_data[
                    "my_rank"
                ]
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# SETTLE
# =========================================================

@app.route(
    "/api/settle",
    methods=["POST"]
)
def settle():

    telegram_user, error = require_telegram_user()


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


        user = get_user_data(
            telegram_id
        )


        player_xp = xp_info(
            user.get(
                "xp",
                0
            )
        )


        tasks = get_daily_tasks(
            telegram_id,
            True
        )


        achievements = get_achievements(
            telegram_id
        )


        leaderboard_data = get_leaderboard(
            telegram_id,
            50
        )


        return jsonify({
            "success": True,

            "balance":
                int(
                    user[
                        "balance"
                    ]
                ),

            "xp":
                player_xp["xp"],

            "level":
                player_xp["level"],

            "league":
                player_xp["league"],

            "current_level_xp":
                player_xp[
                    "current_level_xp"
                ],

            "xp_to_next_level":
                player_xp[
                    "xp_to_next_level"
                ],

            "bets":
                get_user_bets(
                    telegram_id
                ),

            "tasks":
                tasks,

            "achievements":
                achievements,

            "my_rank":
                leaderboard_data[
                    "my_rank"
                ]
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# SINGLE MATCH
# =========================================================

@app.route(
    "/api/match/<int:match_id>"
)
def single_match(
    match_id
):

    if not FOOTBALL_TOKEN:

        return jsonify({
            "success": False,
            "error": "FOOTBALL_DATA_TOKEN not found"
        }), 500


    try:

        result = get_single_match(
            match_id
        )


        return jsonify({
            "success": True,
            **result
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================================================
# MATCHES
# =========================================================

@app.route(
    "/api/matches"
)
def matches():

    if (
        cache_data[
            "response"
        ]
        is not None
        and
        time.time()
        - cache_data[
            "time"
        ]
        < CACHE_SECONDS
    ):

        return jsonify(
            cache_data[
                "response"
            ]
        )


    if not FOOTBALL_TOKEN:

        return jsonify({
            "success": False,
            "error": "FOOTBALL_DATA_TOKEN not found"
        }), 500


    if not ODDS_API_KEY:

        return jsonify({
            "success": False,
            "error": "ODDS_API_KEY not found"
        }), 500


    try:

        (
            football_data,
            today,
            date_to
        ) = get_football_matches()


        odds_events = get_featured_odds()


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


    matches_list = []


    for item in football_data.get(
        "matches",
        []
    ):

        home_team = item.get(
            "homeTeam",
            {}
        )


        away_team = item.get(
            "awayTeam",
            {}
        )


        competition = item.get(
            "competition",
            {}
        )


        home_name = home_team.get(
            "name"
        )


        away_name = away_team.get(
            "name"
        )


        odds_event = find_odds_event(
            home_name,
            away_name,
            odds_events
        )


        markets = get_main_markets(
            odds_event
        )


        extra_markets = None


        if odds_event:

            extra_markets = get_extra_markets(
                odds_event.get(
                    "id"
                ),
                home_name,
                away_name
            )


        match = {
            "fixture_id":
                item.get(
                    "id"
                ),

            "date":
                item.get(
                    "utcDate"
                ),

            "league":
                competition.get(
                    "name",
                    "Premier League"
                ),

            "country":
                "England",

            "home":
                home_name
                or "Unknown",

            "away":
                away_name
                or "Unknown",

            "home_logo":
                home_team.get(
                    "crest",
                    ""
                ),

            "away_logo":
                away_team.get(
                    "crest",
                    ""
                ),

            "status":
                item.get(
                    "status",
                    "SCHEDULED"
                ),

            "bookmaker":
                None,

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

            "btts_bookmaker":
                None,

            "double_chance":
                None,

            "double_chance_bookmaker":
                None,

            "handicaps":
                None,

            "handicaps_bookmaker":
                None,

            "team_totals":
                None,

            "team_totals_bookmaker":
                None,

            "available_extra_markets":
                []
        }


        if markets:

            match[
                "bookmaker"
            ] = markets.get(
                "bookmaker"
            )


            match[
                "odds"
            ] = markets.get(
                "h2h"
            )


            totals = markets.get(
                "totals",
                {}
            )


            for point in TOTAL_POINTS:

                key = point_key(
                    point
                )


                total = totals.get(
                    key
                )


                if (
                    total
                    and
                    (
                        total.get(
                            "over"
                        )
                        is not None
                        or
                        total.get(
                            "under"
                        )
                        is not None
                    )
                ):

                    field = (
                        "total_"
                        + key.replace(
                            ".",
                            "_"
                        )
                    )


                    match[
                        field
                    ] = {
                        "point":
                            point,

                        "over":
                            total.get(
                                "over"
                            ),

                        "under":
                            total.get(
                                "under"
                            )
                    }


        if extra_markets:

            for key in (
                "btts",
                "btts_bookmaker",
                "double_chance",
                "double_chance_bookmaker",
                "handicaps",
                "handicaps_bookmaker",
                "team_totals",
                "team_totals_bookmaker",
                "available_extra_markets"
            ):

                match[
                    key
                ] = extra_markets.get(
                    key
                )


        matches_list.append(
            match
        )


    result = {
        "success":
            True,

        "date_from":
            today.isoformat(),

        "date_to":
            date_to.isoformat(),

        "count":
            len(
                matches_list
            ),

        "matches":
            matches_list
    }


    cache_data[
        "time"
    ] = time.time()


    cache_data[
        "response"
    ] = result


    return jsonify(
        result
    )


# =========================================================
# START
# =========================================================

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
