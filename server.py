achievements = get_achievements(telegram_id)
        current = next((item for item in achievements if item["key"] == achievement_key), None)
        if not current:
            return jsonify({"success": False, "error": "Достижение не найдено"}), 404
        if not current["completed"]:
            return jsonify({"success": False, "error": "Достижение ещё не выполнено"}), 400
        if current["claimed"]:
            return jsonify({"success": False, "error": "Награда уже получена"}), 400
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO achievement_claims (telegram_id, achievement_key)
            VALUES (%s, %s)
            ON CONFLICT (telegram_id, achievement_key) DO NOTHING
        """, (telegram_id, achievement_key))
        if cur.rowcount != 1:
            conn.rollback(); cur.close(); conn.close(); return jsonify({"success": False, "error": "Награда уже получена"}), 400
        reward = int(achievement["reward"])
        cur.execute("UPDATE users SET balance = balance + %s, updated_at = NOW() WHERE telegram_id = %s RETURNING balance", (reward, telegram_id))
        final_balance = int(cur.fetchone()[0]); conn.commit(); cur.close(); conn.close()
        achievements = get_achievements(telegram_id); leaderboard_data = get_leaderboard(telegram_id, 50)
        return jsonify({"success": True, "achievement_key": achievement_key, "reward": reward, "balance": final_balance, "achievements": achievements, "my_rank": leaderboard_data["my_rank"]})
    except Exception as error:
        return jsonify({"success": False, "error": str(error)}), 500


@app.route("/api/settle", methods=["POST"])
def settle():
    telegram_user, error = require_telegram_user()
    if error: return error
    try:
        user = get_or_create_user(telegram_user); telegram_id = user["telegram_id"]
        settle_user_bets(telegram_id); settle_user_parlays(telegram_id)
        user = get_user_data(telegram_id); player_xp = xp_info(user.get("xp", 0))
        tasks = get_daily_tasks(telegram_id, True); achievements = get_achievements(telegram_id); leaderboard_data = get_leaderboard(telegram_id, 50); stats = get_profile_stats(telegram_id)
        return jsonify({
            "success": True, "balance": int(user["balance"]),
            "xp": player_xp["xp"], "level": player_xp["level"], "league": player_xp["league"],
            "current_level_xp": player_xp["current_level_xp"], "xp_to_next_level": player_xp["xp_to_next_level"],
            "bets": get_user_bets(telegram_id), "parlays": get_user_parlays(telegram_id),
            "tasks": tasks, "achievements": achievements, "stats": stats, "my_rank": leaderboard_data["my_rank"],
        })
    except Exception as error:
        return jsonify({"success": False, "error": str(error)}), 500


@app.route("/api/match/<int:match_id>")
def single_match(match_id):
    if not FOOTBALL_TOKEN:
        return jsonify({"success": False, "error": "FOOTBALL_DATA_TOKEN not found"}), 500
    try:
        result = get_single_match(match_id)
        return jsonify({"success": True, **result})
    except Exception as error:
        return jsonify({"success": False, "error": str(error)}), 500


@app.route("/api/matches")
def matches():
    if cache_data["response"] is not None and time.time() - cache_data["time"] < CACHE_SECONDS:
        return jsonify(cache_data["response"])
    if not FOOTBALL_TOKEN:
        return jsonify({"success": False, "error": "FOOTBALL_DATA_TOKEN not found"}), 500
    if not ODDS_API_KEY:
        return jsonify({"success": False, "error": "ODDS_API_KEY not found"}), 500
    try:
        football_data, today, date_to = get_football_matches(); odds_events = get_featured_odds()
    except Exception as error:
        return jsonify({"success": False, "error": str(error)}), 500

    matches_list = []
    for item in football_data.get("matches", []):
        home_team = item.get("homeTeam", {}); away_team = item.get("awayTeam", {}); competition = item.get("competition", {})
        home_name = home_team.get("name"); away_name = away_team.get("name")
        odds_event = find_odds_event(home_name, away_name, odds_events)
        markets = get_main_markets(odds_event)
        extra_markets = get_extra_markets(odds_event.get("id"), home_name, away_name) if odds_event else None
        match = {
            "fixture_id": item.get("id"), "date": item.get("utcDate"), "league": competition.get("name", "Premier League"), "country": "England",
            "home": home_name or "Unknown", "away": away_name or "Unknown", "home_logo": home_team.get("crest", ""), "away_logo": away_team.get("crest", ""),
            "status": item.get("status", "SCHEDULED"), "bookmaker": None, "odds": None,
            "total_1_5": None, "total_2_5": None, "total_3_5": None, "total_4_5": None,
            "btts": None, "btts_bookmaker": None, "double_chance": None, "double_chance_bookmaker": None,
            "handicaps": None, "handicaps_bookmaker": None, "team_totals": None, "team_totals_bookmaker": None,
            "available_extra_markets": [],
        }
        if markets:
            match["bookmaker"] = markets.get("bookmaker"); match["odds"] = markets.get("h2h"); totals = markets.get("totals", {})
            for point in TOTAL_POINTS:
                key = point_key(point); total = totals.get(key)
                if total and (total.get("over") is not None or total.get("under") is not None):
                    match["total_" + key.replace(".", "_")] = {"point": point, "over": total.get("over"), "under": total.get("under")}
        if extra_markets:
            for key in ("btts", "btts_bookmaker", "double_chance", "double_chance_bookmaker", "handicaps", "handicaps_bookmaker", "team_totals", "team_totals_bookmaker", "available_extra_markets"):
                match[key] = extra_markets.get(key)
        matches_list.append(match)

    result = {"success": True, "date_from": today.isoformat(), "date_to": date_to.isoformat(), "count": len(matches_list), "matches": matches_list}
    cache_data["time"] = time.time(); cache_data["response"] = result
    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
