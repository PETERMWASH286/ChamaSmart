# app/blueprints/auth/routes.py
from flask import Blueprint, current_app, make_response, render_template, redirect, session, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from app.models.user import User
from app.models.chama import Chama, Invitation

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


def _dashboard_for(user):
    """Choose dashboard based on user role."""
    if user.role == 'member':
        return url_for('member_dashboard.dashboard')
    if user.role in ('admin', 'treasurer'):
        return url_for('chama_admin.dashboard')
    if user.role == 'super_admin':
        return url_for('platform_admin.dashboard')
    return url_for('public.home')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handle user login: email, password, remember me, redirects.
    """
    # Redirect already-logged-in users
    if current_user.is_authenticated:
        return redirect(_dashboard_for(current_user))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        # Lookup user
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user, remember=remember)
            flash('Logged in successfully.', 'success')

            # Redirect to next or role-based dashboard
            next_page = request.args.get('next')
            return redirect(next_page or _dashboard_for(user))
        else:
            flash('Invalid email or password.', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    # 1) Remove user from session
    logout_user()

    # 2) Clear everything else in session (just in case)
    session.clear()

    # 3) Prepare redirect response and delete the 'remember me' cookie
    resp = make_response(redirect(url_for('auth.login')))
    cookie_name = current_app.config.get('REMEMBER_COOKIE_NAME', 'remember_token')
    resp.delete_cookie(cookie_name)

    # 4) Flash and return
    flash('Logged out successfully.', 'info')
    return resp


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    """
    Handle both Member and Admin registrations depending on form fields.
    """
    if request.method == 'POST':
        # Common fields
        full_name       = request.form.get('fullName', '').strip()
        email           = request.form.get('email', '').strip().lower()
        phone           = request.form.get('phone', '').strip()
        password        = request.form.get('password', '')
        confirm_pass    = request.form.get('confirmPassword', '')
        accepted_terms  = request.form.get('acceptedTerms') == 'on'

        errors = []
        # Validate common
        if not full_name:
            errors.append('Full name is required.')
        if not email:
            errors.append('Email is required.')
        if not phone:
            errors.append('Phone number is required.')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')
        if password != confirm_pass:
            errors.append('Passwords do not match.')
        if not accepted_terms:
            errors.append('You must accept the terms.')
        if User.query.filter_by(email=email).first():
            errors.append('Email is already registered.')

        # Admin registration (has chamaName)
        if 'chamaName' in request.form:
            chama_name = request.form.get('chamaName', '').strip()
            if not chama_name:
                errors.append('Chama name is required.')

            if errors:
                for e in errors:
                    flash(e, 'error')
                return render_template('auth/get_started.html', form_data=request.form)

            # Create Chama
            chama = Chama(
                name=chama_name,
                purpose='',
                contribution_frequency='monthly',
                currency='KES',
                rules=''
            )
            db.session.add(chama)
            db.session.flush()  # Get chama.id before committing

            # Create Admin user
            hashed = generate_password_hash(password)
            user = User(
                full_name=full_name,
                email=email,
                phone=phone,
                password=hashed,
                role='admin'
            )
            user.chamas.append(chama)  # ← Updated line for M2M relationship
            db.session.add(user)
            db.session.commit()

            login_user(user)
            flash('Chama created and you are now logged in!', 'success')
            return redirect(url_for('chama_admin.dashboard'))

        # Member registration
        else:
            if errors:
                for e in errors:
                    flash(e, 'error')
                return render_template('auth/get_started.html', form_data=request.form)

            hashed = generate_password_hash(password)
            user = User(
                full_name=full_name,
                email=email,
                phone=phone,
                password=hashed,
                role='member'
            )
            db.session.add(user)
            db.session.commit()

            login_user(user)
            flash('Registration successful! Welcome to ChamaSmart.', 'success')
            return redirect(url_for('member_dashboard.dashboard'))

    return render_template('auth/get_started.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register_with_token():
    """
    Register a member via invitation token.
    Full validation: token presence, existence, expiration, and link to chama.
    """
    token = request.args.get('token', '').strip()
    print(f"[DEBUG] Received token: {token}")

    if not token or len(token) < 10:
        flash('Invalid or missing invitation token.', 'error')
        print("[DEBUG] Token missing or too short")
        return redirect(url_for('auth.signup'))

    # Look up token
    invitation = Invitation.query.filter_by(token=token).first()
    if not invitation:
        flash('This invitation link is invalid.', 'error')
        print("[DEBUG] Token not found in DB")
        return redirect(url_for('auth.signup'))

    if invitation.is_expired():
        flash('This invitation link has expired.', 'error')
        print("[DEBUG] Token expired")
        return redirect(url_for('auth.signup'))

    if invitation.status != 'pending':
        flash('This invitation link has already been used.', 'error')
        print(f"[DEBUG] Token already used (status: {invitation.status})")
        return redirect(url_for('auth.signup'))

    if request.method == 'POST':
        # Get form data
        full_name = request.form.get('fullName', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm_pass = request.form.get('confirmPassword', '')
        accepted_terms = request.form.get('acceptedTerms') == 'on'

        print(f"[DEBUG] Form data: {request.form}")

        errors = []
        if not full_name:
            errors.append('Full name is required.')
        if not email:
            errors.append('Email is required.')
        if not phone:
            errors.append('Phone number is required.')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')
        if password != confirm_pass:
            errors.append('Passwords do not match.')
        if not accepted_terms:
            errors.append('You must accept the terms and conditions.')

        if User.query.filter_by(email=email).first():
            errors.append('Email is already registered.')

        if errors:
            for err in errors:
                flash(err, 'error')
            print("[DEBUG] Validation errors:", errors)
            return render_template('auth/invite_register.html', token=token, form_data=request.form)

        # Create user
        hashed = generate_password_hash(password)
        user = User(
            full_name=full_name,
            email=email,
            phone=phone,
            password=hashed,
            role='member'
        )

        # Link user to chama
        chama = invitation.chama
        user.chamas.append(chama)

        try:
            db.session.add(user)
            invitation.status = 'accepted'
            db.session.commit()
            print(f"[DEBUG] User created and linked to chama: {chama.name}")
        except Exception as e:
            db.session.rollback()
            flash("An error occurred while creating the account.", 'error')
            print(f"[DEBUG] DB error: {e}")
            return render_template('auth/invite_register.html', token=token, form_data=request.form)

        login_user(user)
        flash('Welcome aboard! You’ve successfully joined the Chama.', 'success')
        return redirect(url_for('member_dashboard.dashboard'))

    return render_template('auth/invite_register.html', token=token)

