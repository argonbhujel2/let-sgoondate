import os
import uuid
from datetime import datetime, date
from functools import wraps
from io import BytesIO

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify
)
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader

from models import db, DateRequest, Setting

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = (os.getenv("SECRET_KEY") or "dev-secret-change-me").strip()

# --- Database URL (Neon / Postgres / SQLite) ---
_db_url = os.getenv("DATABASE_URL", "sqlite:///dates.db")
# Vercel + Neon often give postgres:// or postgresql://
# Force psycopg2 driver which we ship in requirements
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif _db_url.startswith("postgresql://") and "+psycopg" not in _db_url:
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB max upload

# On Vercel the filesystem is read-only except /tmp
IS_VERCEL = os.getenv("VERCEL") == "1" or os.getenv("VERCEL_ENV") is not None
if IS_VERCEL:
    app.instance_path = "/tmp/flask_instance"

# Mail config
app.config["MAIL_SERVER"] = (os.getenv("MAIL_SERVER") or "smtp.gmail.com").strip()
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT") or 587)
app.config["MAIL_USE_TLS"] = (os.getenv("MAIL_USE_TLS") or "true").lower() == "true"
app.config["MAIL_USERNAME"] = (os.getenv("MAIL_USERNAME") or "").strip() or None
app.config["MAIL_PASSWORD"] = (os.getenv("MAIL_PASSWORD") or "").strip() or None
app.config["MAIL_DEFAULT_SENDER"] = app.config["MAIL_USERNAME"]

# Payment config
PAYMENT_AMOUNT = int(os.getenv("PAYMENT_AMOUNT") or 1000)
PAYMENT_RECIPIENT = (os.getenv("PAYMENT_RECIPIENT") or "Date Host").strip()
PAYMENT_QR_PATH = (os.getenv("PAYMENT_QR_PATH") or "static/images/payment-qr.png").strip()
OWNER_EMAIL = (os.getenv("OWNER_EMAIL") or "").strip() or None

# Cloudinary config
CLOUDINARY_CLOUD_NAME = (os.getenv("CLOUDINARY_CLOUD_NAME") or "").strip() or None
CLOUDINARY_API_KEY = (os.getenv("CLOUDINARY_API_KEY") or "").strip() or None
CLOUDINARY_API_SECRET = (os.getenv("CLOUDINARY_API_SECRET") or "").strip() or None
CLOUDINARY_ENABLED = bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)

if CLOUDINARY_ENABLED:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True,
    )

# Local upload fallback (used only if Cloudinary is not configured)
# On Vercel use /tmp because the rest of the FS is read-only
if IS_VERCEL:
    UPLOAD_FOLDER = "/tmp/uploads"
else:
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except OSError:
    pass  # read-only FS – Cloudinary should be used instead
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

db.init_app(app)
mail = Mail(app)
csrf = CSRFProtect(app)

# Simple in-memory rate limiting
_rate_limit_store = {}


def rate_limit(max_requests=10, window=60):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = request.remote_addr or "unknown"
            now = datetime.utcnow().timestamp()
            key = f"{ip}:{f.__name__}"
            if key not in _rate_limit_store:
                _rate_limit_store[key] = []
            _rate_limit_store[key] = [t for t in _rate_limit_store[key] if now - t < window]
            if len(_rate_limit_store[key]) >= max_requests:
                flash("Too many requests. Please wait a moment 💕", "error")
                return redirect(request.referrer or url_for("index"))
            _rate_limit_store[key].append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def upload_to_cloudinary(file_storage, folder="date-invitation"):
    """Upload a Werkzeug FileStorage to Cloudinary. Returns secure_url or None."""
    if not CLOUDINARY_ENABLED:
        app.logger.warning("Cloudinary not configured")
        return None
    try:
        # Reset stream position if needed
        if hasattr(file_storage, "stream"):
            file_storage.stream.seek(0)
        result = cloudinary.uploader.upload(
            file_storage,
            folder=folder,
            resource_type="auto",
            overwrite=False,
            unique_filename=True,
        )
        url = result.get("secure_url")
        app.logger.info(f"Cloudinary upload OK: {url}")
        return url
    except Exception as e:
        app.logger.error(f"Cloudinary upload failed: {e}")
        return None


def save_local_file(file_storage, prefix=""):
    """Fallback: save to local static/uploads. Returns relative path or None."""
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    filename = f"{prefix}{uuid.uuid4().hex[:10]}.{ext}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file_storage.save(path)
    return f"uploads/{filename}"


