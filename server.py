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

    headers = {
        "x-apisports-key": API_KEY
    }

    params = {
        "league": 39,
        "season": 2024,
        "from": "2024-10-01",
        "to": "2024-10-08",
        "timezone": "Europe/Moscow"
    }

    try:
        response = requests.get(
            f"{API_URL}/fixtures",
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
        "matches": matches_list,
        "api_results": data.get("results", 0),
        "api_errors": data.get("errors", []),
        "api_parameters": data.get("parameters", {})
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
