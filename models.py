from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid

db = SQLAlchemy()


class DateRequest(db.Model):
    __tablename__ = "date_requests"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    selected_date = db.Column(db.Date, nullable=False)
    selected_time = db.Column(db.String(20), nullable=False)
    location = db.Column(db.String(255), nullable=True)
    personal_message = db.Column(db.Text, nullable=True)
    payment_status = db.Column(db.String(50), default="pending")  # pending, proof_submitted, verified, rejected
    transaction_id = db.Column(db.String(100), nullable=True)
    proof_filename = db.Column(db.String(255), nullable=True)      # legacy local name
    proof_url = db.Column(db.String(500), nullable=True)           # Cloudinary secure URL
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "selected_date": self.selected_date.isoformat() if self.selected_date else None,
            "selected_time": self.selected_time,
            "location": self.location,
            "personal_message": self.personal_message,
            "payment_status": self.payment_status,
            "transaction_id": self.transaction_id,
            "proof_url": self.proof_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Setting(db.Model):
    """Simple key-value store (e.g. payment_qr_url)."""
    __tablename__ = "settings"

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        row = Setting.query.get(key)
        return row.value if row and row.value else default

    @staticmethod
    def set(key, value):
        row = Setting.query.get(key)
        if row:
            row.value = value
        else:
            row = Setting(key=key, value=value)
            db.session.add(row)
        db.session.commit()
        return row