def get_payment_qr_url():
    """Prefer DB setting (Cloudinary URL) → env → local static."""
    url = Setting.get("payment_qr_url")
    if url:
        return url
    # env can also hold a full Cloudinary URL
    env_url = os.getenv("PAYMENT_QR_URL")
    if env_url:
        return env_url
    # local fallback
    return url_for("static", filename=PAYMENT_QR_PATH.replace("static/", ""))


def send_email(subject, body, html_body=None):
    if not OWNER_EMAIL:
        app.logger.warning("OWNER_EMAIL not set – skipping notification")
        return False
    if not app.config["MAIL_USERNAME"] or not app.config["MAIL_PASSWORD"]:
        app.logger.warning("MAIL_USERNAME or MAIL_PASSWORD not set – skipping notification")
        return False
    try:
        msg = Message(
            subject=subject,
            recipients=[OWNER_EMAIL],
            body=body,
            html=html_body,
            sender=app.config["MAIL_DEFAULT_SENDER"],
        )
        mail.send(msg)
        app.logger.info(f"Email sent: {subject} → {OWNER_EMAIL}")
        return True
    except Exception as e:
        app.logger.error(f"Failed to send email: {e}")
        return False


# ---------- Routes ----------

@app.route("/")
def index():
    session.clear()
    return render_template("index.html")


@app.route("/surprise")
def surprise():
    if not session.get("said_yes"):
        return redirect(url_for("index"))
    return render_template("surprise.html")


@app.route("/choose-date", methods=["GET", "POST"])
@rate_limit(max_requests=8, window=120)
def choose_date():
    if not session.get("said_yes"):
        return redirect(url_for("index"))

    if request.method == "POST":
        selected_date_str = request.form.get("selected_date", "").strip()
        selected_time = request.form.get("selected_time", "").strip()
        location = request.form.get("location", "").strip()
        personal_message = request.form.get("personal_message", "").strip()

        errors = []
        if not selected_date_str:
            errors.append("Please pick a date 📅")
        if not selected_time:
            errors.append("Please choose a time ⏰")

        try:
            selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
            if selected_date < date.today():
                errors.append("That date is already in the past 😢 Pick a future day!")
        except ValueError:
            errors.append("Invalid date format")
            selected_date = None

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "choose_date.html",
                selected_date=selected_date_str,
                selected_time=selected_time,
                location=location,
                personal_message=personal_message,
            )

        date_req = DateRequest(
            selected_date=selected_date,
            selected_time=selected_time,
            location=location or None,
            personal_message=personal_message or None,
            payment_status="pending",
        )
        db.session.add(date_req)
        db.session.commit()

        session["date_request_id"] = date_req.id
        session["selected_date"] = selected_date.isoformat()
        session["selected_time"] = selected_time
        session["location"] = location
        session["personal_message"] = personal_message

        body = f"""
💕 New Date Request!

Request ID: {date_req.id}
Date: {selected_date.strftime('%A, %B %d, %Y')}
Time: {selected_time}
Location: {location or 'Not specified'}
Message: {personal_message or 'None'}

Payment Amount: NPR {PAYMENT_AMOUNT}
Payment Status: Pending
"""
        html = f"""
        <h2>💕 New Date Request!</h2>
        <p><strong>Request ID:</strong> {date_req.id}</p>
        <p><strong>Date:</strong> {selected_date.strftime('%A, %B %d, %Y')}</p>
        <p><strong>Time:</strong> {selected_time}</p>
        <p><strong>Location:</strong> {location or 'Not specified'}</p>
        <p><strong>Message:</strong> {personal_message or 'None'}</p>
        <p><strong>Payment:</strong> NPR {PAYMENT_AMOUNT} — Pending</p>
        """
        sent = send_email("💕 New Date Request!", body, html)
        if not sent:
            flash("Date saved, but we couldn't send the notification email.", "warning")

        return redirect(url_for("payment"))

    return render_template("choose_date.html")


@app.route("/payment")
def payment():
    if not session.get("date_request_id"):
        return redirect(url_for("index"))
    return render_template(
        "payment.html",
        amount=PAYMENT_AMOUNT,
        recipient=PAYMENT_RECIPIENT,
    )


