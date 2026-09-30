import os
import requests

from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

API_KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
API_URL = "https://v3.football.api-sports.io"


@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "BetCoin server is working"
    })



@app.route("/api/matches")
def matches():
    if not API_KEY:
        return jsonify({
            "success": False,
            "error": "API_FOOTBALL_KEY not found"
        }), 500

    from datetime import datetime, timedelta, timezone

    headers = {
        "x-apisports-key": API_KEY
    }

    today = datetime.now(timezone.utc).date()
    week_later = today + timedelta(days=7)

    params = {
        "from": today.isoformat(),
        "to": week_later.isoformat(),
        "timezone": "Europe/Moscow"
    }

    response = requests.get(
        f"{API_URL}/fixtures",
        headers=headers,
        params=params,
        timeout=20
    )

    data = response.json()

    matches_list = []

    for item in data.get("response", []):
        matches_list.append({
            "fixture_id": item["fixture"]["id"],
            "date": item["fixture"]["date"],
            "league": item["league"]["name"],
            "country": item["league"]["country"],
            "home": item["teams"]["home"]["name"],
            "away": item["teams"]["away"]["name"],
            "home_logo": item["teams"]["home"]["logo"],
            "away_logo": item["teams"]["away"]["logo"],
            "status": item["fixture"]["status"]["short"]
        })

    return jsonify({
        "success": True,
        "count": len(matches_list),
        "matches": matches_list
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
