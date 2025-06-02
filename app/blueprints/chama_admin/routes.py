# app/blueprints/chama_admin/routes.py
from datetime import datetime
from io import BytesIO
from turtle import pd
from flask import Blueprint, abort, jsonify, render_template, request, send_file
from flask_login import login_required, current_user
from app import db  # Import the db object
from app.utils.notifications import notification_manager
import logging
from app.models.chama import Chama, Invitation
import sys
from app.models.user import User
from werkzeug.security import generate_password_hash

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
# First add these imports at the top of routes.py
import pandas as pd

chama_admin_bp = Blueprint('chama_admin', __name__, url_prefix='/chama-admin')


logger = logging.getLogger(__name__) 

@chama_admin_bp.route('/')
@login_required
def dashboard():
    """Chama Admin & Treasurer dashboard (Home)."""
    return render_template('dashboard_chama_admin/index.html')



@chama_admin_bp.route('/chamas')
@login_required
def manage_chamas():
    """
    List and manage all chamas, scoped by role:
    - super_admin: sees everything
    - admin/treasurer: sees only their own chamas
    """
    # 1) Determine which chamas to show
    if current_user.role == 'super_admin':
        queryset = Chama.query.order_by(Chama.name).all()
    else:
        # admin or treasurer can belong to multiple chamas
        queryset = current_user.chamas or []

    # 2) Build a serializable list with per‑chama stats
    chamas = []
    for c in queryset:
        members_count = len(c.admins or [])  # formerly users
        chamas.append({
            'id': c.id,
            'name': c.name,
            'purpose': c.purpose or '',
            'frequency': c.contribution_frequency,
            'currency': c.currency,
            'rules': c.rules or '',
            'created_at': c.created_at.strftime('%Y-%m-%d'),
            'updated_at': c.updated_at.strftime('%Y-%m-%d'),
            'members_count': members_count,
            # Add more fields here as needed
        })

    # 3) Compute global stats
    total_chamas = len(chamas)
    total_members = sum(item['members_count'] for item in chamas)

    # 4) Render with context for your Alpine JS data()
    return render_template(
        'dashboard_chama_admin/manage_chamas.html',
        chamas=chamas,
        total_chamas=total_chamas,
        total_members=total_members
    )



@chama_admin_bp.route('/chamas-data')
@login_required
def chamas_data():
    # 1) Get the set of chamas this user can see
    if current_user.role == 'super_admin':
        queryset = Chama.query.order_by(Chama.name).all()
    else:
        queryset = current_user.chamas  # M2M list of chamas they belong to

    chamas = []
    for c in queryset:
        # 2) Count pending invites
        pending_invites = Invitation.query.filter(
            Invitation.chama_id == c.id,
            Invitation.status == 'pending',
            Invitation.expiration > datetime.utcnow()
        ).count()

        # 3) Build member list (only users with role='member')
        members = [
            {
                'name': user.full_name,
                'email': user.email,
                'phone': user.phone
            }
            for user in c.admins  # back_populates='chamas'
            if user.role == 'member'
        ]

        chamas.append({
            'id': c.id,
            'name': c.name,
            'status': c.status,
            'members_count': len(members),
            'members': members,
            'pending_invites': pending_invites,
            'contribution_amount': float(c.contribution_amount),
            'frequency': c.contribution_frequency,
            'currency': c.currency,
            'created_at': c.created_at.strftime('%Y-%m-%d'),
            'rules': c.rules or ''
        })

    return jsonify({
        'chamas': chamas,
        'total_chamas': len(chamas),
        'total_members': sum(c['members_count'] for c in chamas),
        'total_pending_invites': sum(c['pending_invites'] for c in chamas)
    })

@chama_admin_bp.route('/chamas/update/<int:chama_id>', methods=['POST'])
@login_required
def update_chama(chama_id):
    # 1) Load the target chama
    chama = Chama.query.get_or_404(chama_id)

    # 2) Enforce permission: only super_admin or admins linked to the chama
    if current_user.role != 'super_admin' and chama not in current_user.chamas:
        abort(403)

    # 3) Parse JSON payload
    data = request.get_json() or {}
    name   = data.get('name', '').strip()
    freq   = data.get('contribution_frequency')
    rules  = data.get('rules', '').strip()
    amount = data.get('contribution_amount')

    # 4) Validation
    if not name or not freq or amount is None:
        return jsonify({'error': 'Missing required fields'}), 400

    # 5) Apply changes
    chama.name                   = name
    chama.contribution_frequency = freq
    chama.rules                  = rules
    chama.contribution_amount    = amount
    chama.updated_at             = datetime.utcnow()

    # 6) Save
    db.session.commit()

    # 7) Respond
    return jsonify({
        'id': chama.id,
        'name': chama.name,
        'contribution_amount': float(chama.contribution_amount),
        'contribution_frequency': chama.contribution_frequency,
        'rules': chama.rules
    })