@app.route("/payment-qr", methods=["GET", "POST"])
@rate_limit(max_requests=10, window=120)
def payment_qr():
    if not session.get("date_request_id"):
        return redirect(url_for("index"))

    date_req = DateRequest.query.get(session["date_request_id"])
    if not date_req:
        flash("Session expired. Please start over 💕", "error")
        return redirect(url_for("index"))

    qr_url = get_payment_qr_url()

    if request.method == "POST":
        transaction_id = request.form.get("transaction_id", "").strip()
        confirmed = request.form.get("payment_confirmed") == "on"
        proof = request.files.get("proof")

        if not confirmed:
            flash("Please confirm that you have completed the payment 💗", "error")
            return render_template(
                "payment_qr.html",
                amount=PAYMENT_AMOUNT,
                recipient=PAYMENT_RECIPIENT,
                qr_url=qr_url,
            )

        if not transaction_id and not (proof and proof.filename):
            flash("Please provide a transaction ID or upload payment proof 📸", "error")
            return render_template(
                "payment_qr.html",
                amount=PAYMENT_AMOUNT,
                recipient=PAYMENT_RECIPIENT,
                qr_url=qr_url,
            )

        proof_url = None
        proof_filename = None

        if proof and proof.filename:
            if not allowed_file(proof.filename):
                flash("Invalid file type. Please upload an image or PDF 🖼️", "error")
                return render_template(
                    "payment_qr.html",
                    amount=PAYMENT_AMOUNT,
                    recipient=PAYMENT_RECIPIENT,
                    qr_url=qr_url,
                )

            # Prefer Cloudinary (required on Vercel)
            if CLOUDINARY_ENABLED:
                proof_url = upload_to_cloudinary(proof, folder="date-invitation/proofs")
                if not proof_url:
                    flash("Upload failed. Check Cloudinary settings 💔", "error")
                    return render_template(
                        "payment_qr.html",
                        amount=PAYMENT_AMOUNT,
                        recipient=PAYMENT_RECIPIENT,
                        qr_url=qr_url,
                    )
            else:
                if IS_VERCEL:
                    flash("Cloudinary required on Vercel for file uploads. Set CLOUDINARY_* env vars.", "error")
                    return render_template(
                        "payment_qr.html",
                        amount=PAYMENT_AMOUNT,
                        recipient=PAYMENT_RECIPIENT,
                        qr_url=qr_url,
                    )
                # Local fallback
                proof_filename = save_local_file(proof, prefix=f"{date_req.id}_")
                if proof_filename:
                    proof_url = url_for("static", filename=proof_filename, _external=True)

        date_req.transaction_id = transaction_id or None
        date_req.proof_filename = proof_filename
        date_req.proof_url = proof_url
        date_req.payment_status = "proof_submitted"
        db.session.commit()

        session["payment_status"] = "proof_submitted"

        body = f"""
💸 Payment Proof Submitted — Verification Required

Request ID: {date_req.id}
Date: {date_req.selected_date.strftime('%A, %B %d, %Y')}
Time: {date_req.selected_time}
Location: {date_req.location or 'Not specified'}

Transaction ID: {transaction_id or 'Not provided'}
Proof URL: {proof_url or 'None'}
Amount: NPR {PAYMENT_AMOUNT}

Please verify the payment.
"""
        html = f"""
        <h2>💸 Payment Proof Submitted</h2>
        <p><strong>Request ID:</strong> {date_req.id}</p>
        <p><strong>Date:</strong> {date_req.selected_date.strftime('%A, %B %d, %Y')} at {date_req.selected_time}</p>
        <p><strong>Transaction ID:</strong> {transaction_id or 'Not provided'}</p>
        <p><strong>Proof:</strong> {f'<a href="{proof_url}">{proof_url}</a>' if proof_url else 'None'}</p>
        <p><strong>Amount:</strong> NPR {PAYMENT_AMOUNT}</p>
        <p style="color:#e11d48;"><strong>Action required:</strong> Verify this payment.</p>
        """
        send_email("💸 Payment Proof Submitted — Verification Required", body, html)

        return redirect(url_for("awaiting_verification"))

    return render_template(
        "payment_qr.html",
        amount=PAYMENT_AMOUNT,
        recipient=PAYMENT_RECIPIENT,
        qr_url=qr_url,
    )


@app.route("/awaiting-verification")
def awaiting_verification():
    if not session.get("date_request_id"):
        return redirect(url_for("index"))
    date_req = DateRequest.query.get(session["date_request_id"])
    if not date_req:
        return redirect(url_for("index"))

    if date_req.payment_status == "verified":
        return redirect(url_for("confirmation"))

    return render_template(
        "awaiting.html",
        date_req=date_req,
        amount=PAYMENT_AMOUNT,
    )


@app.route("/confirmation")
def confirmation():
    if not session.get("date_request_id"):
        return redirect(url_for("index"))
    date_req = DateRequest.query.get(session["date_request_id"])
    if not date_req or date_req.payment_status != "verified":
        return redirect(url_for("awaiting_verification"))

    return render_template(
        "confirmation.html",
        date_req=date_req,
        amount=PAYMENT_AMOUNT,
    )


