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


# =========================
# ENVIRONMENT
# =========================

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


FOOTBALL_API_URL = (
    "https://api.football-data.org/v4"
)

ODDS_API_URL = (
    "https://api.the-odds-api.com/v4"
)


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


# =========================
# DATABASE
# =========================

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

    conn.commit()

    cur.close()
    conn.close()

    database_ready = True


# =========================
# TELEGRAM AUTH
# =========================

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

        # InitData старше суток
        # не принимаем
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

        if not user.get("id"):
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
                "success": False,
                "error":
                    "Telegram authentication failed"
            }),
            401
        )

    return user, None


# =========================
# USERS
# =========================

def get_or_create_user(
    telegram_user
):
    init_database()

    telegram_id = int(
        telegram_user["id"]
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
        VALUES (%s, %s, %s)

        ON CONFLICT (telegram_id)
        DO UPDATE SET
            first_name = EXCLUDED.first_name,
            username = EXCLUDED.username,
            updated_at = NOW()
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
            balance

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
        "balance": row[3]
    }


def get_user_balance(
    telegram_id
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT balance

        FROM users

        WHERE telegram_id = %s
    """, (
        telegram_id,
    ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return 0

    return row[0]


# =========================
# HELPERS
# =========================

def normalize_team(name):
    if not name:
        return ""

    name = str(name).lower().strip()

    replacements = {
        "manchester united fc":
            "manchester united",

        "manchester city fc":
            "manchester city",

        "arsenal fc":
            "arsenal",

        "chelsea fc":
            "chelsea",

        "liverpool fc":
            "liverpool",

        "tottenham hotspur fc":
            "tottenham hotspur",

        "newcastle united fc":
            "newcastle united",

        "west ham united fc":
            "west ham united",

        "brighton & hove albion fc":
            "brighton and hove albion",

        "wolverhampton wanderers fc":
            "wolverhampton wanderers",

        "nottingham forest fc":
            "nottingham forest",

        "aston villa fc":
            "aston villa",

        "everton fc":
            "everton",

        "fulham fc":
            "fulham",

        "crystal palace fc":
            "crystal palace"
    }

    if name in replacements:
        name = replacements[name]

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
    number = float(point)

    if number.is_integer():
        return str(
            int(number)
        )

    return str(number)


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

        result["home"][key] = None
        result["away"][key] = None

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

        result["home"][key] = {
            "over": None,
            "under": None
        }

        result["away"][key] = {
            "over": None,
            "under": None
        }

    return result


# =========================
# FOOTBALL DATA
# =========================

def get_football_matches():
    headers = {
        "X-Auth-Token":
            FOOTBALL_TOKEN
    }

    today = datetime.now(
        timezone.utc
    ).date()

    date_to = today + timedelta(
        days=14
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
            data.get("id"),

        "status":
            data.get("status"),

        "home":
            data.get(
                "homeTeam",
                {}
            ).get("name"),

        "away":
            data.get(
                "awayTeam",
                {}
            ).get("name"),

        "home_score":
            full_time.get("home"),

        "away_score":
            full_time.get("away"),

        "winner":
            score.get("winner")
    }


# =========================
# ODDS API
# =========================

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
        event.get("home_team")
    )

    away_normalized = normalize_team(
        event.get("away_team")
    )

    for bookmaker in event.get(
        "bookmakers",
        []
    ):

        h2h_data = None

        totals_data = (
            empty_totals()
        )

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
                        normalize_team(name)
                        == home_normalized
                    ):
                        home_odd = price

                    elif (
                        normalize_team(name)
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
                        "home":
                            home_odd,

                        "draw":
                            draw_odd,

                        "away":
                            away_odd
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

                    if (
                        point
                        not in TOTAL_POINTS
                    ):
                        continue

                    key = point_key(
                        point
                    )

                    if name == "Over":
                        totals_data[
                            key
                        ]["over"] = price

                        found = True

                    elif name == "Under":
                        totals_data[
                            key
                        ]["under"] = price

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

    if (
        home_normalized
        in combined
    ):
        return "home"

    if (
        away_normalized
        in combined
    ):
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

        if (
            response.status_code
            != 200
        ):
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


            # ОБЕ ЗАБЬЮТ
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
                    result["btts"]
                    is None
                    and
                    yes_odd is not None
                    and
                    no_odd is not None
                ):

                    result["btts"] = {
                        "yes":
                            yes_odd,

                        "no":
                            no_odd
                    }

                    result[
                        "btts_bookmaker"
                    ] = bookmaker.get(
                        "title",
                        "Bookmaker"
                    )


            # ДВОЙНОЙ ШАНС
            elif (
                market_key
                == "double_chance"
            ):

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

                    normalized = (
                        normalize_team(
                            name
                        )
                    )

                    if (
                        home_normalized
                        in normalized
                        and
                        "draw"
                        in normalized
                    ):
                        one_x = price

                    elif (
                        away_normalized
                        in normalized
                        and
                        "draw"
                        in normalized
                    ):
                        x_two = price

                    elif (
                        home_normalized
                        in normalized
                        and
                        away_normalized
                        in normalized
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
                        "1x":
                            one_x,

                        "12":
                            one_two,

                        "x2":
                            x_two
                    }

                    result[
                        "double_chance_bookmaker"
                    ] = bookmaker.get(
                        "title",
                        "Bookmaker"
                    )


            # ФОРЫ
            elif (
                market_key
                == "alternate_spreads"
            ):

                if (
                    result[
                        "handicaps"
                    ]
                    is not None
                ):
                    continue

                handicap_data = (
                    empty_handicaps()
                )

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

                    if (
                        point
                        not in HANDICAP_POINTS
                    ):
                        continue

                    key = point_key(
                        point
                    )

                    if (
                        name
                        == home_normalized
                    ):
                        handicap_data[
                            "home"
                        ][key] = price

                        found = True

                    elif (
                        name
                        == away_normalized
                    ):
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


            # ИНДИВИДУАЛЬНЫЕ ТОТАЛЫ
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
                    ] = (
                        empty_team_totals()
                    )

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

                    if (
                        point
                        not in TEAM_TOTAL_POINTS
                    ):
                        continue

                    team_side = (
                        detect_team_side(
                            outcome,
                            home_normalized,
                            away_normalized
                        )
                    )

                    over_under = (
                        detect_over_under(
                            outcome
                        )
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


# =========================
# BET SETTLEMENT
# =========================

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
    init_database()

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
            AND status = 'Активна'
            AND settled = FALSE
    """, (
        telegram_id,
    ))

    rows = cur.fetchall()

    if not rows:
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


        if (
            fixture_id
            not in match_cache
        ):

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


        home_score = (
            match_data.get(
                "home_score"
            )
        )

        away_score = (
            match_data.get(
                "away_score"
            )
        )


        if (
            home_score is None
            or
            away_score is None
        ):
            continue


        result = calculate_bet_result(
            selection,
            int(home_score),
            int(away_score)
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


        # начисляем только если
        # UPDATE действительно произошёл
        if cur.rowcount == 1:

            if payout > 0:

                cur.execute("""
                    UPDATE users

                    SET
                        balance =
                            balance + %s,
                        updated_at = NOW()

                    WHERE
                        telegram_id = %s
                """, (
                    payout,
                    telegram_id
                ))


    conn.commit()

    cur.close()
    conn.close()


# =========================
# BET LIST
# =========================

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

            "created_at":
                row[10].isoformat()
                if row[10]
                else None
        })

    return result