@chama_admin_bp.route('/chamas/invite', methods=['POST'])
@login_required
def invite_members():
    """
    Expects JSON:
    {
      "method": "email" | "sms",
      "contacts": ["a@b.com", "+2547...", ...],
      "chama_id": 123
    }
    """
    data      = request.get_json() or {}
    method    = data.get('method')
    contacts  = data.get('contacts', [])
    chama_id  = data.get('chama_id')

    # 1) Validate payload
    if method not in ('email', 'sms') or not contacts or not isinstance(chama_id, int):
        return jsonify({'error': 'Invalid payload'}), 400

    # 2) Load chama & authorize
    chama = Chama.query.get_or_404(chama_id)
    if current_user.role != 'super_admin' and chama not in current_user.chamas:
        abort(403)

    invited = []
    for contact in contacts:
        # 3) Create Invitation record
        inv = Invitation(
            email         = contact if method == 'email' else None,
            phone         = contact if method == 'sms'   else None,
            chama_id      = chama.id,
            invited_by_id = current_user.id
        )
        inv.generate_new_token()
        db.session.add(inv)
        invited.append(contact)

        expiry_str = inv.expiration.strftime('%Y-%m-%d')

        # 4a) Send email
        if method == 'email':
            notification_manager.send_email(
                subject    = f"You're invited to join \"{chama.name}\"",
                recipients = [contact],
                body       = (
                    f"Hello,\n\n"
                    f"You have been invited to join the Chama \"{chama.name}\".\n"
                    f"Sign up here: https://chamasmart/auth/register?token={inv.token}\n\n"
                    f"Invitation expires on {expiry_str}.\n"
                ),
                sender     = chama.name
            )

        # 4b) Send SMS
        else:
            notification_manager.send_sms(
                message    = (
                    f"Join \"{chama.name}\" Chama! "
                    f"Use token {inv.token} (expires {expiry_str})."
                ),
                recipients = [contact],
                sender_id  = chama.name
            )

    # 5) Commit
    db.session.commit()

    # 6) Respond
    return jsonify({
        'invited_count': len(invited),
        'invited': invited
    }), 201



@chama_admin_bp.route('/chamas/create', methods=['POST'])
@login_required
def create_chama():
    # --- Debug ---
    print(f"[DEBUG create_chama] user_id={current_user.get_id()}, role={current_user.role!r}", file=sys.stdout, flush=True)
    logger.debug(f"[DEBUG create_chama] user={current_user.get_id()} role={current_user.role}")

    data = request.get_json() or {}
    name     = data.get('name', '').strip()
    amount   = data.get('contribution_amount')
    currency = data.get('currency')

    # 1) Basic validation
    if not name or amount is None or not currency:
        return jsonify({'error': 'Missing required fields'}), 400

    # 2) Authorization: ONLY admin, treasurer, or super_admin can create
    if current_user.role not in ('super_admin', 'admin', 'treasurer'):
        print("[DEBUG create_chama] Authorization FAILED: role not allowed", file=sys.stdout, flush=True)
        logger.warning("Authorization FAILED: role not in allowed set")
        abort(403)

    # 3) Create chama and flush to get the ID
    chama = Chama(
        name                = name,
        contribution_amount = amount,
        currency            = currency
    )
    db.session.add(chama)
    db.session.flush()

    # 4) Associate this user with the chama as an admin/treasurer
    current_user.chamas.append(chama)
    db.session.add(current_user)

    # 5) Commit
    db.session.commit()

    # 6) Return the new chama data
    return jsonify({
        'id': chama.id,
        'name': chama.name,
        'status': chama.status,
        'members_count': len(chama.admins),
        'pending_invites': len(chama.invitations),
        'contribution_amount': float(chama.contribution_amount),
        'frequency': chama.contribution_frequency,
        'currency': chama.currency,
        'created_at': chama.created_at.strftime('%Y-%m-%d'),
        'rules': chama.rules or ''
    }), 201

@chama_admin_bp.route('/members')
@login_required
def members():
    """View and manage chama members."""
    # Get accessible chamas based on role
    if current_user.role == 'super_admin':
        queryset = Chama.query.order_by(Chama.name).all()
    else:
        queryset = current_user.chamas  # Assuming many-to-many relationship

    # Serialize chamas data
    chamas = [{
        'id': c.id,
        'name': c.name,
        'status': c.status,
        'members_count': len(c.admins),
        'created_at': c.created_at.strftime('%Y-%m-%d')
    } for c in queryset]

    return render_template('dashboard_chama_admin/members.html', chamas=chamas)

# Add to routes.py

@chama_admin_bp.route('/chama-members/<int:chama_id>')
@login_required
def get_chama_members(chama_id):
    # Authorization check
    chama = Chama.query.get_or_404(chama_id)
    if current_user.role != 'super_admin' and chama not in current_user.chamas:
        abort(403)

    # Get members
    members = [{
        'id': user.id,
        'name': user.full_name,
        'avatar': '/static/default-avatar.png',
        'role': 'Admin' if user.role in ['admin', 'super_admin'] else 'Member',
        'status': 'Active' if user.is_active else 'Inactive',
        'joined_at': user.created_at.strftime('%Y-%m-%d')
    } for user in chama.admins]

    # Get stats
    pending_invites = Invitation.query.filter(
        Invitation.chama_id == chama_id,
        Invitation.status == 'pending'
    ).count()

    return jsonify({
        'members': members,
        'total_members': len(members),
        'active_members': len([m for m in members if m['status'] == 'Active']),
        'pending_invites': pending_invites
    })

@chama_admin_bp.route('/chama-members/export/<int:chama_id>')
@login_required
def export_chama_members(chama_id):
    # Authorization check
    chama = Chama.query.get_or_404(chama_id)
    if current_user.role != 'super_admin' and chama not in current_user.chamas:
        abort(403)

    # Generate CSV (example using pandas)
    members = [{'Name': user.full_name, 'Email': user.email} for user in chama.admins]
    
    df = pd.DataFrame(members)
    output = BytesIO()
    df.to_csv(output, index=False)
    output.seek(0)

    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"{chama.name}_members.csv"
    )
