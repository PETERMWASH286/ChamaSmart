# chamasmart/app/blueprints/public/routes.py
from flask import Blueprint, render_template

public_bp = Blueprint('public', __name__)

@public_bp.route('/')
def home():
    return render_template('public_site/home.html')