# =========================
# BASIC ROUTE
# =========================

@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message":
            "BetCoin server is working",
        "database":
            bool(DATABASE_URL)
    })


# =========================
# SESSION
# =========================

@app.route(
    "/api/session",
    methods=["POST"]
)
def session():

    telegram_user, error = (
        require_telegram_user()
    )

    if error:
        return error


    try:
        user = get_or_create_user(
            telegram_user
        )

        settle_user_bets(
            user["telegram_id"]
        )

        balance = get_user_balance(
            user["telegram_id"]
        )

        bets = get_user_bets(
            user["telegram_id"]
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
                balance,

            "bets":
                bets
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================
# CREATE BET
# =========================

@app.route(
    "/api/bets",
    methods=["POST"]
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
            "error":
                "Invalid bet data"
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
            "error":
                "Invalid bet data"
        }), 400


    possible = int(
        amount * odd
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


        # блокируем строку пользователя,
        # чтобы нельзя было одновременно
        # потратить один баланс дважды
        cur.execute("""
            SELECT balance

            FROM users

            WHERE telegram_id = %s

            FOR UPDATE
        """, (
            telegram_id,
        ))


        row = cur.fetchone()


        if not row:

            conn.rollback()

            cur.close()
            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "User not found"
            }), 404


        current_balance = int(
            row[0]
        )


        if (
            amount
            > current_balance
        ):

            conn.rollback()

            cur.close()
            conn.close()

            return jsonify({
                "success": False,
                "error":
                    "Недостаточно монет"
            }), 400


        new_balance = (
            current_balance
            - amount
        )


        cur.execute("""
            UPDATE users

            SET
                balance = %s,
                updated_at = NOW()

            WHERE telegram_id = %s
        """, (
            new_balance,
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


        conn.commit()

        cur.close()
        conn.close()


        return jsonify({
            "success":
                True,

            "bet_id":
                bet_id,

            "balance":
                new_balance,

            "possible":
                possible
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================
# MANUAL SETTLE
# =========================

@app.route(
    "/api/settle",
    methods=["POST"]
)
def settle():

    telegram_user, error = (
        require_telegram_user()
    )

    if error:
        return error


    try:
        user = get_or_create_user(
            telegram_user
        )

        settle_user_bets(
            user["telegram_id"]
        )

        return jsonify({
            "success":
                True,

            "balance":
                get_user_balance(
                    user[
                        "telegram_id"
                    ]
                ),

            "bets":
                get_user_bets(
                    user[
                        "telegram_id"
                    ]
                )
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================
# SINGLE MATCH
# =========================

@app.route(
    "/api/match/<int:match_id>"
)
def single_match(match_id):

    if not FOOTBALL_TOKEN:

        return jsonify({
            "success": False,
            "error":
                "FOOTBALL_DATA_TOKEN not found"
        }), 500


    try:
        result = get_single_match(
            match_id
        )

        return jsonify({
            "success":
                True,

            **result
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# =========================
# MATCH LIST
# =========================

@app.route("/api/matches")
def matches():

    if (
        cache_data["response"]
        is not None
        and
        time.time()
        - cache_data["time"]
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
            "error":
                "FOOTBALL_DATA_TOKEN not found"
        }), 500


    if not ODDS_API_KEY:

        return jsonify({
            "success": False,
            "error":
                "ODDS_API_KEY not found"
        }), 500


    try:
        (
            football_data,
            today,
            date_to
        ) = get_football_matches()

        odds_events = (
            get_featured_odds()
        )


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

            extra_markets = (
                get_extra_markets(
                    odds_event.get(
                        "id"
                    ),
                    home_name,
                    away_name
                )
            )


        match = {
            "fixture_id":
                item.get("id"),

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

            match["bookmaker"] = (
                markets.get(
                    "bookmaker"
                )
            )

            match["odds"] = (
                markets.get(
                    "h2h"
                )
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

                    match[field] = {
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

                match[key] = (
                    extra_markets.get(
                        key
                    )
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


    cache_data["time"] = (
        time.time()
    )

    cache_data["response"] = (
        result
    )


    return jsonify(
        result
    )


# =========================
# START
# =========================

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
