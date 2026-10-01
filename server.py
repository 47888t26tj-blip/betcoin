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

TOTAL_POINTS = [1.5, 2.5, 3.5, 4.5]

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

    name = name.lower().strip()

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


def get_football_matches():
    headers = {
        "X-Auth-Token": FOOTBALL_TOKEN
    }

    today = datetime.now(timezone.utc).date()
    date_to = today + timedelta(days=14)

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

    return response.json(), today, date_to


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
    return {
        "1.5": {"over": None, "under": None},
        "2.5": {"over": None, "under": None},
        "3.5": {"over": None, "under": None},
        "4.5": {"over": None, "under": None}
    }


def find_odds_event(home_team, away_team, odds_events):
    home_normalized = normalize_team(home_team)
    away_normalized = normalize_team(away_team)

    for event in odds_events:
        odds_home = normalize_team(event.get("home_team"))
        odds_away = normalize_team(event.get("away_team"))

        if (
            home_normalized == odds_home
            and away_normalized == odds_away
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

    for bookmaker in event.get("bookmakers", []):
        h2h_data = None
        totals_data = empty_totals()

        found_something = False

        for market in bookmaker.get("markets", []):

            if market.get("key") == "h2h":
                home_odd = None
                draw_odd = None
                away_odd = None

                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    price = outcome.get("price")

                    if name == "Draw":
                        draw_odd = price

                    elif normalize_team(name) == home_normalized:
                        home_odd = price

                    elif normalize_team(name) == away_normalized:
                        away_odd = price

                if (
                    home_odd is not None
                    and draw_odd is not None
                    and away_odd is not None
                ):
                    h2h_data = {
                        "home": home_odd,
                        "draw": draw_odd,
                        "away": away_odd
                    }

                    found_something = True

            elif market.get("key") == "totals":
                for outcome in market.get("outcomes", []):
                    point = outcome.get("point")
                    name = outcome.get("name")
                    price = outcome.get("price")

                    if point not in TOTAL_POINTS:
                        continue

                    key = str(point)

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


def get_extra_markets(event_id, home_team, away_team):
    if not event_id:
        return None

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "btts,double_chance",
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

    home_normalized = normalize_team(home_team)
    away_normalized = normalize_team(away_team)

    result = {
        "btts": None,
        "double_chance": None,
        "btts_bookmaker": None,
        "double_chance_bookmaker": None
    }

    for bookmaker in data.get("bookmakers", []):

        for market in bookmaker.get("markets", []):

            # ОЗ
            if market.get("key") == "btts":
                yes_odd = None
                no_odd = None

                for outcome in market.get("outcomes", []):
                    name = str(
                        outcome.get("name", "")
                    ).lower()

                    price = outcome.get("price")

                    if name == "yes":
                        yes_odd = price

                    elif name == "no":
                        no_odd = price

                if (
                    yes_odd is not None
                    and no_odd is not None
                    and result["btts"] is None
                ):
                    result["btts"] = {
                        "yes": yes_odd,
                        "no": no_odd
                    }

                    result["btts_bookmaker"] = (
                        bookmaker.get(
                            "title",
                            "Bookmaker"
                        )
                    )

            # Двойной шанс
            elif market.get("key") == "double_chance":

                one_x = None
                one_two = None
                x_two = None

                for outcome in market.get("outcomes", []):

                    name = str(
                        outcome.get("name", "")
                    )

                    price = outcome.get("price")

                    normalized_name = normalize_team(name)

                    # 1X = хозяева или ничья
                    if (
                        normalize_team(home_team) in normalized_name
                        and "draw" in normalized_name
                    ):
                        one_x = price

                    # X2 = гости или ничья
                    elif (
                        normalize_team(away_team) in normalized_name
                        and "draw" in normalized_name
                    ):
                        x_two = price

                    # 12 = хозяева или гости
                    elif (
                        normalize_team(home_team) in normalized_name
                        and normalize_team(away_team) in normalized_name
                    ):
                        one_two = price

                if (
                    result["double_chance"] is None
                    and (
                        one_x is not None
                        or one_two is not None
                        or x_two is not None
                    )
                ):
                    result["double_chance"] = {
                        "1x": one_x,
                        "12": one_two,
                        "x2": x_two
                    }

                    result["double_chance_bookmaker"] = (
                        bookmaker.get(
                            "title",
                            "Bookmaker"
                        )
                    )

    return result


@app.route("/api/matches")
def matches():

    if (
        cache_data["response"] is not None
        and time.time() - cache_data["time"] < CACHE_SECONDS
    ):
        return jsonify(
            cache_data["response"]
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
        football_data, today, date_to = get_football_matches()
        odds_events = get_featured_odds()

    except requests.exceptions.HTTPError as error:
        response = error.response

        try:
            api_error = response.json()
        except Exception:
            api_error = response.text

        return jsonify({
            "success": False,
            "status_code": response.status_code,
            "api_error": api_error
        }), response.status_code

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    matches_list = []

    for item in football_data.get("matches", []):

        home_team = item.get("homeTeam", {})
        away_team = item.get("awayTeam", {})
        competition = item.get("competition", {})

        home_name = home_team.get("name")
        away_name = away_team.get("name")

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
            "fixture_id": item.get("id"),
            "date": item.get("utcDate"),

            "league": competition.get(
                "name",
                "Premier League"
            ),

            "country": "England",

            "home": home_name or "Unknown",
            "away": away_name or "Unknown",

            "home_logo": home_team.get(
                "crest",
                ""
            ),

            "away_logo": away_team.get(
                "crest",
                ""
            ),

            "status": item.get(
                "status",
                "SCHEDULED"
            ),

            "bookmaker": None,
            "odds": None,

            "total_1_5": None,
            "total_2_5": None,
            "total_3_5": None,
            "total_4_5": None,

            "btts": None,
            "btts_bookmaker": None,

            "double_chance": None,
            "double_chance_bookmaker": None
        }

        if markets:
            match["bookmaker"] = markets.get(
                "bookmaker"
            )

            match["odds"] = markets.get(
                "h2h"
            )

            totals = markets.get(
                "totals",
                {}
            )

            for point in TOTAL_POINTS:
                key = str(point)

                total = totals.get(key)

                if (
                    total
                    and (
                        total.get("over") is not None
                        or total.get("under") is not None
                    )
                ):
                    field_name = (
                        "total_"
                        + key.replace(".", "_")
                    )

                    match[field_name] = {
                        "point": point,
                        "over": total.get("over"),
                        "under": total.get("under")
                    }

        if extra_markets:

            match["btts"] = extra_markets.get(
                "btts"
            )

            match["btts_bookmaker"] = (
                extra_markets.get(
                    "btts_bookmaker"
                )
            )

            match["double_chance"] = (
                extra_markets.get(
                    "double_chance"
                )
            )

            match[
                "double_chance_bookmaker"
            ] = extra_markets.get(
                "double_chance_bookmaker"
            )

        matches_list.append(match)

    result = {
        "success": True,
        "date_from": today.isoformat(),
        "date_to": date_to.isoformat(),
        "count": len(matches_list),
        "matches": matches_list
    }

    cache_data["time"] = time.time()
    cache_data["response"] = result

    return jsonify(result)


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
