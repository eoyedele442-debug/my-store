import os
import secrets
import stripe
from flask import Flask, request, jsonify
from flask_cors import CORS

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
DOMAIN = os.environ.get("DOMAIN", "https://eoyedele442-debug.github.io/my-store")

app = Flask(__name__)
CORS(app)

PLANS = {
    "1m": {"price_cents": 700,  "name": "Pro — 1 Month"},
    "3m": {"price_cents": 1800, "name": "Pro — 3 Months"},
    "1y": {"price_cents": 6000, "name": "Pro — 1 Year"},
    "lt": {"price_cents": 11300, "name": "Pro — Lifetime"},
}

# in-memory store: session_id → license_key
# replace with a real DB when you're ready
license_store = {}

def generate_license_key() -> str:
    raw = secrets.token_bytes(20)
    hex_key = raw.hex().upper()
    return "-".join(hex_key[i:i+5] for i in range(0, 20, 5))


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    data = request.get_json()
    plan_id = data.get("plan_id")

    if plan_id not in PLANS:
        return jsonify({"error": "Invalid plan"}), 400

    plan = PLANS[plan_id]

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": plan["name"]},
                "unit_amount": plan["price_cents"],
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=DOMAIN + "/index.html?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=DOMAIN + "/index.html?cancelled=1",
        billing_address_collection="auto",
        metadata={"plan_id": plan_id},
    )

    return jsonify({"checkout_url": session.url})


@app.route("/session-key", methods=["GET"])
def session_key():
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    # check in-memory store first
    if session_id in license_store:
        return jsonify({"license_key": license_store[session_id]})

    # verify with Stripe that payment actually completed
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.InvalidRequestError:
        return jsonify({"error": "Invalid session"}), 400

    if session.payment_status != "paid":
        return jsonify({"error": "Payment not completed"}), 402

    # generate and cache the key
    key = generate_license_key()
    license_store[session_id] = key
    return jsonify({"license_key": key})


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        session_id = session["id"]
        if session_id not in license_store:
            license_store[session_id] = generate_license_key()

    return jsonify({"status": "ok"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "running"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4242))
    app.run(host="0.0.0.0", port=port)
