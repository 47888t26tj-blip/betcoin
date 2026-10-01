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


FOOTBALL_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

FOOTBALL_API_URL = "https://api.football-data.org/v4"
ODDS_API_URL = "https://api.the-odds-api.com/v4"

MATCH_LIST_CACHE_SECONDS = 1800
MATCH_DETAIL_CACHE_SECONDS = 3600

TOTAL_POINTS = [1.5, 2.5, 3.5, 4.5]

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

matches_cache = {
    "time": 0,
    "data": None
}

detail_cache = {}

fixture_event_map = {}


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


def get_db():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL not found")

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
        ADD COLUMN IF NOT EXISTS last_daily_claim TIMESTAMPTZ
    """)

    cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS xp INTEGER NOT NULL DEFAULT 0
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

            settled_at TIMESTAMPTZ
        )
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

            score TEXT
        )
    """)

    conn.commit()

    cur.close()
    conn.close()

    database_ready = True


def calculate_level(xp):

    return (
        int(
            xp or 0
        )
        // 100
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
            100 - current_level_xp
    }


def calculate_level_reward(
    old_level,
    new_level
):

    reward = 0
    gained = []

    for level_number in range(
        old_level + 1,
        new_level + 1
    ):

        current_reward = 100

        if (
            level_number % 5
            == 0
        ):

            current_reward += 500

        reward += current_reward

        gained.append({
            "level":
                level_number,

            "reward":
                current_reward
        })

    return (
        reward,
        gained
    )


