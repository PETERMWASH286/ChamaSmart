# chamasmart/app/config.py

import os

class Config:
    SECRET_KEY                    = os.getenv('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI       = os.getenv('SQLALCHEMY_DATABASE_URI')
    SQLALCHEMY_TRACK_MODIFICATIONS= os.getenv('SQLALCHEMY_TRACK_MODIFICATIONS', 'False') == 'True'

    # ─── Email Settings ───────────────────────────────────────────────────────────
    SMTP_SERVER      = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT        = int(os.getenv('SMTP_PORT', 587))
    SMTP_USERNAME    = os.getenv('SMTP_USERNAME')       # e.g. your Gmail address
    SMTP_PASSWORD    = os.getenv('SMTP_PASSWORD')       # app password (or real SMTP pwd)
    DEFAULT_EMAIL_SENDER = os.getenv('DEFAULT_EMAIL_SENDER', SMTP_USERNAME)

    # ─── SMS (Africa’s Talking) Settings ─────────────────────────────────────────
    AFRICASTALKING_USERNAME = os.getenv('AFRICASTALKING_USERNAME')
    AFRICASTALKING_API_KEY  = os.getenv('AFRICASTALKING_API_KEY')
    AFRICASTALKING_SENDER_ID= os.getenv('AFRICASTALKING_SENDER_ID')
