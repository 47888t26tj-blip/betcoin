import os
import re
import time
import requests

from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify
from flask_cors import CORS


app = Flask(__name__)
CORS(app)


FOOTBALL_TOKEN = os.environ.get(
    "FOOTBALL_DATA_TOKEN",
    ""
).strip()

ODDS_API_KEY = os.environ.get(
    "ODDS_API_KEY",
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


@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "BetCoin server is working"
    })


def normalize_team(name):
    if not name:
        return ""

    name = str(name).lower().strip()

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
        name = replacements[name]

    name = name.replace("&", "and")
    name = re.sub(r"\bfc\b", "", name)
    name = re.sub(r"\s+", " ", name)

    return name.strip()


def point_key(point):
    number = float(point)

    if number.is_integer():
        return str(int(number))

    return str(number)


def get_football_matches():
    headers = {
        "X-Auth-Token": FOOTBALL_TOKEN
    }

    today = datetime.now(
        timezone.utc
    ).date()

    date_to = today + timedelta(
        days=14
    )

    params = {
        "dateFrom": today.isoformat(),
        "dateTo": date_to.isoformat()
    }

    response = requests.get(
        f"{FOOTBALL_API_URL}/competitions/PL/matches",
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


def get_featured_odds():
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
        "dateFormat": "iso"
    }

    response = requests.get(
        f"{ODDS_API_URL}/sports/soccer_epl/odds",
        params=params,
        timeout=20
    )

    response.raise_for_status()

    return response.json()


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
        key = point_key(point)

        result["home"][key] = None
        result["away"][key] = None

    return result


