# chamasmart/app/__init__.py
from flask import Flask
from .config import Config
from .extensions import db, migrate, login_manager, mail
from .models.user import User
from app.utils.notifications import notification_manager

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)
    notification_manager.init_app(app)

    # Register Blueprints
    from .blueprints.auth.routes import auth_bp
    from .blueprints.member_dashboard.routes import member_bp
    from .blueprints.chama_admin.routes import chama_admin_bp
    from .blueprints.platform_admin.routes import platform_admin_bp
    from .blueprints.contributions.routes import contributions_bp
    from .blueprints.loans.routes import loans_bp
    from .blueprints.expenses.routes import expenses_bp
    from .blueprints.reports.routes import reports_bp
    from .blueprints.notifications.routes import notifications_bp
    from .blueprints.public.routes import public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(member_bp)
    app.register_blueprint(chama_admin_bp)
    app.register_blueprint(platform_admin_bp)
    app.register_blueprint(contributions_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(notifications_bp)

    return app