@chama_admin_bp.route('/add-member', methods=['POST'])
@login_required
def add_chama_member():
     """Add a new member to a Chama"""
     data = request.get_json() or {}
     chama_id   = data.get('chama_id')
     full_name  = data.get('name')
     email      = data.get('email')
     phone      = data.get('phone', '')
     role       = data.get('role', 'member').lower()
     status     = data.get('status', 'Active').lower()

     # Validate required fields
     if not chama_id or not full_name or not email:
         return jsonify({"message": "chama_id, name and email are required"}), 400

     # Fetch Chama or 404
     chama = Chama.query.get_or_404(chama_id)

     # Authorization: only super_admin or existing chama admin can add
     if current_user.role != 'super_admin' and chama not in current_user.chamas:
         abort(403)

     # Find or create User
     user = User.query.filter_by(email=email).first()
     temp_password = None
     if not user and status != 'pending':
         # Create user with a temporary password
         temp_password = '1234'
         user = User(
             full_name=full_name,
             email=email,
             phone=phone,
             role=role if role in ('member','treasurer','admin','super_admin') else 'member',
             password=generate_password_hash(temp_password)
         )
         db.session.add(user)
         db.session.flush()
     elif not user:
         # Create placeholder user for pending invite (password set upon registration)
         user = User(
             full_name=full_name,
             email=email,
             phone=phone,
             role=role if role in ('member','treasurer','admin','super_admin') else 'member',
             password=generate_password_hash('placeholder')  # dummy to satisfy non-null
         )
         db.session.add(user)
         db.session.flush()

     # Prevent duplicates
     if user in chama.admins:
         return jsonify({"message": "User is already a member of this chama"}), 400

     # Attach to Chama
     chama.admins.append(user)

     # Non-pending: send login credentials
     if status != 'pending' and temp_password:
         login_url = "https://chamasmart/auth/login"
         notification_manager.send_email(
             subject=f"Access granted to \"{chama.name}\" on ChamaSmart",
             recipients=[user.email],
             body=(
                 f"Hello {user.full_name},\n\n"
                 f"You have been added to the Chama “{chama.name}”.\n"
                 f"Log in at {login_url} with:\n"
                 f"Email: {user.email}\n"
                 f"Password: {temp_password}\n\n"
                 "Please change your password after logging in.\n\n"
                 f"Best regards,\n{chama.name} Team"
             ),
             sender=chama.name
         )

     # Pending: create invitation and send registration link
     if status == 'pending':
         inv = Invitation(
             email=user.email,
             phone=user.phone,
             chama=chama,
             invited_by=current_user,
             status='pending'
         )
         inv.generate_new_token()
         db.session.add(inv)

         registration_link = f"https://chamasmart/auth/register?token={inv.token}"
         notification_manager.send_email(
             subject=f"Invitation to join \"{chama.name}\"",
             recipients=[user.email],
             body=(
                 f"Hello {user.full_name},\n\n"
                 f"You are invited to join the Chama “{chama.name}”.\n"
                 f"Set your password and complete registration here:\n{registration_link}\n\n"
                 f"Expires on {inv.expiration.strftime('%Y-%m-%d')}.\n"
             ),
             sender=chama.name
         )

     # Persist all changes
     db.session.commit()

     return jsonify({
         "message": "Member added successfully",
         "user": {
             "id": user.id,
             "name": user.full_name,
             "email": user.email
         }
     }), 201




