# /home/pincho/Desktop/chamasmart/app/models/loan.py
from datetime import datetime
from app.extensions import db
from sqlalchemy import CheckConstraint

class Loan(db.Model):
    __tablename__ = 'loans'
    
    STATUSES = ('pending', 'approved', 'rejected', 'active', 'paid', 'defaulted')
    TYPES = ('emergency', 'business', 'education', 'personal', 'other')
    
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    interest_rate = db.Column(db.Numeric(5, 2), nullable=False, default=0.0)
    purpose = db.Column(db.String(255), nullable=True)
    status = db.Column(db.Enum(*STATUSES, name='loan_status'), default='pending')
    loan_type = db.Column(db.Enum(*TYPES, name='loan_type'), default='personal')
    issued_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=False)
    repayment_period = db.Column(db.Integer, nullable=False)  # In months
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    chama_id = db.Column(db.Integer, db.ForeignKey('chamas.id'), nullable=False)
    guarantor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Many-to-one relationships
    user = db.relationship('User', foreign_keys=[user_id], back_populates='loans')
    chama = db.relationship('Chama', back_populates='loans')
    guarantor = db.relationship('User', foreign_keys=[guarantor_id])

    # One-to-many relationship with repayments
    repayments = db.relationship('LoanRepayment', back_populates='loan', cascade='all, delete-orphan')

    __table_args__ = (
        CheckConstraint('amount > 0', name='check_positive_amount'),
        CheckConstraint('interest_rate >= 0', name='check_non_negative_interest'),
    )

    def __repr__(self):
        return f"<Loan {self.amount} {self.status} for {self.user.full_name}>"

    @property
    def remaining_balance(self):
        # sum floats (start at 0.0 to ensure float result)
        total_paid = sum((float(rep.amount) for rep in self.repayments), 0.0)
        total_amount = float(self.amount) * (1 + float(self.interest_rate) / 100)
        return total_amount - total_paid

class LoanRepayment(db.Model):
    __tablename__ = 'loan_repayments'
    
    STATUSES = ('paid', 'partial', 'missed')
    
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.Enum(*STATUSES, name='repayment_status'), default='paid')
    method = db.Column(db.String(50), nullable=False)  # M-Pesa, Bank Transfer, etc.
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Many-to-one relationships
    loan = db.relationship('Loan', back_populates='repayments')
    user = db.relationship('User', back_populates='loan_repayments')

    __table_args__ = (
        CheckConstraint('amount > 0', name='check_positive_repayment'),
    )

    def __repr__(self):
        return f"<Repayment {self.amount} for Loan #{self.loan_id}>"