def add_xp(
    telegram_id,
    amount,
    cursor=None
):

    own_connection = (
        cursor is None
    )

    conn = None

    if own_connection:

        conn = get_db()

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

    if not row:

        result = xp_info(
            0
        )

        result[
            "level_reward"
        ] = 0

        result[
            "levels_gained"
        ] = []

        return result

    old_xp = int(
        row[0] or 0
    )

    old_level = calculate_level(
        old_xp
    )

    new_xp = (
        old_xp
        + int(
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

    level_reward, gained = (
        calculate_level_reward(
            old_level,
            new_level
        )
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
    ] = gained

    return result


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

    return (
        user,
        None
    )


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


def current_task_date():

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

    conn = None

    if own_connection:

        conn = get_db()
        cursor = conn.cursor()

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
            AND
            task_date = %s
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
                login_done,

            "claimed":
                login_claimed,

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
                bets_claimed,

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
                win_claimed,

            "reward_type":
                "coins",

            "reward":
                150
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
            AND
            task_date = %s
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
            odd >= 3.0
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
            total_odd >= 3.0
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

    claimed_keys = {
        row[0]
        for row
        in cur.fetchall()
    }

    cur.close()
    conn.close()

    bets_count = (
        single_bets
        + parlay_bets
    )

    wins_count = (
        single_wins
        + parlay_wins
    )

    high_odd_wins = (
        high_single
        + high_parlay
    )

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

    rows = cur.fetchall()

    players = []

    for rank, row in enumerate(
        rows,
        start=1
    ):

        player_xp = int(
            row[4] or 0
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
                ) AS rank

            FROM users u

            WHERE
                u.telegram_id = %s
        """, (
            current_telegram_id,
        ))

        row = cur.fetchone()

        if row:

            player_xp = int(
                row[4] or 0
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

    active_bets = int(
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

    settled_staked = int(
        row[6] or 0
    )

    settled_returned = int(
        row[7] or 0
    )

    win_rate = 0.0

    if (
        wins + losses
        > 0
    ):

        win_rate = round(
            wins
            /
            (
                wins + losses
            )
            *
            100,
            1
        )

    net_profit = (
        settled_returned
        - settled_staked
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

    running_streak = 0
    best_streak = 0

    for settled_row in cur.fetchall():

        if (
            settled_row[0]
            == "Выиграла"
        ):

            running_streak += 1

            best_streak = max(
                best_streak,
                running_streak
            )

        else:

            running_streak = 0

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

    parlay_row = cur.fetchone()

    cur.close()
    conn.close()

    return {
        "total_bets":
            total_bets,

        "active_bets":
            active_bets,

        "wins":
            wins,

        "losses":
            losses,

        "refunds":
            refunds,

        "settled_bets":
            wins + losses + refunds,

        "win_rate":
            win_rate,

        "current_win_streak":
            running_streak,

        "best_win_streak":
            best_streak,

        "total_won":
            total_won,

        "settled_staked":
            settled_staked,

        "settled_returned":
            settled_returned,

        "net_profit":
            net_profit,

        "total_parlays":
            int(
                parlay_row[0]
                or 0
            ),

        "active_parlays":
            int(
                parlay_row[1]
                or 0
            ),

        "parlay_wins":
            int(
                parlay_row[2]
                or 0
            ),

        "parlay_losses":
            int(
                parlay_row[3]
                or 0
            ),

        "parlay_refunds":
            int(
                parlay_row[4]
                or 0
            ),

        "parlay_total_won":
            int(
                parlay_row[5]
                or 0
            )
    }


def normalize_team(name):

    if not name:
        return ""

    name = str(
        name
    ).lower().strip()

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
    ).strip()

    return name


def point_key(point):

    value = float(
        point
    )

    if value.is_integer():

        return str(
            int(
                value
            )
        )

    return str(
        value
    )


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
            "over":
                None,

            "under":
                None
        }

        result[
            "away"
        ][key] = {
            "over":
                None,

            "under":
                None
        }

    return result


def football_headers():

    return {
        "X-Auth-Token":
            FOOTBALL_TOKEN
    }


def get_football_matches():

    today = datetime.now(
        timezone.utc
    ).date()

    date_to = (
        today
        + timedelta(
            days=14
        )
    )

    response = requests.get(
        (
            f"{FOOTBALL_API_URL}"
            f"/competitions/PL/matches"
        ),
        headers=football_headers(),
        params={
            "dateFrom":
                today.isoformat(),

            "dateTo":
                date_to.isoformat()
        },
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

    response = requests.get(
        (
            f"{FOOTBALL_API_URL}"
            f"/matches/{fixture_id}"
        ),
        headers=football_headers(),
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

        "date":
            data.get(
                "utcDate"
            ),

        "status":
            data.get(
                "status"
            ),

        "league":
            data.get(
                "competition",
                {}
            ).get(
                "name",
                "Premier League"
            ),

        "country":
            "England",

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

        "home_logo":
            data.get(
                "homeTeam",
                {}
            ).get(
                "crest",
                ""
            ),

        "away_logo":
            data.get(
                "awayTeam",
                {}
            ).get(
                "crest",
                ""
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


def safe_get_odds_list():

    if not ODDS_API_KEY:

        return (
            [],
            "ODDS_API_KEY not found"
        )

    try:

        response = requests.get(
            (
                f"{ODDS_API_URL}"
                f"/sports/soccer_epl/odds"
            ),
            params={
                "apiKey":
                    ODDS_API_KEY,

                "regions":
                    "eu",

                "markets":
                    "h2h",

                "oddsFormat":
                    "decimal",

                "dateFormat":
                    "iso"
            },
            timeout=20
        )

        if (
            response.status_code
            != 200
        ):

            try:

                message = (
                    response.json()
                    .get(
                        "message"
                    )
                )

            except Exception:

                message = (
                    response.text[
                        :200
                    ]
                )

            return (
                [],
                (
                    f"Odds API "
                    f"{response.status_code}: "
                    f"{message}"
                )
            )

        return (
            response.json(),
            None
        )

    except Exception as error:

        return (
            [],
            str(
                error
            )
        )


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

        event_home = normalize_team(
            event.get(
                "home_team"
            )
        )

        event_away = normalize_team(
            event.get(
                "away_team"
            )
        )

        if (
            event_home
            == home_normalized
            and
            event_away
            == away_normalized
        ):

            return event

    return None


def extract_h2h(
    event
):

    if not event:

        return (
            None,
            None
        )

    home = normalize_team(
        event.get(
            "home_team"
        )
    )

    away = normalize_team(
        event.get(
            "away_team"
        )
    )

    for bookmaker in event.get(
        "bookmakers",
        []
    ):

        for market in bookmaker.get(
            "markets",
            []
        ):

            if (
                market.get(
                    "key"
                )
                != "h2h"
            ):

                continue

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
                    == home
                ):

                    home_odd = price

                elif (
                    normalize_team(
                        name
                    )
                    == away
                ):

                    away_odd = price

            if (
                home_odd is not None
                and
                draw_odd is not None
                and
                away_odd is not None
            ):

                return (
                    {
                        "home":
                            home_odd,

                        "draw":
                            draw_odd,

                        "away":
                            away_odd
                    },
                    bookmaker.get(
                        "title",
                        "Bookmaker"
                    )
                )

    return (
        None,
        None
    )


def detect_team_side(
    outcome,
    home_normalized,
    away_normalized
):

    text = normalize_team(
        (
            f"{outcome.get('name', '')} "
            f"{outcome.get('description', '')}"
        )
    )

    if home_normalized in text:
        return "home"

    if away_normalized in text:
        return "away"

    return None


def detect_over_under(
    outcome
):

    text = (
        f"{outcome.get('name', '')} "
        f"{outcome.get('description', '')}"
    ).lower()

    if "over" in text:
        return "over"

    if "under" in text:
        return "under"

    return None


def get_detailed_odds(
    event_id,
    home_team,
    away_team
):

    if (
        not ODDS_API_KEY
        or
        not event_id
    ):

        return {
            "success":
                False,

            "warning":
                "Odds detail unavailable"
        }

    cache_key = str(
        event_id
    )

    cached = detail_cache.get(
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
        MATCH_DETAIL_CACHE_SECONDS
    ):

        return cached[
            "data"
        ]

    try:

        response = requests.get(
            (
                f"{ODDS_API_URL}"
                f"/sports/soccer_epl/"
                f"events/{event_id}/odds"
            ),
            params={
                "apiKey":
                    ODDS_API_KEY,

                "regions":
                    "eu",

                "markets": (
                    "totals,"
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
            },
            timeout=20
        )

        if (
            response.status_code
            != 200
        ):

            try:

                message = (
                    response.json()
                    .get(
                        "message"
                    )
                )

            except Exception:

                message = (
                    response.text[
                        :200
                    ]
                )

            return {
                "success":
                    False,

                "warning": (
                    f"Odds API "
                    f"{response.status_code}: "
                    f"{message}"
                )
            }

        data = response.json()

    except Exception as error:

        return {
            "success":
                False,

            "warning":
                str(
                    error
                )
        }

    result = {
        "success":
            True,

        "totals":
            {},

        "btts":
            None,

        "double_chance":
            None,

        "handicaps":
            None,

        "team_totals":
            None,

        "available_extra_markets":
            []
    }

    for point in TOTAL_POINTS:

        result[
            "totals"
        ][
            point_key(
                point
            )
        ] = {
            "over":
                None,

            "under":
                None
        }

    home_normalized = normalize_team(
        home_team
    )

    away_normalized = normalize_team(
        away_team
    )

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
                market_key
                not in result[
                    "available_extra_markets"
                ]
            ):

                result[
                    "available_extra_markets"
                ].append(
                    market_key
                )

            if market_key == "totals":

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

                    if point not in TOTAL_POINTS:
                        continue

                    key = point_key(
                        point
                    )

                    name = outcome.get(
                        "name"
                    )

                    price = outcome.get(
                        "price"
                    )

                    if name == "Over":

                        result[
                            "totals"
                        ][key][
                            "over"
                        ] = price

                    elif name == "Under":

                        result[
                            "totals"
                        ][key][
                            "under"
                        ] = price

            elif (
                market_key
                == "btts"
                and
                result[
                    "btts"
                ]
                is None
            ):

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

                    if name == "yes":

                        yes_odd = outcome.get(
                            "price"
                        )

                    elif name == "no":

                        no_odd = outcome.get(
                            "price"
                        )

                if (
                    yes_odd is not None
                    or
                    no_odd is not None
                ):

                    result[
                        "btts"
                    ] = {
                        "yes":
                            yes_odd,

                        "no":
                            no_odd
                    }

            elif (
                market_key
                == "double_chance"
                and
                result[
                    "double_chance"
                ]
                is None
            ):

                one_x = None
                one_two = None
                x_two = None

                for outcome in market.get(
                    "outcomes",
                    []
                ):

                    name = normalize_team(
                        outcome.get(
                            "name"
                        )
                    )

                    price = outcome.get(
                        "price"
                    )

                    if (
                        home_normalized
                        in name
                        and
                        "draw"
                        in name
                    ):

                        one_x = price

                    elif (
                        away_normalized
                        in name
                        and
                        "draw"
                        in name
                    ):

                        x_two = price

                    elif (
                        home_normalized
                        in name
                        and
                        away_normalized
                        in name
                    ):

                        one_two = price

                if (
                    one_x is not None
                    or
                    one_two is not None
                    or
                    x_two is not None
                ):

                    result[
                        "double_chance"
                    ] = {
                        "1x":
                            one_x,

                        "12":
                            one_two,

                        "x2":
                            x_two
                    }

            elif (
                market_key
                == "alternate_spreads"
                and
                result[
                    "handicaps"
                ]
                is None
            ):

                handicap_data = empty_handicaps()

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

                    if point not in HANDICAP_POINTS:
                        continue

                    key = point_key(
                        point
                    )

                    name = normalize_team(
                        outcome.get(
                            "name"
                        )
                    )

                    price = outcome.get(
                        "price"
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

                    if point not in TEAM_TOTAL_POINTS:
                        continue

                    side = detect_team_side(
                        outcome,
                        home_normalized,
                        away_normalized
                    )

                    over_under = detect_over_under(
                        outcome
                    )

                    if (
                        not side
                        or
                        not over_under
                    ):

                        continue

                    key = point_key(
                        point
                    )

                    result[
                        "team_totals"
                    ][side][key][
                        over_under
                    ] = outcome.get(
                        "price"
                    )

    detail_cache[
        cache_key
    ] = {
        "time":
            time.time(),

        "data":
            result
    }

    return result


def build_match_item(
    item,
    odds_events
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

    fixture_id = item.get(
        "id"
    )

    odds_event = find_odds_event(
        home_name,
        away_name,
        odds_events
    )

    odds = None
    bookmaker = None

    if odds_event:

        fixture_event_map[
            int(
                fixture_id
            )
        ] = odds_event.get(
            "id"
        )

        odds, bookmaker = extract_h2h(
            odds_event
        )

    return {
        "fixture_id":
            fixture_id,

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
            bookmaker,

        "odds":
            odds,

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
    }


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

        return (
            "win"
            if home_score > away_score
            else "loss"
        )

    if selection == "X":

        return (
            "win"
            if home_score == away_score
            else "loss"
        )

    if selection == "П2":

        return (
            "win"
            if away_score > home_score
            else "loss"
        )

    if selection == "1X":

        return (
            "win"
            if home_score >= away_score
            else "loss"
        )

    if selection == "12":

        return (
            "win"
            if home_score != away_score
            else "loss"
        )

    if selection == "X2":

        return (
            "win"
            if away_score >= home_score
            else "loss"
        )

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
            if total_match.group(1)
            == "Б"
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

            value = (
                home_score
                + handicap
                - away_score
            )

        else:

            value = (
                away_score
                + handicap
                - home_score
            )

        if value > 0:
            return "win"

        if value < 0:
            return "loss"

        return "refund"

    team_total_match = re.match(
        r"^ИТ([БМ])([12])\(([0-9.]+)\)$",
        selection
    )

    if team_total_match:

        bet_type = (
            "over"
            if team_total_match.group(1)
            == "Б"
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

    rows = cur.fetchall()

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

        if (
            not match_data
            or
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

        score = (
            f"{int(home_score)}:"
            f"{int(away_score)}"
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
        })

    return result


def calculate_parlay_odd(
    legs
):

    total = 1.0

    for leg in legs:

        total *= float(
            leg[
                "odd"
            ]
        )

    return round(
        total,
        4
    )


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

    parlays = []

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

        parlays.append({
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

    return parlays


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

    rows = cur.fetchall()

    match_cache = {}

    for parlay_id, amount in rows:

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

        leg_rows = cur.fetchall()

        any_loss = False
        all_resolved = True
        effective_odd = 1.0

        for leg_row in leg_rows:

            leg_id = leg_row[0]
            fixture_id = leg_row[1]
            selection = leg_row[2]
            leg_odd = float(
                leg_row[3]
            )
            current_status = leg_row[4]

            if current_status == "Проиграла":

                any_loss = True

                continue

            if current_status == "Выиграла":

                effective_odd *= leg_odd

                continue

            if current_status == "Возврат":

                continue

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

            if (
                not match_data
                or
                match_data.get(
                    "status"
                )
                != "FINISHED"
            ):

                all_resolved = False

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

            score = (
                f"{int(home_score)}:"
                f"{int(away_score)}"
            )

            if result == "win":

                leg_status = "Выиграла"

                effective_odd *= leg_odd

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
            <= 1.0000001
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

            if (
                final_status
                == "Выиграла"
            ):

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

        "parlays":
            True,

        "optimized_odds":
            True
    })


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

        settle_user_parlays(
            telegram_id
        )

        user = get_user_data(
            telegram_id
        )

        player_xp = xp_info(
            user[
                "xp"
            ]
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
                +
                timedelta(
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
            "success":
                False,

            "error":
                str(
                    error
                )
        }), 500


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
            "success":
                True,

            "players":
                data[
                    "players"
                ],

            "my_rank":
                data[
                    "my_rank"
                ],

            "me":
                data[
                    "me"
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
            "success":
                False,

            "error":
                "Некорректные данные ставки"
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
            "success":
                False,

            "error":
                "Некорректные данные ставки"
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
    methods=["POST"]
)
def create_parlay():

    telegram_user, error = require_telegram_user()

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
        ) < 2
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

    parsed_legs = []
    fixture_ids = set()

    try:

        for leg in legs:

            fixture_id = int(
                leg.get(
                    "fixture_id"
                )
            )

            match_name = str(
                leg.get(
                    "match",
                    ""
                )
            ).strip()

            selection = str(
                leg.get(
                    "selection",
                    ""
                )
            ).strip()

            odd = float(
                leg.get(
                    "odd"
                )
            )

            if (
                odd <= 1
                or
                not match_name
                or
                not selection
            ):

                raise ValueError()

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

            parsed_legs.append({
                "fixture_id":
                    fixture_id,

                "match":
                    match_name,

                "selection":
                    selection,

                "odd":
                    odd
            })

    except Exception:

        return jsonify({
            "success":
                False,

            "error":
                "Некорректные события экспресса"
        }), 400

    total_odd = calculate_parlay_odd(
        parsed_legs
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

        for leg in parsed_legs:

            cur.execute("""
                INSERT INTO parlay_legs (
                    parlay_id,
                    fixture_id,
                    match_name,
                    selection,
                    odd,
                    status
                )

                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'Активна'
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

        last_claim = row[1]

        now = datetime.now(
            timezone.utc
        )

        if last_claim:

            next_claim = (
                last_claim
                +
                timedelta(
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
    methods=["POST"]
)
def claim_task():

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
            current_task_date()
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

            claim_column = (
                "login_claimed"
            )

        elif task_key == "bets_3":

            completed = (
                int(
                    row[1] or 0
                )
                >= 3
            )

            claimed = bool(
                row[4]
            )

            reward_type = "coins"

            reward = 100

            claim_column = (
                "bets_claimed"
            )

        else:

            completed = (
                int(
                    row[2] or 0
                )
                >= 1
            )

            claimed = bool(
                row[5]
            )

            reward_type = "coins"

            reward = 150

            claim_column = (
                "win_claimed"
            )

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
                {claim_column}
                =
                TRUE

            WHERE
                telegram_id = %s
                AND
                task_date = %s
            """,
            (
                telegram_id,
                current_task_date()
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

            player_xp = xp_info(
                int(
                    cur.fetchone()[0]
                    or 0
                )
            )

            player_xp[
                "level_reward"
            ] = 0

            player_xp[
                "levels_gained"
            ] = []

        else:

            player_xp = add_xp(
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

            **player_xp,

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
            if item[
                "key"
            ]
            == achievement_key
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

        achievements = get_achievements(
            telegram_id
        )

        current = next(
            (
                item
                for item
                in achievements
                if item[
                    "key"
                ]
                == achievement_key
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

        settle_user_parlays(
            telegram_id
        )

        user = get_user_data(
            telegram_id
        )

        player_xp = xp_info(
            user[
                "xp"
            ]
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

            **player_xp,

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


@app.route(
    "/api/matches"
)
def matches():

    if (
        matches_cache[
            "data"
        ]
        is not None
        and
        time.time()
        -
        matches_cache[
            "time"
        ]
        <
        MATCH_LIST_CACHE_SECONDS
    ):

        return jsonify(
            matches_cache[
                "data"
            ]
        )

    if not FOOTBALL_TOKEN:

        return jsonify({
            "success":
                False,

            "error":
                "FOOTBALL_DATA_TOKEN not found"
        }), 500

    try:

        (
            football_data,
            today,
            date_to
        ) = get_football_matches()

    except Exception as error:

        return jsonify({
            "success":
                False,

            "error":
                str(
                    error
                )
        }), 500

    odds_events, odds_warning = (
        safe_get_odds_list()
    )

    result_matches = []

    for item in football_data.get(
        "matches",
        []
    ):

        result_matches.append(
            build_match_item(
                item,
                odds_events
            )
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
                result_matches
            ),

        "matches":
            result_matches,

        "odds_warning":
            odds_warning
    }

    matches_cache[
        "time"
    ] = time.time()

    matches_cache[
        "data"
    ] = result

    return jsonify(
        result
    )


@app.route(
    "/api/match/<int:match_id>"
)
def match_detail(
    match_id
):

    if not FOOTBALL_TOKEN:

        return jsonify({
            "success":
                False,

            "error":
                "FOOTBALL_DATA_TOKEN not found"
        }), 500

    try:

        match = get_single_match(
            match_id
        )

    except Exception as error:

        return jsonify({
            "success":
                False,

            "error":
                str(
                    error
                )
        }), 500

    event_id = fixture_event_map.get(
        match_id
    )

    warning = None

    if not event_id:

        odds_events, warning = (
            safe_get_odds_list()
        )

        if odds_events:

            event = find_odds_event(
                match[
                    "home"
                ],
                match[
                    "away"
                ],
                odds_events
            )

            if event:

                event_id = event.get(
                    "id"
                )

                fixture_event_map[
                    match_id
                ] = event_id

                (
                    match[
                        "odds"
                    ],
                    match[
                        "bookmaker"
                    ]
                ) = extract_h2h(
                    event
                )

            else:

                match[
                    "odds"
                ] = None

                match[
                    "bookmaker"
                ] = None

        else:

            match[
                "odds"
            ] = None

            match[
                "bookmaker"
            ] = None

    else:

        match[
            "odds"
        ] = None

        match[
            "bookmaker"
        ] = None

        cached_data = (
            matches_cache.get(
                "data"
            )
            or {}
        )

        for item in cached_data.get(
            "matches",
            []
        ):

            if (
                int(
                    item.get(
                        "fixture_id"
                    )
                )
                ==
                int(
                    match_id
                )
            ):

                match[
                    "odds"
                ] = item.get(
                    "odds"
                )

                match[
                    "bookmaker"
                ] = item.get(
                    "bookmaker"
                )

                break

    detail = get_detailed_odds(
        event_id,
        match[
            "home"
        ],
        match[
            "away"
        ]
    )

    totals = detail.get(
        "totals",
        {}
    )

    for point in TOTAL_POINTS:

        key = point_key(
            point
        )

        value = totals.get(
            key
        )

        field_name = (
            "total_"
            +
            key.replace(
                ".",
                "_"
            )
        )

        if (
            value
            and
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
        ):

            match[
                field_name
            ] = {
                "point":
                    point,

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
                field_name
            ] = None

    match[
        "btts"
    ] = detail.get(
        "btts"
    )

    match[
        "double_chance"
    ] = detail.get(
        "double_chance"
    )

    match[
        "handicaps"
    ] = detail.get(
        "handicaps"
    )

    match[
        "team_totals"
    ] = detail.get(
        "team_totals"
    )

    match[
        "available_extra_markets"
    ] = detail.get(
        "available_extra_markets",
        []
    )

    return jsonify({
        "success":
            True,

        **match,

        "odds_warning": (
            detail.get(
                "warning"
            )
            or
            warning
        )
    })


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
