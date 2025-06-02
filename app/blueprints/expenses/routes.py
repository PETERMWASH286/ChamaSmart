# Skeleton: app/blueprints/expenses/routes.py
from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required

expenses_bp = Blueprint('expenses', __name__, url_prefix='/expenses')

@expenses_bp.route('/')
@login_required
def list_expenses():
    # List expenses
    return render_template('expenses/list.html')

@expenses_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    # Add expense
    return render_template('expenses/add.html')