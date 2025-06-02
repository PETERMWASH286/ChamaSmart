# /home/pincho/Desktop/chamasmart/app/models/contribution.py
from datetime import datetime
from app.extensions import db

class Contribution(db.Model):
    __tablename__ = 'contributions'

    # Payment statuses
    STATUSES = ('Paid', 'Pending', 'Overdue')
    # Payment methods
    METHODS = ('M-Pesa', 'Bank', 'Cash', 'Other')

    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    status = db.Column(db.Enum(*STATUSES, name='contribution_status'), default='Pending')
    method = db.Column(db.Enum(*METHODS, name='payment_method'), nullable=False)
    reference_number = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    chama_id = db.Column(db.Integer, db.ForeignKey('chamas.id'), nullable=False)
    
    # Many-to-one relationships
    user = db.relationship('User', back_populates='contributions')
    chama = db.relationship('Chama', back_populates='contributions')

    def __repr__(self):
        return f"<Contribution KES {self.amount} by {self.user.full_name}>"

class Penalty(db.Model):
    __tablename__ = 'penalties'

    STATUSES = ('Active', 'Waived', 'Paid')
    TYPES = ('Late Payment', 'Missed Meeting', 'Other')

    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    penalty_type = db.Column(db.Enum(*TYPES, name='penalty_type'), default='Late Payment')
    status = db.Column(db.Enum(*STATUSES, name='penalty_status'), default='Active')
    reason = db.Column(db.Text, nullable=True)
    imposed_date = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    chama_id = db.Column(db.Integer, db.ForeignKey('chamas.id'), nullable=False)
    
    # Many-to-one relationships
    user = db.relationship('User', back_populates='penalties')
    chama = db.relationship('Chama', back_populates='penalties')

    def __repr__(self):
        return f"<Penalty KES {self.amount} for {self.user.full_name}>"