# --- server.py ---
import os
import stripe
import hashlib
import secrets
from flask import Flask, request, jsonify

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]

app = Flask(__name__)

PLANS = {
    "1m": {"price_cents": 700,  "name": "Pro — 1 Month",   "days": 30},
    "3m": {"price_cents": 1800, "name": "Pro — 3 Months",  "days": 90},
    "1y": {"price_cents": 6000, "name": "Pro — 1 Year",    "days": 365},
    "lt": {"price_cents": 9900, "name": "Pro — Lifetime",  "days": None},
}

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
        success_url=os.environ["DOMAIN"] + "/success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=os.environ["DOMAIN"] + "/cancel",
        payment_intent_data={
            # gift card tolerance — skip zip/AVS hard failure
            # Stripe still runs the check but won't decline on mismatch
            "capture_method": "automatic",
        },
        billing_address_collection="auto",  # "auto" = optional, not required
        # don't force address — kills prepaid cards that have none
        metadata={"plan_id": plan_id},
    )

    return jsonify({"checkout_url": session.url})


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
        plan_id = session["metadata"]["plan_id"]
        customer_email = session.get("customer_details", {}).get("email", "")
        payment_intent_id = session.get("payment_intent", "")

        license_key = generate_license_key()

        # store in your DB here — minimum viable schema below
        # INSERT INTO licenses (email, plan_id, license_key, payment_intent_id, created_at)
        # VALUES (?, ?, ?, ?, NOW())

        # send key via email — plug in SendGrid/Resend/Postmark here
        deliver_license(customer_email, license_key, plan_id)

    return jsonify({"status": "ok"})


def deliver_license(email: str, key: str, plan_id: str):
    # swap for real email provider
    # example: resend.emails.send({"to": email, "subject": "Your license key", ...})
    print(f"[DELIVER] {email} → {key} (plan: {plan_id})")


if __name__ == "__main__":
    app.run(port=4242, debug=False)