@app.route("/verify/<request_id>/<token>", methods=["GET", "POST"])
def verify_payment(request_id, token):
    """Owner visits /verify/<id>/<SECRET_KEY> to mark as verified."""
    if (token or "").strip() != app.config["SECRET_KEY"]:
        return "Unauthorized", 403

    date_req = DateRequest.query.get(request_id)
    if not date_req:
        return "Request not found", 404

    if request.method == "POST":
        action = request.form.get("action")
        if action == "verify":
            date_req.payment_status = "verified"
            db.session.commit()
            body = f"""
💗 Date Confirmed!

Request ID: {date_req.id}
Date: {date_req.selected_date.strftime('%A, %B %d, %Y')}
Time: {date_req.selected_time}
Location: {date_req.location or 'Not specified'}
Message: {date_req.personal_message or 'None'}
Transaction: {date_req.transaction_id or 'N/A'}
"""
            send_email("💗 Date Confirmed!", body)
            flash("Payment verified! Date is confirmed 💕", "success")
            return redirect(url_for("verify_payment", request_id=request_id, token=token))
        elif action == "reject":
            date_req.payment_status = "rejected"
            db.session.commit()
            flash("Payment marked as rejected.", "warning")
            return redirect(url_for("verify_payment", request_id=request_id, token=token))

    return render_template("verify.html", date_req=date_req, token=token)


# ---------- Owner: Upload QR via filepicker (Cloudinary) ----------
# Access at:  /upload   (no secret key required)

@app.route("/upload", methods=["GET", "POST"])
def upload_qr():
    """
    Simple /upload page to change the payment QR.
    No authentication required (as requested).
    Uses Cloudinary when configured, otherwise local storage.
    """
    current_qr = get_payment_qr_url()
    cloudinary_status = "enabled ✅" if CLOUDINARY_ENABLED else "disabled (local fallback)"

    if request.method == "POST":
        qr_file = request.files.get("qr_image")
        if not qr_file or not qr_file.filename:
            flash("Please choose a QR image file 📷", "error")
            return render_template(
                "upload_qr.html",
                current_qr=current_qr,
                cloudinary_status=cloudinary_status,
            )

        if not allowed_file(qr_file.filename):
            flash("Only image files are allowed (png, jpg, jpeg, gif, webp)", "error")
            return render_template(
                "upload_qr.html",
                current_qr=current_qr,
                cloudinary_status=cloudinary_status,
            )

        new_url = None
        if CLOUDINARY_ENABLED:
            new_url = upload_to_cloudinary(qr_file, folder="date-invitation/qr")
            if not new_url:
                flash("Cloudinary upload failed. Check CLOUDINARY_* env vars on Vercel.", "error")
                return render_template(
                    "upload_qr.html",
                    current_qr=current_qr,
                    cloudinary_status=cloudinary_status,
                )
        else:
            if IS_VERCEL:
                flash("Cloudinary is required on Vercel. Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET in Environment Variables.", "error")
                return render_template(
                    "upload_qr.html",
                    current_qr=current_qr,
                    cloudinary_status=cloudinary_status,
                )
            rel = save_local_file(qr_file, prefix="qr_")
            if rel:
                new_url = url_for("static", filename=rel, _external=True)

        if new_url:
            Setting.set("payment_qr_url", new_url)
            flash("QR image uploaded successfully! 🎉", "success")
            return redirect(url_for("upload_qr"))
        else:
            flash("Upload failed. Try again or check Cloudinary settings.", "error")

    return render_template(
        "upload_qr.html",
        current_qr=current_qr,
        cloudinary_status=cloudinary_status,
    )


@app.route("/api/say-yes", methods=["POST"])
@csrf.exempt
def say_yes():
    session["said_yes"] = True
    return jsonify({"ok": True})


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "cloudinary_configured": CLOUDINARY_ENABLED,
        "mail_configured": bool(app.config["MAIL_USERNAME"] and app.config["MAIL_PASSWORD"] and OWNER_EMAIL),
        "owner_email": bool(OWNER_EMAIL),
        "database": "postgres" if "postgres" in (app.config.get("SQLALCHEMY_DATABASE_URI") or "") else "sqlite",
    })


# Create tables lazily / safely (avoid crash on read-only or cold start)
def _ensure_tables():
    try:
        with app.app_context():
            db.create_all()
    except Exception as e:
        app.logger.warning(f"db.create_all() skipped: {e}")

_ensure_tables()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_ENV") == "development")
