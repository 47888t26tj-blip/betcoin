import os
import requests

from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
API_URL = "https://api.football-data.org/v4"


@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "BetCoin server is working"
    })


@app.route("/api/matches")
def matches():
    if not TOKEN:
        return jsonify({
            "success": False,
            "error": "FOOTBALL_DATA_TOKEN not found"
        }), 500

    headers = {
        "X-Auth-Token": TOKEN
    }

    today = datetime.now(timezone.utc).date()
    date_to = today + timedelta(days=14)

    params = {
        "dateFrom": today.isoformat(),
        "dateTo": date_to.isoformat()
    }

    try:
        response = requests.get(
            f"{API_URL}/competitions/PL/matches",
            headers=headers,
            params=params,
            timeout=20
        )

        data = response.json()

    except Exception as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500

    if response.status_code != 200:
        return jsonify({
            "success": False,
            "status_code": response.status_code,
            "api_response": data
        }), response.status_code

    matches_list = []

    for item in data.get("matches", []):
        home_team = item.get("homeTeam", {})
        away_team = item.get("awayTeam", {})
        competition = item.get("competition", {})

        matches_list.append({
            "fixture_id": item.get("id"),
            "date": item.get("utcDate"),
            "league": competition.get("name", "Premier League"),
            "country": "England",
            "home": home_team.get("name", "Unknown"),
            "away": away_team.get("name", "Unknown"),
            "home_logo": home_team.get("crest", ""),
            "away_logo": away_team.get("crest", ""),
            "status": item.get("status", "SCHEDULED")
        })

    return jsonify({
        "success": True,
        "date_from": today.isoformat(),
        "date_to": date_to.isoformat(),
        "count": len(matches_list),
        "matches": matches_list
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port
    )
