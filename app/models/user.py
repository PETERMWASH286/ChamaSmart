# chamasmart/app/models/user.py
from datetime import datetime
from flask_login import UserMixin
from app.extensions import db
from app.models.loan import Loan

class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    role = db.Column(db.Enum('member', 'treasurer', 'admin', 'super_admin', name='user_roles'), nullable=False, default='member')

    # ADD this many-to-many:
    chamas = db.relationship(
        'Chama',
        secondary='chama_admins',
        back_populates='admins'
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Add these relationships
    contributions = db.relationship('Contribution', back_populates='user', cascade='all, delete-orphan')
    penalties = db.relationship('Penalty', back_populates='user', cascade='all, delete-orphan')
    # Add to User class
    loans = db.relationship('Loan', foreign_keys=[Loan.user_id], back_populates='user', cascade='all, delete-orphan')
    loan_repayments = db.relationship('LoanRepayment', back_populates='user', cascade='all, delete-orphan')
    def __repr__(self):
        return f"<User {self.email} ({self.role})>"