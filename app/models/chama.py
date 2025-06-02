# chamasmart/app/models/chama.py
from datetime import datetime, timedelta
from uuid import uuid4
from app.extensions import db


# Admins ↔ Chamas many-to-many
chama_admins = db.Table(
    'chama_admins',
    db.Column('user_id',  db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('chama_id', db.Integer, db.ForeignKey('chamas.id'), primary_key=True)
)
 
class Chama(db.Model):
    __tablename__ = 'chamas'
    
    # Existing columns...
    STATUSES = ('active', 'suspended', 'archived')
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    purpose = db.Column(db.String(255), nullable=True)
    contribution_frequency = db.Column(
        db.Enum('weekly', 'monthly', 'yearly', name='frequency'),
        nullable=False, 
        default='monthly'
    )
    currency = db.Column(db.String(3), nullable=False, default='KES')
    rules = db.Column(db.Text, nullable=True)
    status = db.Column(
        db.Enum(*STATUSES, name='chama_status'),
        nullable=False,
        default='active'
    )
    # Add to Chama model
    contribution_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Add these two relationships:
    admins = db.relationship(
        'User',
        secondary=chama_admins,
        back_populates='chamas'
    )
    invitations = db.relationship('Invitation', back_populates='chama', cascade='all, delete-orphan')
    # Add these relationships
    contributions = db.relationship('Contribution', back_populates='chama', cascade='all, delete-orphan')
    penalties = db.relationship('Penalty', back_populates='chama', cascade='all, delete-orphan')
    # Add to Chama class
    loans = db.relationship('Loan', back_populates='chama', cascade='all, delete-orphan')
    def __repr__(self):
        return f"<Chama {self.name}>"


class Invitation(db.Model):
    __tablename__ = 'invitations'

    STATUSES = ('pending', 'accepted', 'expired')

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=True, index=True)
    phone = db.Column(db.String(20), nullable=True, index=True)
    token = db.Column(db.String(36), unique=True, index=True, default=lambda: str(uuid4().hex))
    expiration = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=7))
    status = db.Column(db.Enum(*STATUSES, name='invitation_status'), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    chama_id = db.Column(db.Integer, db.ForeignKey('chamas.id'), nullable=False)
    chama = db.relationship('Chama', back_populates='invitations')
    
    invited_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    invited_by = db.relationship('User')

    def __repr__(self):
        return f"<Invitation {self.token} ({self.status})>"

    def is_expired(self):
        return datetime.utcnow() > self.expiration

    def generate_new_token(self):
        self.token = uuid4().hex
        self.expiration = datetime.utcnow() + timedelta(days=7)
        self.status = 'pending'