@chama_admin_bp.route('/export/<int:chama_id>/excel')
@login_required
def export_members_excel(chama_id):
    """
    Export chama members to an enhanced Excel file with improved formatting,
    data visualization, and comprehensive member information.
    """
    # Authorization check
    chama = Chama.query.get_or_404(chama_id)
    if current_user.role != 'super_admin' and chama not in current_user.chamas:
        abort(403)
    
    # Get members data with more comprehensive information
    members = []
    for user in chama.admins:
        # Get additional statistics for each member if needed
        # For example, you could add contribution history or attendance data
        
        members.append({
            'Name': user.full_name,
            'Email': user.email,
            'Phone': user.phone if hasattr(user, 'phone') else '',
            'Role': 'Admin' if user.role in ['admin', 'super_admin'] else ('Treasurer' if user.role == 'treasurer' else 'Member'),
            'Status': 'Active' if hasattr(user, 'is_active') and user.is_active else 'Inactive',
            'Joined Date': user.created_at.strftime('%Y-%m-%d'),
            'Last Login': user.last_login.strftime('%Y-%m-%d %H:%M') if hasattr(user, 'last_login') and user.last_login else 'N/A',
            'Total Contributions': get_member_contribution_total(user.id, chama_id) if hasattr(user, 'id') else 0.00
        })
    
    # Create DataFrame
    df = pd.DataFrame(members)
    
    # Create Excel file in memory with xlsxwriter for advanced formatting
    output = BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Write main data with offset to allow for title rows
        df.to_excel(writer, sheet_name='Members', index=False, startrow=3)  # Start data from row 4
        
        # Get workbook and worksheet objects
        workbook = writer.book
        worksheet = writer.sheets['Members']
        
        # Define formats
        title_format = workbook.add_format({
            'bold': True,
            'font_name': 'Arial',
            'font_size': 16,
            'font_color': '#FFFFFF',
            'bg_color': '#4472C4',
            'border': 2,
            'align': 'center',
            'valign': 'vcenter'
        })
        
        subtitle_format = workbook.add_format({
            'bold': True,
            'font_name': 'Arial',
            'font_size': 12,
            'font_color': '#FFFFFF',
            'bg_color': '#8EA9DB',  # Lighter blue for subtitle
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        
        header_format = workbook.add_format({
            'bold': True,
            'font_name': 'Arial',
            'font_size': 12,
            'font_color': '#FFFFFF',
            'bg_color': '#4472C4',  # Modern blue color
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        
        date_format = workbook.add_format({
            'font_name': 'Arial',
            'font_size': 11,
            'num_format': 'yyyy-mm-dd',
            'align': 'center'
        })
        
        currency_format = workbook.add_format({
            'font_name': 'Arial',
            'font_size': 11,
            'num_format': f'#,##0.00 "{chama.currency}"',
            'align': 'right'
        })
        
        cell_format = workbook.add_format({
            'font_name': 'Arial',
            'font_size': 11,
            'align': 'left',
            'border': 1,
            'border_color': '#D9D9D9'
        })
        
        active_format = workbook.add_format({
            'font_name': 'Arial',
            'font_size': 11,
            'bg_color': '#C6EFCE',
            'font_color': '#006100',
            'align': 'center',
            'border': 1
        })
        
        inactive_format = workbook.add_format({
            'font_name': 'Arial',
            'font_size': 11,
            'bg_color': '#FFC7CE',
            'font_color': '#9C0006',
            'align': 'center',
            'border': 1
        })
        
        # Add title and subtitle
        # Merge cells for the title (Chama Name)
        worksheet.merge_range('A1:H1', chama.name.upper(), title_format)
        
        # Merge cells for the subtitle
        worksheet.merge_range('A2:H2', 'MEMBERS LIST', subtitle_format)
        
        # Add export date
        export_date_format = workbook.add_format({
            'font_name': 'Arial',
            'font_size': 10,
            'align': 'right',
            'italic': True
        })
        export_date = datetime.now().strftime('%Y-%m-%d %H:%M')
        worksheet.merge_range('F3:H3', f'Export Date: {export_date}', export_date_format)
        
        # Set column widths
        worksheet.set_column('A:A', 25)  # Name
        worksheet.set_column('B:B', 30)  # Email
        worksheet.set_column('C:C', 15)  # Phone
        worksheet.set_column('D:D', 12)  # Role
        worksheet.set_column('E:E', 12)  # Status
        worksheet.set_column('F:F', 15)  # Joined Date
        worksheet.set_column('G:G', 20)  # Last Login
        worksheet.set_column('H:H', 20)  # Total Contributions
        
        # Add header row with formatting (now at row 4)
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(3, col_num, value, header_format)
        
        # Format the data rows (start at row 5, which is index 4)
        for row_num in range(4, len(df) + 4):
            # Get the corresponding DataFrame row index
            df_row = row_num - 4
            
            # Apply different formats to different columns
            worksheet.write(row_num, 0, df['Name'].iloc[df_row], cell_format)
            worksheet.write(row_num, 1, df['Email'].iloc[df_row], cell_format)
            worksheet.write(row_num, 2, df['Phone'].iloc[df_row], cell_format)
            worksheet.write(row_num, 3, df['Role'].iloc[df_row], cell_format)
            
            # Conditional formatting for Status column
            status = df['Status'].iloc[df_row]
            if status == 'Active':
                worksheet.write(row_num, 4, status, active_format)
            else:
                worksheet.write(row_num, 4, status, inactive_format)
            
            # Date formatting
            worksheet.write(row_num, 5, df['Joined Date'].iloc[df_row], date_format)
            worksheet.write(row_num, 6, df['Last Login'].iloc[df_row], cell_format)
            
            # Currency formatting
            try:
                contribution = float(df['Total Contributions'].iloc[df_row])
                worksheet.write(row_num, 7, contribution, currency_format)
            except (ValueError, TypeError):
                worksheet.write(row_num, 7, df['Total Contributions'].iloc[df_row], cell_format)
        
        # Add summary information at the bottom
        summary_row = len(df) + 6  # Adjusted for the title rows
        worksheet.merge_range(summary_row, 0, summary_row, 3, 'Summary Information', header_format)
        
        worksheet.write(summary_row + 1, 0, 'Total Members:', cell_format)
        worksheet.write(summary_row + 1, 1, len(df), cell_format)
        
        worksheet.write(summary_row + 2, 0, 'Active Members:', cell_format)
        worksheet.write(summary_row + 2, 1, len(df[df['Status'] == 'Active']), cell_format)
        
        worksheet.write(summary_row + 3, 0, 'Total Contributions:', cell_format)
        total_contributions = sum(df['Total Contributions'].replace('N/A', 0).astype(float))
        worksheet.write(summary_row + 3, 1, total_contributions, currency_format)
        
        # Add chama information sheet
        chama_info = pd.DataFrame([{
            'Name': chama.name,
            'Purpose': chama.purpose or 'N/A',
            'Contribution Frequency': chama.contribution_frequency.capitalize(),
            'Contribution Amount': float(chama.contribution_amount),
            'Currency': chama.currency,
            'Status': chama.status.capitalize(),
            'Created Date': chama.created_at.strftime('%Y-%m-%d'),
            'Member Count': len(df)
        }])
        
        # Create Chama Info sheet with title
        info_sheet_name = 'Chama Info'
        chama_info.to_excel(writer, sheet_name=info_sheet_name, index=False, startrow=2)  # Start at row 3
        info_sheet = writer.sheets[info_sheet_name]
        
        # Add title to Chama Info sheet
        info_sheet.merge_range('A1:H1', f'{chama.name.upper()} - ORGANIZATION DETAILS', title_format)
        
        # Format chama info sheet
        for col_num, value in enumerate(chama_info.columns.values):
            info_sheet.write(2, col_num, value, header_format)
            info_sheet.set_column(col_num, col_num, 20)
        
        # Apply cell format to chama info sheet
        for col_num, value in enumerate(chama_info.iloc[0]):
            if col_num == 3:  # Contribution Amount
                info_sheet.write(3, col_num, float(value), currency_format)
            elif col_num == 6:  # Created Date
                info_sheet.write(3, col_num, value, date_format)
            else:
                info_sheet.write(3, col_num, value, cell_format)
        
        # Try to add logo if available
        try:
            # If logo file exists, insert it (you'd need to set up the path)
            logo_path = 'app/static/img/chama_logo.png'  # Adjust path as needed
            worksheet.insert_image('A1', logo_path, {'x_offset': 10, 'y_offset': 10, 'x_scale': 0.5, 'y_scale': 0.5})
        except:
            # If logo insertion fails, just continue without it
            pass
        
        # Enable filtering for the main data (adjusted for title rows)
        worksheet.autofilter(3, 0, len(df) + 3, len(df.columns) - 1)
        
        # Add page setup for printing
        worksheet.set_landscape()
        worksheet.fit_to_pages(1, 0)
        worksheet.set_header(f'&C&B{chama.name} - Members List')
        worksheet.set_footer('&CPage &P of &N')
        
        # Set print area to include titles and all data
        worksheet.print_area(0, 0, len(df) + 6 + 3, len(df.columns) - 1)  # Include summary
        
        # Repeat header rows on each printed page
        worksheet.repeat_rows(0, 3)  # Repeat title and header rows
    
    output.seek(0)
    
    # Create descriptive filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{chama.name}_members_report_{timestamp}.xlsx"
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

# Helper function to get member contribution totals
def get_member_contribution_total(user_id, chama_id):
    """
    Calculate the total contributions for a specific member in a chama.
    You'll need to implement this based on your contribution model.
    """
    # This is a placeholder - implement according to your data model
    try:
        # Example implementation assuming a Contribution model exists
        from app.models.contribution import Contribution
        
        total = db.session.query(db.func.sum(Contribution.amount)) \
                .filter(Contribution.user_id == user_id) \
                .filter(Contribution.chama_id == chama_id) \
                .scalar()
                
        return float(total) if total else 0.00
    except:
        # If there's an error or the model doesn't exist yet
        return 0.00


@chama_admin_bp.route('/export/<int:chama_id>/pdf')
@login_required
def export_members_pdf(chama_id):
    # Authorization check
    chama = Chama.query.get_or_404(chama_id)
    if current_user.role != 'super_admin' and chama not in current_user.chamas:
        abort(403)
        
    # Get members data
    members = [{
        'Name': user.full_name,
        'Email': user.email,
        'Phone': user.phone if hasattr(user, 'phone') else '',
        'Role': 'Admin' if user.role in ['admin', 'super_admin'] else ('Treasurer' if user.role == 'treasurer' else 'Member'),
        'Status': 'Active' if user.is_active else 'Inactive',
        'Joined Date': user.created_at.strftime('%Y-%m-%d')
    } for user in chama.admins]
    
    # Define color scheme - brand colors
    PRIMARY_COLOR = '#1A4D6C'      # Deep blue
    SECONDARY_COLOR = '#00A896'    # Teal accent
    ACCENT_COLOR = '#F9A826'       # Golden accent
    LIGHT_BG = '#F5F9FC'           # Light background
    TEXT_COLOR = '#333333'         # Main text
    LIGHT_TEXT = '#FFFFFF'         # Light text
    MUTED_TEXT = '#7A8C98'         # Muted text
    
    # Create PDF file with premium layout
    buffer = BytesIO()
    # Use A4 for international standard with better proportions
    from reportlab.lib.pagesizes import A4
    page_width, page_height = A4
    
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=80,
        bottomMargin=60
    )
    
    # Import more advanced ReportLab components
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Flowable, PageBreak, KeepTogether
    from reportlab.graphics.shapes import Drawing, Line, Rect
    
    # Custom flowable for horizontal line with gradient effect
    class GradientLine(Flowable):
        def __init__(self, width, height=2, color=PRIMARY_COLOR, spacer=10):
            Flowable.__init__(self)
            self.width = width
            self.height = height
            self.color = color
            self.spacer = spacer
            
        def draw(self):
            self.canv.setFillColor(self.color)
            self.canv.rect(0, 0, self.width, self.height, fill=1)
            
    # Initialize enhanced styles
    styles = getSampleStyleSheet()
    
    # Premium title style
    styles.add(ParagraphStyle(
        name='PremiumTitle',
        fontName='Helvetica-Bold',
        fontSize=28,
        alignment=1,  # Center alignment
        spaceAfter=10,
        textColor=colors.HexColor(PRIMARY_COLOR)
    ))
    
    # Add more custom styles
    styles.add(ParagraphStyle(
        name='SubTitle',
        fontName='Helvetica',
        fontSize=16,
        alignment=1,
        spaceAfter=20,
        textColor=colors.HexColor(SECONDARY_COLOR)
    ))
    
    styles.add(ParagraphStyle(
        name='SectionTitle',
        fontName='Helvetica-Bold',
        fontSize=14,
        alignment=0,  # Left alignment
        spaceAfter=10,
        spaceBefore=15,
        textColor=colors.HexColor(PRIMARY_COLOR)
    ))
    
    styles.add(ParagraphStyle(
        name='NormalText',
        fontName='Helvetica',
        fontSize=10,
        alignment=0,
        textColor=colors.HexColor(TEXT_COLOR)
    ))
    
    styles.add(ParagraphStyle(
        name='FooterText',
        fontName='Helvetica',
        fontSize=8,
        alignment=1,
        textColor=colors.HexColor(MUTED_TEXT)
    ))
    
    styles.add(ParagraphStyle(
        name='Disclaimer',
        fontName='Helvetica-Oblique',
        fontSize=7,
        alignment=1,
        textColor=colors.HexColor(MUTED_TEXT)
    ))
    
    # Create enhanced header and footer function
    def header_footer(canvas, doc):
        # Save canvas state
        canvas.saveState()
        
        # HEADER SECTION
        # Create modern gradient-like header
        canvas.setFillColor(colors.HexColor(PRIMARY_COLOR))
        canvas.rect(0, page_height - 55, page_width, 55, fill=1)
        
        # Add accent strip below header
        canvas.setFillColor(colors.HexColor(ACCENT_COLOR))
        canvas.rect(0, page_height - 58, page_width, 3, fill=1)
        
        # Add logo and company name with premium styling
        # Logo placeholder (this would be replaced with actual logo)
        canvas.setFillColor(colors.white)
        rounded_rect = lambda x, y, w, h, r: (
            canvas.roundRect(x, y, w, h, r, fill=1)
        )
        rounded_rect(45, page_height - 45, 35, 35, 5)
        
        # Add CS icon (placeholder)
        canvas.setFillColor(colors.HexColor(SECONDARY_COLOR))
        canvas.setFont('Helvetica-Bold', 20)
        canvas.drawString(53, page_height - 33, "CS")
        
        # Add company name with modern typography
        canvas.setFillColor(colors.white)
        canvas.setFont('Helvetica-Bold', 18)
        canvas.drawString(90, page_height - 30, "CHAMASMART")
        
        # Add tagline
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor(LIGHT_BG))
        canvas.drawString(90, page_height - 42, "SMART FINANCIAL MANAGEMENT")
        
        # — Document type badge —
        badge_text = "MEMBER REPORT"
        badge_font  = "Helvetica-Bold"
        badge_size  = 9
        badge_pad_x = 6   # horizontal padding
        badge_pad_y = 4   # vertical padding
        text_w = canvas.stringWidth(badge_text, badge_font, badge_size)
        badge_w = text_w + badge_pad_x * 2
        badge_h = badge_size + badge_pad_y * 2

        # position it 45pt from right edge, vertically centered on your header strip
        bx = page_width - 45 - badge_w
        by = page_height - 30 - badge_h/2

        # optional shadow for depth
        canvas.setFillColor(colors.HexColor("#000000"), alpha=0.15)
        canvas.roundRect(bx+1, by-1, badge_w, badge_h, badge_h/2, fill=1, stroke=0)

        # fill the badge
        canvas.setFillColor(colors.HexColor(ACCENT_COLOR))
        canvas.roundRect(bx, by, badge_w, badge_h, badge_h/2, fill=1, stroke=0)

        # draw the label
        canvas.setFont(badge_font, badge_size)
        canvas.setFillColor(colors.white)
        canvas.drawString(bx + badge_pad_x, by + badge_pad_y, badge_text)


        # — Page number pill —
        page_text = f"{doc.page}"
        page_font = "Helvetica-Bold"
        page_size = 8
        page_pad  = 3
        p_w = canvas.stringWidth(page_text, page_font, page_size) + page_pad*2
        p_h = page_size + page_pad*2

        # place it just left of the document-type badge
        px = bx - 10 - p_w
        py = by

        # page-pill background
        canvas.setFillColor(colors.HexColor(SECONDARY_COLOR))
        canvas.roundRect(px, py, p_w, p_h, p_h/2, fill=1, stroke=0)

        # page number text
        canvas.setFont(page_font, page_size)
        canvas.setFillColor(colors.white)
        canvas.drawCentredString(px + p_w/2, py + page_pad, page_text)

        
        # FOOTER SECTION
        # Add modern footer bar
        canvas.setFillColor(colors.HexColor(LIGHT_BG))
        canvas.rect(0, 0, page_width, 40, fill=1)
        
        # Add accent line above footer
        canvas.setFillColor(colors.HexColor(SECONDARY_COLOR))
        canvas.rect(0, 40, page_width, 1, fill=1)
        
        # Add footer content with enhanced layout
        canvas.setFillColor(colors.HexColor(MUTED_TEXT))
        canvas.setFont('Helvetica', 8)
        current_date = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        # Left side info
        canvas.drawString(45, 25, f"Generated: {current_date}")
        canvas.drawString(45, 15, f"Chama ID: {chama_id}")
        
        # Center info
        canvas.setFont('Helvetica-Bold', 9)
        canvas.setFillColor(colors.HexColor(PRIMARY_COLOR))
        canvas.drawCentredString(page_width/2, 25, "Report generated by ChamaSmart Software")
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor(MUTED_TEXT))
        canvas.drawCentredString(page_width/2, 15, "Premium Financial Management Solutions")
        
        # Right side info
        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(page_width - 45, 25, "support@chamasmart.com")
        canvas.drawRightString(page_width - 45, 15, "www.chamasmart.com")
        
        # Restore canvas state
        canvas.restoreState()
    
    # Initialize elements list for content
    elements = []
    
    # Create cover page
    # Add title with premium styling
    title = Paragraph(f"{chama.name}", styles['PremiumTitle'])
    elements.append(Spacer(1, 60))  # Add space at top
    elements.append(title)
    elements.append(Spacer(1, 20))    # <-- add 20 points of space here

    
    # Add subtitle with date
    today = datetime.now().strftime('%B %d, %Y')
    subtitle = Paragraph(f"Members Report", styles['SubTitle'])
    elements.append(subtitle)
    
    # create and center the decorative line
    line = GradientLine(200)
    line.hAlign = 'CENTER'      # ← tell Platypus to center it
    elements.append(line)

    elements.append(Spacer(1, 20))
    
    # Add report summary
    summary_text = f"This report provides a comprehensive overview of all members in {chama.name} as of {today}."
    summary = Paragraph(summary_text, styles['NormalText'])
    elements.append(summary)
    elements.append(Spacer(1, 30))
    
    # Add chama details in a premium styled box
    elements.append(Paragraph("Chama Information", styles['SectionTitle']))
    
    # Create enhanced chama info table
    chama_info = [
        ['Purpose', chama.purpose or 'N/A'],
        ['Contribution', f"{chama.currency} {chama.contribution_amount} ({chama.contribution_frequency})"],
        ['Status', chama.status.capitalize()],
        ['Created', chama.created_at.strftime('%B %d, %Y')],
        ['Total Members', f"{len(members)} {'members' if len(members) != 1 else 'member'}"]
    ]
    
    # Create chama info table with premium styling
    info_table = Table(chama_info, colWidths=[120, 350])
    info_table.setStyle(TableStyle([
        # Alternating row colors for modern look
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor(LIGHT_BG)),
        ('BACKGROUND', (1, 0), (1, -1), colors.white),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor(PRIMARY_COLOR)),
        ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor(TEXT_COLOR)),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        # Add subtle borders
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#EEEEEE')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#DDDDDD')),
    ]))
    
    elements.append(info_table)
    
    # Add page break for cleaner layout
    elements.append(PageBreak())
    
    # MEMBERS SECTION
    section_title = Paragraph("Member Directory", styles['SectionTitle'])
    elements.append(section_title)
    elements.append(GradientLine(100, color=colors.HexColor(SECONDARY_COLOR)))
    elements.append(Spacer(1, 15))
    
    # Add introductory text
    intro_text = f"Below is a complete list of members registered with {chama.name}. The data includes contact information, roles, and membership status."
    intro = Paragraph(intro_text, styles['NormalText'])
    elements.append(intro)
    elements.append(Spacer(1, 15))
    
    # Create members table with responsive design
    if members:
        # Determine table columns (dynamic based on available width)
        available_width = page_width - (doc.leftMargin + doc.rightMargin)
        
        headers = list(members[0].keys())
        data = [headers]  # First row is headers
        for member in members:
            data.append([member[header] for header in headers])
            
        # Create dynamic column widths based on content type
        col_widths = None
        if available_width >= 450:  # Enough space for full table
            # Calculate proportional column widths
            name_width = int(available_width * 0.20)  # 20% for name
            email_width = int(available_width * 0.25)  # 25% for email
            phone_width = int(available_width * 0.15)  # 15% for phone
            role_width = int(available_width * 0.12)   # 12% for role
            status_width = int(available_width * 0.12) # 12% for status
            date_width = int(available_width * 0.16)   # 16% for date
            
            col_widths = [name_width, email_width, phone_width, role_width, status_width, date_width]
        
        # Create the table with responsive column widths
        table = Table(data, colWidths=col_widths, repeatRows=1)
            
        # Style the table with premium modern look
        table.setStyle(TableStyle([
            # Enhanced header styling
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(PRIMARY_COLOR)),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 15),
            ('TOPPADDING', (0, 0), (-1, 0), 15),
            
            # Enhanced content styling
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor(TEXT_COLOR)),
            ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            
            # Premium zebra striping for readability
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor(LIGHT_BG)]),
            
            # Subtle grid styling for modern look
            ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor(SECONDARY_COLOR)),  # Header bottom line
            ('LINEBELOW', (0, 1), (-1, -2), 0.3, colors.HexColor('#EEEEEE')),     # Row dividers
            ('BOX', (0, 0), (-1, -1), 0.7, colors.HexColor('#DDDDDD')),           # Table border
            
            # Status colors for visual indicators
            ('TEXTCOLOR', (4, 1), (4, -1), colors.HexColor(SECONDARY_COLOR)),  # Status column
        ]))
        
        # Add conditional formatting - highlight admins
        for i in range(1, len(data)):
            if data[i][3] == 'Admin':  # Role column
                table.setStyle(TableStyle([
                    ('TEXTCOLOR', (3, i), (3, i), colors.HexColor(ACCENT_COLOR)),
                    ('FONTNAME', (3, i), (3, i), 'Helvetica-Bold'),
                ]))
            
            # Add status indicators
            if data[i][4] == 'Active':  # Status column
                table.setStyle(TableStyle([
                    ('TEXTCOLOR', (4, i), (4, i), colors.HexColor(SECONDARY_COLOR)),
                ]))
            else:
                table.setStyle(TableStyle([
                    ('TEXTCOLOR', (4, i), (4, i), colors.HexColor('#FF5252')),  # Red for inactive
                ]))
        
        # Add table within KeepTogether to prevent page breaks in the middle
        elements.append(KeepTogether([table]))
    else:
        # Create a visually appealing "no members" message
        no_members_text = "No members found for this chama."
        
        # Create a styled box for the message
        no_members_style = ParagraphStyle(
            name='NoMembers',
            fontName='Helvetica-Bold',
            fontSize=12,
            alignment=1,  # Center
            textColor=colors.HexColor(MUTED_TEXT)
        )
        
        no_members = Paragraph(no_members_text, no_members_style)
        
        # Create a framed box
        no_members_table = Table([[no_members]], colWidths=[400])
        no_members_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor(LIGHT_BG)),
            ('ALIGN', (0, 0), (0, 0), 'CENTER'),
            ('BOTTOMPADDING', (0, 0), (0, 0), 20),
            ('TOPPADDING', (0, 0), (0, 0), 20),
            ('BOX', (0, 0), (0, 0), 1, colors.HexColor('#DDDDDD')),
        ]))
        
        elements.append(no_members_table)
    
    # Add report notes section
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("Notes", styles['SectionTitle']))
    elements.append(GradientLine(100, color=colors.HexColor(SECONDARY_COLOR)))
    elements.append(Spacer(1, 10))
    
    notes_text = """
    1. This report contains confidential information about chama members.
    2. The status shown reflects the current state at the time of report generation.
    3. For any discrepancies or updates, please contact your chama administrator.
    4. Report data is synchronized with the ChamaSmart database.
    """
    
    notes = Paragraph(notes_text, styles['NormalText'])
    elements.append(notes)
    
    # Add legal information at the bottom
    elements.append(Spacer(1, 40))
    
    # Add disclaimer with more professional styling
    disclaimer_text = "CONFIDENTIALITY NOTICE: This document contains proprietary information belonging to ChamaSmart Software and the respective chama organization. Unauthorized distribution is strictly prohibited. All information is provided as-is without warranty of any kind."
    disclaimer = Paragraph(disclaimer_text, styles['Disclaimer'])
    elements.append(disclaimer)
    
    # Copyright footer
    copyright_text = f"© {datetime.now().year} ChamaSmart Software. All rights reserved."
    copyright = Paragraph(copyright_text, styles['Disclaimer'])
    elements.append(copyright)
    
    # Build PDF with our premium header and footer
    doc.build(elements, onFirstPage=header_footer, onLaterPages=header_footer)
    
    # Reset file pointer
    buffer.seek(0)
    
    # Generate filename with timestamp and chama details
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_chama_name = ''.join(c if c.isalnum() else '_' for c in chama.name)
    filename = f"{safe_chama_name}_Members_Report_{timestamp}.pdf"
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )

