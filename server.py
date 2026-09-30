import os
import re
import requests

from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

FOOTBALL_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "").strip()

FOOTBALL_API_URL = "https://api.football-data.org/v4"
ODDS_API_URL = "https://api.the-odds-api.com/v4"


@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "BetCoin server is working"
    })


def normalize_team(name):
    if not name:
        return ""

    name = name.lower()

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


def get_real_odds():
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
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


def find_odds(home_team, away_team, odds_events):
    home_normalized = normalize_team(home_team)
    away_normalized = normalize_team(away_team)

    for event in odds_events:
        odds_home = normalize_team(event.get("home_team"))
        odds_away = normalize_team(event.get("away_team"))

        if (
            home_normalized == odds_home
            and away_normalized == odds_away
        ):
            bookmakers = event.get("bookmakers", [])

            for bookmaker in bookmakers:
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "h2h":
                        continue

                    home_odd = None
                    draw_odd = None
                    away_odd = None

                    for outcome in market.get("outcomes", []):
                        outcome_name = normalize_team(
                            outcome.get("name")
                        )

                        price = outcome.get("price")

                        if outcome.get("name") == "Draw":
                            draw_odd = price

                        elif outcome_name == home_normalized:
                            home_odd = price

                        elif outcome_name == away_normalized:
                            away_odd = price

                    if (
                        home_odd is not None
                        and draw_odd is not None
                        and away_odd is not None
                    ):
                        return {
                            "home": home_odd,
                            "draw": draw_odd,
                            "away": away_odd,
                            "bookmaker": bookmaker.get(
                                "title",
                                "Bookmaker"
                            ),
                            "last_update": market.get(
                                "last_update",
                                bookmaker.get("last_update")
                            )
                        }

    return None


@app.route("/api/matches")
def matches():
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
        odds_events = get_real_odds()

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

        real_odds = find_odds(
            home_team.get("name"),
            away_team.get("name"),
            odds_events
        )

        match = {
            "fixture_id": item.get("id"),
            "date": item.get("utcDate"),
            "league": competition.get(
                "name",
                "Premier League"
            ),
            "country": "England",
            "home": home_team.get(
                "name",
                "Unknown"
            ),
            "away": away_team.get(
                "name",
                "Unknown"
            ),
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
            "odds_available": real_odds is not None
        }

        if real_odds:
            match["odds"] = {
                "home": real_odds["home"],
                "draw": real_odds["draw"],
                "away": real_odds["away"]
            }

            match["bookmaker"] = real_odds["bookmaker"]
            match["odds_updated"] = real_odds["last_update"]

        matches_list.append(match)

    return jsonify({
        "success": True,
        "date_from": today.isoformat(),
        "date_to": date_to.isoformat(),
        "count": len(matches_list),
        "matches_with_odds": sum(
            1
            for match in matches_list
            if match["odds_available"]
        ),
        "matches": matches_list
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
