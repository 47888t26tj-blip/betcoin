import os

from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "BetCoin server is working"
    })


@app.route("/api/test")
def test():
    return jsonify({
        "success": True,
        "message": "Связь с сервером работает"
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