@chama_admin_bp.route('/contributions')
@login_required
def contributions():
    """Contributions overview and management."""
    return render_template('dashboard_chama_admin/contributions.html')

@chama_admin_bp.route('/loans')
@login_required
def loans():
    """Approve and track loans."""
    return render_template('dashboard_chama_admin/loans.html')

@chama_admin_bp.route('/expenses')
@login_required
def expenses():
    """Record and review expenses."""
    return render_template('dashboard_chama_admin/expenses.html')

@chama_admin_bp.route('/communications')
@login_required
def communications():
    """In-app announcements and chat."""
    return render_template('dashboard_chama_admin/communications.html')

@chama_admin_bp.route('/reports')
@login_required
def reports():
    """Generate and download financial reports."""
    return render_template('dashboard_chama_admin/reports.html')

@chama_admin_bp.route('/settings')
@login_required
def settings():
    """Configure chama settings."""
    return render_template('dashboard_chama_admin/settings.html')

@chama_admin_bp.route('/audit-logs')
@login_required
def audit_logs():
    """View system audit logs."""
    return render_template('dashboard_chama_admin/audit_logs.html')

@chama_admin_bp.route('/help-support')
@login_required
def help_support():
    """Help and support resources."""
    return render_template('dashboard_chama_admin/help_support.html')


