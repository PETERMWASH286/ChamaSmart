# Skeleton: app/blueprints/notifications/routes.py
from flask import Blueprint
from flask_login import login_required

notifications_bp = Blueprint('notifications', __name__, url_prefix='/notifications')

@notifications_bp.route('/')
@login_required
def list_notifications():
    # List notifications
    return "List of notifications"  # replace with template