def empty_team_totals():
    result = {
        "home": {},
        "away": {}
    }

    for point in TEAM_TOTAL_POINTS:
        key = point_key(point)

        result["home"][key] = {
            "over": None,
            "under": None
        }

        result["away"][key] = {
            "over": None,
            "under": None
        }

    return result


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
            event.get("home_team")
        )

        odds_away = normalize_team(
            event.get("away_team")
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
        totals_data = empty_totals()

        found_something = False

        for market in bookmaker.get(
            "markets",
            []
        ):

            market_key = market.get("key")

            if market_key == "h2h":

                home_odd = None
                draw_odd = None
                away_odd = None

                for outcome in market.get(
                    "outcomes",
                    []
                ):

                    name = outcome.get("name")
                    price = outcome.get("price")

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
                        "home": home_odd,
                        "draw": draw_odd,
                        "away": away_odd
                    }

                    found_something = True

            elif market_key == "totals":

                for outcome in market.get(
                    "outcomes",
                    []
                ):

                    point = outcome.get("point")
                    name = outcome.get("name")
                    price = outcome.get("price")

                    if point is None:
                        continue

                    try:
                        point = float(point)
                    except Exception:
                        continue

                    if point not in TOTAL_POINTS:
                        continue

                    key = point_key(point)

                    if name == "Over":
                        totals_data[key]["over"] = price
                        found_something = True

                    elif name == "Under":
                        totals_data[key]["under"] = price
                        found_something = True

        if found_something:

            return {
                "h2h": h2h_data,
                "totals": totals_data,
                "bookmaker": bookmaker.get(
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
        outcome.get("name", "")
    )

    description = str(
        outcome.get("description", "")
    )

    combined = normalize_team(
        name + " " + description
    )

    if home_normalized in combined:
        return "home"

    if away_normalized in combined:
        return "away"

    return None


def detect_over_under(outcome):
    name = str(
        outcome.get("name", "")
    ).lower()

    description = str(
        outcome.get("description", "")
    ).lower()

    combined = (
        name
        + " "
        + description
    )

    if "over" in combined:
        return "over"

    if "under" in combined:
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
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": (
            "btts,"
            "double_chance,"
            "alternate_spreads,"
            "team_totals,"
            "alternate_team_totals"
        ),
        "oddsFormat": "decimal",
        "dateFormat": "iso"
    }

    try:
        response = requests.get(
            (
                f"{ODDS_API_URL}/sports/"
                f"soccer_epl/events/"
                f"{event_id}/odds"
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

            market_key = market.get("key")

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


            # =========================
            # ОБЕ ЗАБЬЮТ
            # =========================

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


            # =========================
            # ДВОЙНОЙ ШАНС
            # =========================

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

                    normalized_name = normalize_team(
                        name
                    )

                    if (
                        home_normalized
                        in normalized_name
                        and
                        "draw"
                        in normalized_name
                    ):
                        one_x = price

                    elif (
                        away_normalized
                        in normalized_name
                        and
                        "draw"
                        in normalized_name
                    ):
                        x_two = price

                    elif (
                        home_normalized
                        in normalized_name
                        and
                        away_normalized
                        in normalized_name
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


            # =========================
            # ФОРЫ
            # =========================

            elif market_key == "alternate_spreads":

                if result["handicaps"] is not None:
                    continue

                handicap_data = empty_handicaps()
                found_handicap = False

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

                    if (
                        point is None
                        or
                        price is None
                    ):
                        continue

                    try:
                        point = float(point)
                    except Exception:
                        continue

                    if point not in HANDICAP_POINTS:
                        continue

                    key = point_key(point)

                    if name == home_normalized:

                        handicap_data[
                            "home"
                        ][key] = price

                        found_handicap = True

                    elif name == away_normalized:

                        handicap_data[
                            "away"
                        ][key] = price

                        found_handicap = True

                if found_handicap:

                    result[
                        "handicaps"
                    ] = handicap_data

                    result[
                        "handicaps_bookmaker"
                    ] = bookmaker.get(
                        "title",
                        "Bookmaker"
                    )


            # =========================
            # ИНДИВИДУАЛЬНЫЕ ТОТАЛЫ
            # =========================

            elif market_key in (
                "team_totals",
                "alternate_team_totals"
            ):

                if result[
                    "team_totals"
                ] is None:

                    result[
                        "team_totals"
                    ] = empty_team_totals()

                found_team_total = False

                for outcome in market.get(
                    "outcomes",
                    []
                ):

                    point = outcome.get(
                        "point"
                    )

                    price = outcome.get(
                        "price"
                    )

                    if (
                        point is None
                        or
                        price is None
                    ):
                        continue

                    try:
                        point = float(point)
                    except Exception:
                        continue

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
                        team_side is None
                        or
                        over_under is None
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

                    found_team_total = True

                if (
                    found_team_total
                    and
                    result[
                        "team_totals_bookmaker"
                    ] is None
                ):

                    result[
                        "team_totals_bookmaker"
                    ] = bookmaker.get(
                        "title",
                        "Bookmaker"
                    )


    # Если рынок вообще не пришёл,
    # оставляем None

    team_totals = result[
        "team_totals"
    ]

    if team_totals:

        any_team_total = False

        for side in (
            "home",
            "away"
        ):

            for line in team_totals[
                side
            ].values():

                if (
                    line.get("over")
                    is not None
                    or
                    line.get("under")
                    is not None
                ):

                    any_team_total = True

        if not any_team_total:

            result[
                "team_totals"
            ] = None

            result[
                "team_totals_bookmaker"
            ] = None


    return result


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
            cache_data["response"]
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

        odds_events = get_featured_odds()

    except requests.exceptions.HTTPError as error:

        response = error.response

        try:
            api_error = response.json()

        except Exception:
            api_error = response.text

        return jsonify({
            "success": False,
            "status_code":
                response.status_code,
            "api_error":
                api_error
        }), response.status_code

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
                odds_event.get("id"),
                home_name,
                away_name
            )


        match = {

            "fixture_id":
                item.get("id"),

            "date":
                item.get("utcDate"),

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

                    field_name = (
                        "total_"
                        + key.replace(
                            ".",
                            "_"
                        )
                    )

                    match[
                        field_name
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

            match[
                "btts"
            ] = extra_markets.get(
                "btts"
            )

            match[
                "btts_bookmaker"
            ] = extra_markets.get(
                "btts_bookmaker"
            )

            match[
                "double_chance"
            ] = extra_markets.get(
                "double_chance"
            )

            match[
                "double_chance_bookmaker"
            ] = extra_markets.get(
                "double_chance_bookmaker"
            )

            match[
                "handicaps"
            ] = extra_markets.get(
                "handicaps"
            )

            match[
                "handicaps_bookmaker"
            ] = extra_markets.get(
                "handicaps_bookmaker"
            )

            match[
                "team_totals"
            ] = extra_markets.get(
                "team_totals"
            )

            match[
                "team_totals_bookmaker"
            ] = extra_markets.get(
                "team_totals_bookmaker"
            )

            match[
                "available_extra_markets"
            ] = extra_markets.get(
                "available_extra_markets",
                []
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
            len(matches_list),

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