def serialize_chama(chama):
    """Serializes a Chama object for listing."""
    return {
        'id': chama.id,
        'name': chama.name,
        # Add other fields if needed by the frontend, e.g., purpose, members count, etc.
        # 'purpose': chama.purpose,
    }

# Helper function to get accessible chama IDs (can be shared or duplicated if needed)
# Duplicating here for self-containment of the blueprint, but sharing is better if possible
def get_user_accessible_chama_ids_for_chamas():
    """Returns a list of chama IDs the current user has access to view in the list."""
    if current_user.is_authenticated:
        if hasattr(current_user, 'role') and current_user.role == 'super_admin':
            # Super admin can see all chamas
            # Fetching all IDs might be inefficient if you have many chamas
            # Consider pagination or limiting the number of chamas returned
             return [c.id for c in Chama.query.all()]

        if hasattr(current_user, 'chamas'):
            # User is an admin of these chamas
            return [chama.id for chama in current_user.chamas]

    return [] # No access


# --- API Endpoint for Listing Chamas ---
@chama_admin_bp.route('/api/chamas', methods=['GET'])
@login_required
def get_chamas():
    """Fetches a list of chamas accessible to the current user."""
    accessible_chama_ids = get_user_accessible_chama_ids_for_chamas()

    if not accessible_chama_ids and current_user.role != 'super_admin':
        # User is not super admin and has no accessible chamas
        return jsonify([]), 200 # Return empty list

    query = Chama.query

    # Filter by accessible chamas unless super admin
    if current_user.role != 'super_admin':
        query = query.filter(Chama.id.in_(accessible_chama_ids))

    # Optional: Add ordering (e.g., by name)
    query = query.order_by(Chama.name.asc())

    chamas = query.all()

    # Serialize the results
    serialized_chamas = [serialize_chama(chama) for chama in chamas]

    return jsonify(serialized_chamas), 200

