# /home/pincho/Desktop/chamasmart/app/blueprints/contributions/routes.py

import io
from flask import Blueprint, Response, render_template, request, redirect, send_file, url_for, jsonify, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models.contribution import Contribution, Penalty
from app.models.chama import Chama, chama_admins
from app.models.user import User # Make sure User is imported
from datetime import datetime
from sqlalchemy import distinct # Import distinct for unique user IDs
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Flowable, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
# First add these imports at the top of routes.py
import pandas as pd

contributions_bp = Blueprint('contributions', __name__, url_prefix='/contributions')

# Helper function to serialize contribution data
def serialize_contribution(c):
    return {
        'id': c.id,
        'member': c.user.full_name, # Get member name from relationship
        'user_id': c.user_id,      # Include user_id
        'amount': float(c.amount), # Convert Decimal to float for JSON
        'date': c.payment_date.strftime('%Y-%m-%d'), # Format date
        'status': c.status,
        'method': c.method,
        'chamaId': c.chama_id,
        'chamaName': c.chama.name, # Get chama name
        'reference_number': c.reference_number,
        'notes': c.notes
    }

# Helper function to serialize penalty data
def serialize_penalty(p):
     return {
        'id': p.id,
        'member': p.user.full_name,
        'user_id': p.user_id,
        'amount': float(p.amount),
        'reason': p.reason or p.penalty_type, # Use reason if available, else type
        'date': p.imposed_date.strftime('%Y-%m-%d'),
        'status': p.status,
        'chamaId': p.chama_id,
        'chamaName': p.chama.name,
        'penalty_type': p.penalty_type,
        'resolved_date': p.resolved_date.strftime('%Y-%m-%d') if p.resolved_date else None
    }

# --- Original Page Route ---
@contributions_bp.route('/')
@login_required
def list_contributions_page():
    # This route now just renders the main page template.
    # The data will be fetched by JavaScript via the API route below.
    # You might want to pass the initial list of chamas here if needed immediately
    # Or let the API handle fetching everything.
    # user_chamas = current_user.chamas # Assuming 'chamas' relationship links user to chamas they manage/are part of
    # For simplicity, we'll let the API fetch chamas too, but you could pass them:
    # chamas_list = [{'id': ch.id, 'name': ch.name} for ch in user_chamas]
    return render_template('contributions/list.html') # Assuming your template is here

# --- API Routes ---

# GET Initial Data (Chamas, Contributions, Penalties)
@contributions_bp.route('/api/data')
@login_required
def get_contribution_data():
    try:
        # Determine which chamas the user has access to (e.g., admin of)
        # Adjust this logic based on your permission model (members vs admins)
        # Assuming current_user.chamas gives chamas the user is associated with (e.g., admin)
        accessible_chama_ids = [chama.id for chama in current_user.chamas]

        if not accessible_chama_ids:
             return jsonify({"chamas": [], "contributions": [], "penalties": []})

        # Fetch Chamas details
        chamas = Chama.query.filter(Chama.id.in_(accessible_chama_ids)).all()
        chamas_list = [{'id': ch.id, 'name': ch.name} for ch in chamas]

        # Fetch Contributions for these chamas
        contributions = Contribution.query.filter(Contribution.chama_id.in_(accessible_chama_ids)).\
            options(db.joinedload(Contribution.user), db.joinedload(Contribution.chama)).\
            order_by(Contribution.payment_date.desc()).all()

        # Fetch Penalties for these chamas
        penalties = Penalty.query.filter(Penalty.chama_id.in_(accessible_chama_ids)).\
             options(db.joinedload(Penalty.user), db.joinedload(Penalty.chama)).\
             order_by(Penalty.imposed_date.desc()).all()

        return jsonify({
            "chamas": chamas_list,
            "contributions": [serialize_contribution(c) for c in contributions],
            "penalties": [serialize_penalty(p) for p in penalties]
        })
    except Exception as e:
        # Log the error e
        print(f"Error fetching contribution data: {e}")
        abort(500, description="Internal server error fetching data.")


# GET Members for a Specific Chama
@contributions_bp.route('/api/chamas/<int:chama_id>/members', methods=['GET'])
@login_required
def get_chama_members(chama_id):
    """
    Fetches members associated with a specific chama.
    Currently defined as users who are admins of the chama
    OR have contributions/penalties recorded for the chama.
    Requires the current user to be an admin of the chama.
    """
    try:
        # 1. Fetch the Chama
        chama = Chama.query.get(chama_id)
        if not chama:
            # If chama doesn't exist, return 404
            abort(404, description=f"Chama with ID {chama_id} not found.")

        # 2. Permission check: Ensure current_user is an admin of this chama
        # This aligns with the assumption from your previous code snippets that
        # current_user.chamas represents the chamas they administer or manage.
        # Adjust logic if membership viewing permissions are different (e.g., any member can see).
        if chama not in current_user.chamas:
             # If user is not an admin of this chama, deny access
             abort(403, description="You do not have permission to view members of this Chama.")

        # 3. Fetch users associated with this chama
        # This approach gets users who are admins OR have transactions in this chama.
        # It might miss members who have just joined and have no records/aren't admins.
        # A dedicated 'chama_members' relationship between User and Chama would be more accurate for all members.

        # Get IDs of users who are admins of this chama using the association table
        admin_user_ids = db.session.query(chama_admins.c.user_id).filter(chama_admins.c.chama_id == chama_id)

        # Get IDs of users who have contributions in this chama
        contribution_user_ids = db.session.query(Contribution.user_id).filter_by(chama_id=chama_id).distinct()

        # Get IDs of users who have penalties in this chama
        penalty_user_ids = db.session.query(Penalty.user_id).filter_by(chama_id=chama_id).distinct()

        # Combine all unique user IDs from these sources using union
        # The query will select users whose ID is in the combined list of admin, contribution, or penalty user IDs.
        all_member_ids_query = admin_user_ids.union(contribution_user_ids).union(penalty_user_ids)

        # Fetch the User objects for these unique IDs
        # Filter User.id to be in the combined list of IDs and order by full name
        members = User.query.filter(User.id.in_(all_member_ids_query)).order_by(User.full_name).all()

        # 4. Serialize the members to the format expected by the frontend
        # Frontend expects a list of dictionaries: [{'id': ..., 'name': ...}, ...]
        members_list = [{'id': m.id, 'name': m.full_name} for m in members]

        # 5. Return JSON response
        return jsonify(members_list)

    except Exception as e:
        # Log the error for debugging purposes (important in production)
        print(f"Error fetching members for chama {chama_id}: {e}")
        # Return a generic internal server error response
        # Using abort(500) is standard for internal errors
        abort(500, description="Internal server error fetching members.")


# POST Add Contribution
@contributions_bp.route('/api/contributions', methods=['POST'])
@login_required
def add_contribution():
    data = request.get_json()
    if not data:
        abort(400, description="Missing data")

    # Basic Validation (add more as needed)
    required_fields = ['chamaId', 'userId', 'amount', 'date', 'method', 'status']
    if not all(field in data for field in required_fields):
         abort(400, description="Missing required fields")

    # Check if user and chama exist and if user belongs to chama (add this check)
    # Check if current_user has permission to add for this chamaId
    chama = Chama.query.get_or_404(data['chamaId'])
    if chama not in current_user.chamas: # Example permission check based on admin relationship
         abort(403, description="Permission denied for this Chama.")
    user = User.query.get_or_404(data['userId']) # Ensure the selected user exists

    try:
        # Frontend sends userId, so we use that.
        # The 'member' name sent from frontend can be ignored or used for logging,
        # but the canonical link is via user_id.
        new_contribution = Contribution(
            amount=data['amount'],
            payment_date=datetime.strptime(data['date'], '%Y-%m-%d'),
            status=data['status'],
            method=data['method'],
            user_id=data['userId'], # Use the userId from the form
            chama_id=data['chamaId'],
            reference_number=data.get('reference_number'),
            notes=data.get('notes')
        )
        db.session.add(new_contribution)
        db.session.commit()
        # Need to reload user/chama relationships for serialization after commit
        db.session.refresh(new_contribution)
        return jsonify(serialize_contribution(new_contribution)), 201 # Return the created object
    except Exception as e:
        db.session.rollback()
        print(f"Error adding contribution: {e}")
        # Provide a more informative error if possible (e.g., validation failed)
        abort(500, description="Failed to add contribution.")


# PUT Update Contribution
@contributions_bp.route('/api/contributions/<int:contribution_id>', methods=['PUT'])
@login_required
def update_contribution(contribution_id):
    contribution = Contribution.query.get_or_404(contribution_id)
    data = request.get_json()
    if not data:
        abort(400, description="Missing data")

    # Permission check: Ensure current_user can edit this contribution
    # Example check: Is the user an admin of the chama the contribution belongs to?
    if contribution.chama not in current_user.chamas:
        abort(403, description="Permission denied.")

    try:
        # Update fields from data, providing current value as default if key missing
        contribution.amount = data.get('amount', contribution.amount)
        if 'date' in data:
             contribution.payment_date = datetime.strptime(data['date'], '%Y-%m-%d')
        contribution.status = data.get('status', contribution.status)
        contribution.method = data.get('method', contribution.method)
        contribution.reference_number = data.get('reference_number', contribution.reference_number)
        contribution.notes = data.get('notes', contribution.notes)
        # Ideally, prevent changing user_id or chama_id via this route or add specific checks

        db.session.commit()
        db.session.refresh(contribution) # Refresh to get potentially updated relationships (like member name if User model changes)
        return jsonify(serialize_contribution(contribution))
    except Exception as e:
        db.session.rollback()
        print(f"Error updating contribution {contribution_id}: {e}")
        abort(500, description="Failed to update contribution.")


# DELETE Contribution
@contributions_bp.route('/api/contributions/<int:contribution_id>', methods=['DELETE'])
@login_required
def delete_contribution(contribution_id):
    contribution = Contribution.query.get_or_404(contribution_id)

     # Permission check: Is the user an admin of the chama the contribution belongs to?
    if contribution.chama not in current_user.chamas:
        abort(403, description="Permission denied.")

    try:
        db.session.delete(contribution)
        db.session.commit()
        # Return a success message or just a 204 No Content
        return jsonify({"success": True, "message": "Contribution deleted"}), 200
        # return '', 204 # Alternative: No Content
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting contribution {contribution_id}: {e}")
        abort(500, description="Failed to delete contribution.")


# POST Add Penalty
@contributions_bp.route('/api/penalties', methods=['POST'])
@login_required
def add_penalty():
    data = request.get_json()
    if not data:
        abort(400, description="Missing data")

    required_fields = ['chamaId', 'userId', 'amount', 'reason', 'date', 'status']
    if not all(field in data for field in required_fields):
         abort(400, description="Missing required fields for penalty")

    # Check if user and chama exist and if user belongs to chama (add this check)
    # Check if current_user has permission to add for this chamaId
    chama = Chama.query.get_or_404(data['chamaId'])
    if chama not in current_user.chamas: # Example permission check
         abort(403, description="Permission denied for this Chama.")
    user = User.query.get_or_404(data['userId']) # Ensure the selected user exists


    try:
        new_penalty = Penalty(
            amount=data['amount'],
            reason=data['reason'], # Store detailed reason here
            penalty_type=data.get('penalty_type', 'Other'), # Get type or default 'Other'
            imposed_date=datetime.strptime(data['date'], '%Y-%m-%d'),
            status=data['status'],
            user_id=data['userId'], # Use the userId from the form
            chama_id=data['chamaId'],
            # Handle optional resolved_date
            resolved_date=datetime.strptime(data['resolved_date'], '%Y-%m-%d') if data.get('resolved_date') else None
        )
        db.session.add(new_penalty)
        db.session.commit()
        db.session.refresh(new_penalty)
        return jsonify(serialize_penalty(new_penalty)), 201 # Return the created object
    except Exception as e:
        db.session.rollback()
        print(f"Error adding penalty: {e}")
        abort(500, description="Failed to add penalty.")


# PUT Update Penalty
@contributions_bp.route('/api/penalties/<int:penalty_id>', methods=['PUT'])
@login_required
def update_penalty(penalty_id):
    penalty = Penalty.query.get_or_404(penalty_id)
    data = request.get_json()
    if not data:
        abort(400, description="Missing data")

    # Permission check
    if penalty.chama not in current_user.chamas: # Example permission check
        abort(403, description="Permission denied.")

    try:
        penalty.amount = data.get('amount', penalty.amount)
        penalty.reason = data.get('reason', penalty.reason)
        penalty.penalty_type = data.get('penalty_type', penalty.penalty_type)
        if 'date' in data:
             penalty.imposed_date = datetime.strptime(data['date'], '%Y-%m-%d')
        penalty.status = data.get('status', penalty.status)

        # Handle resolved_date update
        if 'resolved_date' in data:
            # If data['resolved_date'] is provided and not empty, parse it
            if data['resolved_date']:
                penalty.resolved_date = datetime.strptime(data['resolved_date'], '%Y-%m-%d')
            else:
                # If provided but empty (e.g., user cleared the field), set to None
                penalty.resolved_date = None
        # If 'resolved_date' is not in data, leave the existing value


        db.session.commit()
        db.session.refresh(penalty)
        return jsonify(serialize_penalty(penalty))
    except Exception as e:
        db.session.rollback()
        print(f"Error updating penalty {penalty_id}: {e}")
        abort(500, description="Failed to update penalty.")


# DELETE Penalty
@contributions_bp.route('/api/penalties/<int:penalty_id>', methods=['DELETE'])
@login_required
def delete_penalty(penalty_id):
    penalty = Penalty.query.get_or_404(penalty_id)

    # Permission check
    if penalty.chama not in current_user.chamas: # Example permission check
        abort(403, description="Permission denied.")

    try:
        db.session.delete(penalty)
        db.session.commit()
        return jsonify({"success": True, "message": "Penalty deleted"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting penalty {penalty_id}: {e}")
        abort(500, description="Failed to delete penalty.")

# Note: You will likely need to register this blueprint in your app factory
# e.g., app.register_blueprint(contributions_bp)........



# In your app/blueprints/contributions/routes.py

import io
from flask import Response, send_file, request, jsonify, abort # Ensure send_file and Response are imported
from flask_login import login_required, current_user
from app.extensions import db
from app.models.contribution import Contribution, Penalty
from app.models.chama import Chama
from app.models.user import User
from datetime import datetime
from sqlalchemy import distinct
import pandas as pd

# In your app/blueprints/contributions/routes.py

import io
from flask import Response, send_file, request, jsonify, abort # Ensure send_file and Response are imported
from flask_login import login_required, current_user
from app.extensions import db
from app.models.contribution import Contribution, Penalty
from app.models.chama import Chama
from app.models.user import User
from datetime import datetime
from sqlalchemy import distinct
import pandas as pd

# Import Openpyxl components
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.pagebreak import Break
from reportlab.platypus import Table, SimpleDocTemplate, Paragraph, Spacer, PageBreak, Flowable


# ... your existing blueprint definition and helper functions (serialize_contribution, serialize_penalty) ...
# ... your get_filtered_data_for_export function (ensure it's accessible) ...


# Define colors (using AARRGGBB hex codes for Openpyxl)
COLOR_PRIMARY = "FF1A4D6C"      # Deep blue (AARRGGBB)
COLOR_SECONDARY = "FF00A896"    # Teal accent (AARRGGBB)
COLOR_ACCENT = "FFF9A826"       # Golden accent (AARRGGBB)
COLOR_LIGHT_BG = "FFF5F9FC"     # Light background (AARRGGBB)
COLOR_TEXT = "FF333333"         # Main text (AARRGGBB)
COLOR_LIGHT_TEXT = "FFFFFFFF"     # Light text (used on dark backgrounds) (AARRGGBB)
COLOR_MUTED_TEXT = "FF7A8C98"     # Muted text (AARRGGBB)
COLOR_RED = "FFE53E3E"          # Red for overdue/active penalties (AARRGGBB)
COLOR_GREEN = "FF38A169"        # Green for paid contributions/penalties (AARRGGBB)
COLOR_YELLOW = "FFD69E2E"       # Yellow for pending (AARRGGBB)

# Also update colors used in borders if they were RRGGBB
COLOR_BORDER_GRAY = "FFDDDDDD" # Border gray (AARRGGBB)
COLOR_BORDER_LIGHT_GRAY = "FFEEEEEE" # Lighter border gray (AARRGGBB)


# Define styles using openpyxl.styles (referencing the updated colors)
FONT_TITLE = Font(name='Calibri', size=18, bold=True, color=COLOR_PRIMARY) # Uses updated COLOR_PRIMARY
FONT_SUBTITLE = Font(name='Calibri', size=12, color=COLOR_SECONDARY) # Uses updated COLOR_SECONDARY
FONT_HEADER = Font(name='Calibri', size=10, bold=True, color=COLOR_LIGHT_TEXT) # Uses updated COLOR_LIGHT_TEXT
FONT_BODY = Font(name='Calibri', size=9, color=COLOR_TEXT) # Uses updated COLOR_TEXT
FONT_MUTED = Font(name='Calibri', size=9, color=COLOR_MUTED_TEXT) # Uses updated COLOR_MUTED_TEXT

FILL_HEADER = PatternFill(start_color=COLOR_PRIMARY, end_color=COLOR_PRIMARY, fill_type="solid") # Uses updated COLOR_PRIMARY
FILL_ROW_ALT = PatternFill(start_color=COLOR_LIGHT_BG, end_color=COLOR_LIGHT_BG, fill_type="solid") # Uses updated COLOR_LIGHT_BG

# Define Border Sides
SIDE_THIN = Side(style='thin', color=COLOR_BORDER_GRAY)
SIDE_MEDIUM = Side(style='medium', color=COLOR_BORDER_GRAY)

# Define complete Border objects
BORDER_THIN_ALL = Border(left=SIDE_THIN, right=SIDE_THIN, top=SIDE_THIN, bottom=SIDE_THIN)
BORDER_OUTER_MEDIUM = Border(left=SIDE_MEDIUM, right=SIDE_MEDIUM, top=SIDE_MEDIUM, bottom=SIDE_MEDIUM)
# We'll build specific borders as needed during the cell iteration


# Helper function to get filtered data (you might already have similar logic)
def get_filtered_data_for_export(chama_id, search_term, data_type):
    # Adjust this to match your filtering logic and access control
    # Example permission check (assuming current_user is available and has chamas relationship)
    # Make sure this logic is robust for 'all' chama_id and different user roles
    accessible_chama_ids = [chama.id for chama in current_user.chamas] if current_user.is_authenticated and hasattr(current_user, 'chamas') else []

    if chama_id != 'all':
        try:
            requested_chama_id = int(chama_id)
            if requested_chama_id not in accessible_chama_ids and current_user.role != 'super_admin':
                 # User requested a specific chama they don't manage and aren't super admin
                 return [] # Or raise 403 if preferred
        except ValueError:
            # Invalid chamaId format, return empty data
            return []


    query = None
    if data_type == 'contributions':
        query = Contribution.query.options(db.joinedload(Contribution.user), db.joinedload(Contribution.chama))
        if chama_id != 'all':
            query = query.filter(Contribution.chama_id == int(chama_id))
        else:
             # If 'all' chamas, filter by chamas the user *can* see (unless super admin)
             if current_user.role != 'super_admin':
                 query = query.filter(Contribution.chama_id.in_(accessible_chama_ids))

        # Add search term filtering if applicable
        if search_term:
             # Assuming 'member' in serialized data comes from User.full_name
             query = query.join(User, Contribution.user_id == User.id).filter(User.full_name.ilike(f'%{search_term}%'))

        query = query.order_by(Contribution.payment_date.desc())
        # Ensure serialization provides 'chamaName'
        return [serialize_contribution(c) for c in query.all()]

    elif data_type == 'penalties':
        query = Penalty.query.options(db.joinedload(Penalty.user), db.joinedload(Penalty.chama))
        if chama_id != 'all':
            query = query.filter(Penalty.chama_id == int(chama_id))
        else:
             # If 'all' chamas, filter by chamas the user *can* see (unless super admin)
             if current_user.role != 'super_admin':
                 query = query.filter(Penalty.chama_id.in_(accessible_chama_ids))

         # Add search term filtering if applicable
        if search_term:
             # Assuming 'member' in serialized data comes from User.full_name
             query = query.join(User, Penalty.user_id == User.id).filter(
                 (User.full_name.ilike(f'%{search_term}%')) |
                 (Penalty.reason.ilike(f'%{search_term}%')) # Example search on member or reason
            )

        query = query.order_by(Penalty.imposed_date.desc())
        # Ensure serialization provides 'chamaName'
        return [serialize_penalty(p) for p in query.all()]

    return [] # Invalid data type or no access to any data


@contributions_bp.route('/api/export/excel', methods=['GET'])
@login_required
def export_excel():
    chama_id = request.args.get('chamaId', 'all')
    search_term = request.args.get('searchTerm', '')
    data_type = request.args.get('dataType', 'contributions') # Default to contributions

    # Fetch the data using your existing function (handles permissions and filtering)
    data = get_filtered_data_for_export(chama_id, search_term, data_type)

    # Fetch the Chama object for report details (only if a specific chama was requested)
    chama = None
    if chama_id and chama_id != 'all':
        try:
            # Fetch the chama object, don't use get_or_404 here as get_filtered_data_for_export
            # should handle the authorization check. This is just for display name.
            chama = Chama.query.get(int(chama_id))
        except ValueError:
             pass # chama remains None if ID is invalid


    # Handle case where no data is found. get_filtered_data_for_export should return []
    # if no data or no permission.
    if not data:
         # Improve error message based on whether a specific chama was requested
         if chama_id != 'all':
             if not chama:
                 # This case should ideally be caught by get_filtered_data_for_export
                 abort(404, description=f"Chama with ID {chama_id} not found or you do not have access.")
             else:
                 # Chama found, but no records matching criteria or user not authorized for this chama
                 abort(404, description=f"No {data_type} found for {chama.name} matching your criteria.")
         elif search_term:
             # No specific chama, but search term applied across accessible chamas
             abort(404, description=f"No {data_type} found across your accessible chamas matching your search criteria.")
         else:
             # No specific chama, no search term, but no data returned across accessible chamas
             abort(404, description=f"No {data_type} records found in your accessible chamas.")


    # --- Excel Generation Logic using Openpyxl ---
    workbook = Workbook()
    sheet = workbook.active

    # Rename the default sheet (ensure name is valid for Excel)
    safe_sheet_title = ''.join(c if c.isalnum() or c in (' ', '-') else '' for c in data_type).replace(' ', '_')
    sheet.title = safe_sheet_title[:31] # Excel sheet name max length is 31

    # --- Add Report Title ---
    report_title_text = f"{data_type.capitalize()} Report"
    if chama:
        report_title_text += f" for {chama.name}"
    else:
        report_title_text += " for All Accessible Chamas" # Clarify 'All' means accessible ones

    sheet['A1'] = report_title_text
    sheet['A1'].font = FONT_TITLE
    # Merge cells for the title (e.g., across the first 5 columns or number of data columns)
    # Use the actual number of data columns for merge width
    num_data_columns = len(data[0]) if data else 5 # Default merge 5 if no data
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(num_data_columns, 5)) # Merge across data columns or at least 5
    sheet['A1'].alignment = Alignment(horizontal='left', vertical='center') # Align merged cell


    # --- Add Report Information (Subtitle and Filters) ---
    info_start_row = 3
    sheet[f'A{info_start_row}'] = f"Generated on: {datetime.now().strftime('%B %d, %Y %H:%M')}"
    sheet[f'A{info_start_row}'].font = FONT_SUBTITLE
    sheet[f'A{info_start_row}'].alignment = Alignment(horizontal='left')

    sheet[f'A{info_start_row + 1}'] = f"Chama: {chama.name if chama else 'All Accessible Chamas'}"
    sheet[f'A{info_start_row + 1}'].font = FONT_MUTED

    sheet[f'A{info_start_row + 2}'] = f"Search Term: {search_term if search_term else 'None'}"
    sheet[f'A{info_start_row + 2}'].font = FONT_MUTED

    sheet[f'A{info_start_row + 3}'] = f"Data Type: {data_type.capitalize()}"
    sheet[f'A{info_start_row + 3}'].font = FONT_MUTED

    sheet[f'A{info_start_row + 4}'] = f"Number of Records: {len(data)}"
    sheet[f'A{info_start_row + 4}'].font = FONT_MUTED


    # Add some space before the table
    DATA_START_ROW = info_start_row + 6 # Start the data table after info and space


    # --- Prepare DataFrame and Headers ---
    # Ensure dataframe has the desired columns and names for the report
    df = pd.DataFrame(data)

    # Define the desired order and header text for the columns
    ordered_headers = [] # List of desired header strings
    df_columns_map = {}  # Mapping from desired header to original df column name

    if data_type == 'contributions':
         ordered_headers = ['Payment Date', 'Chama', 'Member', 'Amount', 'Status', 'Method', 'Reference', 'Notes']
         # Map desired headers to the keys in your serialized data dictionaries
         df_columns_map = {
             'Payment Date': 'date',
             'Chama': 'chamaName',
             'Member': 'member',
             'Amount': 'amount',
             'Status': 'status',
             'Method': 'method',
             'Reference': 'reference_number',
             'Notes': 'notes'
         }
         # Select and reorder columns in the DataFrame
         # Use a list of keys from df_columns_map to select columns in the correct order
         df = df[[df_columns_map[h] for h in ordered_headers]]


    elif data_type == 'penalties':
         ordered_headers = ['Imposed Date', 'Chama', 'Member', 'Amount', 'Reason', 'Type', 'Status', 'Resolved Date']
         df_columns_map = {
             'Imposed Date': 'date',
             'Chama': 'chamaName',
             'Member': 'member',
             'Amount': 'amount',
             'Reason': 'reason',
             'Type': 'penalty_type',
             'Status': 'status',
             'Resolved Date': 'resolved_date'
         }
         # Select and reorder columns in the DataFrame
         df = df[[df_columns_map[h] for h in ordered_headers]]

    # --- Write Table Headers ---
    # Write headers starting from DATA_START_ROW
    header_row_index = DATA_START_ROW
    for col_index, header_text in enumerate(ordered_headers, start=1): # Use the ordered_headers list
        cell = sheet.cell(row=header_row_index, column=col_index)
        cell.value = header_text
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        # Borders will be applied in the main border loop
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)


    # --- Write Data Rows ---
    for row_index, row_data in df.iterrows(): # Iterate over DataFrame rows
        excel_row = DATA_START_ROW + 1 + row_index # +1 for header row

        # Apply alternating row background fill
        row_fill = None
        if row_index % 2 != 0: # Row index 0 is header, data starts at index 0 in df
             row_fill = FILL_ROW_ALT # Apply fill to the 2nd, 4th, 6th data rows (index 1, 3, 5 in df)

        for col_index, header_text in enumerate(ordered_headers, start=1): # Iterate using ordered headers to get correct column name
            cell = sheet.cell(row=excel_row, column=col_index)
            # Get value from the DataFrame row using the original column name
            original_col_name = df_columns_map[header_text]
            value = row_data[original_col_name]

            # Apply formatting based on header text
            if header_text == 'Amount':
                cell.value = float(value) if pd.notna(value) else None # Ensure it's a number
                cell.number_format = '#,##0.00' # Currency format
                cell.alignment = Alignment(horizontal='right')
            elif 'Date' in header_text: # Check if header contains 'Date'
                 try:
                     # Attempt to parse date string into a datetime object for Excel
                     if isinstance(value, str) and value: # Check if value is a non-empty string
                         date_obj = datetime.strptime(value, '%Y-%m-%d')
                         cell.value = date_obj
                     elif isinstance(value, datetime):
                          cell.value = value # Already a datetime object
                     else:
                         cell.value = None # Handle None or other cases

                     cell.number_format = 'yyyy-mm-dd' # Date format
                     cell.alignment = Alignment(horizontal='center') # Center align dates
                 except (ValueError, TypeError):
                     cell.value = value # Keep original value if parsing fails (might be 'N/A')
                     cell.alignment = Alignment(horizontal='left') # Left align non-date strings

            elif header_text == 'Status':
                 cell.value = value
                 # Optional: Apply text color based on status
                 # FIX: Font colors use AARRGGBB
                 if data_type == 'contributions':
                     if value == 'Paid': cell.font = Font(color=COLOR_GREEN)
                     elif value == 'Pending': cell.font = Font(color=COLOR_YELLOW)
                     elif value == 'Overdue': cell.font = Font(color=COLOR_RED)
                     # No else needed, default font is applied by row fill logic

                 elif data_type == 'penalties':
                      if value == 'Active': cell.font = Font(color=COLOR_RED)
                      elif value == 'Waived': cell.font = Font(color=COLOR_MUTED_TEXT)
                      elif value == 'Paid': cell.font = Font(color=COLOR_GREEN)
                      # No else needed

                 cell.alignment = Alignment(horizontal='center') # Center align status

            else: # Default styling for other text columns
                cell.value = value
                cell.font = FONT_BODY
                cell.alignment = Alignment(horizontal='left', wrap_text=True) # Left align text, allow wrap

            # Apply alternating row fill
            if row_fill:
                 cell.fill = row_fill

            # Borders will be applied in the main border loop


    # --- Apply Table Borders ---
    # Define the range of the data table (including headers)
    table_start_row = DATA_START_ROW
    table_end_row = sheet.max_row
    table_start_col = 1
    table_end_col = sheet.max_column

    # Apply borders to all cells in the range
    for r_idx in range(table_start_row, table_end_row + 1):
        for c_idx in range(table_start_col, table_end_col + 1):
            cell = sheet.cell(row=r_idx, column=c_idx)

            # Build border based on position (inner thin, outer medium)
            border = Border()
            # Left border
            if c_idx == table_start_col: border.left = SIDE_MEDIUM
            else: border.left = SIDE_THIN
            # Right border
            if c_idx == table_end_col: border.right = SIDE_MEDIUM
            else: border.right = SIDE_THIN
            # Top border
            if r_idx == table_start_row: border.top = SIDE_MEDIUM
            else: border.top = SIDE_THIN
            # Bottom border
            if r_idx == table_end_row: border.bottom = SIDE_MEDIUM
            else: border.bottom = SIDE_THIN

            # Apply the constructed border to the cell
            cell.border = border


    # --- Adjust Column Widths ---
    # Estimate column widths based on header text length (basic approach)
    # For more accurate auto-sizing, you might need a different library or more complex logic
    for col_index, header_text in enumerate(ordered_headers, start=1):
        # Estimate width based on header length + some padding
        header_width = len(str(header_text)) * 1.2 # Rough estimate
        # Set a minimum sensible width
        estimated_width = max(header_width, 12) # Min width 12

        # Specific adjustments for known columns
        if header_text == 'Notes': estimated_width = max(estimated_width, 25) # Wider for notes
        if 'Date' in header_text: estimated_width = max(estimated_width, 14) # Specific width for dates
        if header_text == 'Amount': estimated_width = max(estimated_width, 12) # Specific width for amount
        if header_text == 'Reason': estimated_width = max(estimated_width, 20) # Reason might be long

        col_letter = get_column_letter(col_index)
        sheet.column_dimensions[col_letter].width = estimated_width

    # --- Optional: Add an official Excel Table ---
    # This adds sorting/filtering features within Excel itself
    # Requires defining the table range
    # Note: TableStyleElement import was removed due to error
    # If you want to use official tables, you'll need openpyxl 3.0+ and
    # apply styles via excel_table.styleInfo = TableStyleInfo(...)
    # Keeping this commented out as it was previously causing issues.
    # if sheet.max_row > DATA_START_ROW: # Only add if there are data rows + header
    #     table_range = f"A{DATA_START_ROW}:{get_column_letter(sheet.max_column)}{sheet.max_row}"
    #     excel_table_name = f"{data_type.capitalize()}Table"
    #     # Ensure table name is valid (starts with letter, no spaces/special chars)
    #     excel_table_name = ''.join(c for c in excel_table_name if c.isalnum()).capitalize() + "Table"
    #
    #     excel_table = Table(displayName=excel_table_name, ref=table_range)
    #
    #     # Apply a basic built-in style (optional, requires office support)
    #     # excel_table.styleInfo = TableStyleInfo(name="TableStyleMedium9", showFirstColumn=False,
    #     #                                         showLastColumn=False, showRowStripes=True, showTotalRow=False) # Example style
    #
    #     # Add the table to the sheet
    #     try:
    #         sheet.add_table(excel_table)
    #     except ValueError as e:
    #          print(f"Error adding Excel table: {e}. This might happen if the range is invalid or table name exists.")
    #          # Continue without adding the official table if it fails


    # --- Add Footer Note ---
    footer_note_row = sheet.max_row + 2
    sheet[f'A{footer_note_row}'] = "Report generated by ChamaSmart Software."
    sheet[f'A{footer_note_row}'].font = FONT_MUTED
    # Merge across the same number of columns as the data table + maybe a bit more
    sheet.merge_cells(start_row=footer_note_row, start_column=1, end_row=footer_note_row, end_column=max(sheet.max_column, 5))
    sheet[f'A{footer_note_row}'].alignment = Alignment(horizontal='left') # Align footer note


    # --- Save Workbook ---
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    # --- Prepare the Response ---
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    # Create a safe filename slug from chama name
    chama_name_slug = ''.join(c if c.isalnum() or c in (' ', '-') else '' for c in (chama.name if chama else 'AllChamas')).replace(' ', '_') # Use 'AllChamas' slug
    report_name_slug = data_type.lower()
    filename = f"{chama_name_slug}_{report_name_slug}_Report_{timestamp}.xlsx"


    response = Response(output.read(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response.headers.set('Content-Disposition', 'attachment', filename=filename)

    return response

# ... rest of your routes.py ...

# Define color scheme - brand colors (reuse from your example)
PRIMARY_COLOR = '#1A4D6C'      # Deep blue
SECONDARY_COLOR = '#00A896'    # Teal accent
ACCENT_COLOR = '#F9A826'       # Golden accent
LIGHT_BG = '#F5F9FC'           # Light background
TEXT_COLOR = '#333333'         # Main text
LIGHT_TEXT = '#FFFFFF'         # Light text (used on dark backgrounds)
MUTED_TEXT = '#7A8C98'         # Muted text
RED_COLOR = '#E53E3E'          # Red for overdue/active penalties
GREEN_COLOR = '#38A169'        # Green for paid contributions/penalties
YELLOW_COLOR = '#D69E2E'       # Yellow for pending

# Custom flowable for horizontal line with gradient effect (reuse from your example)
class SolidLine(Flowable):
    def __init__(self, width, height=1, color=PRIMARY_COLOR):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color

    def draw(self):
        self.canv.setFillColor(colors.HexColor(self.color))
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0) # stroke=0 means no border


# Initialize enhanced styles
styles = getSampleStyleSheet()

# Premium title style (reuse/adapt)
styles.add(ParagraphStyle(
    name='ReportTitle', # Renamed from PremiumTitle
    fontName='Helvetica-Bold',
    fontSize=24, # Slightly smaller than example title
    alignment=1,  # Center alignment
    spaceAfter=10,
    textColor=colors.HexColor(PRIMARY_COLOR)
))

# Add more custom styles (reuse/adapt)
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
    spaceAfter=8, # Slightly less space after
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

# Style for table header text
styles.add(ParagraphStyle(
    name='TableHeaderText',
    fontName='Helvetica-Bold',
    fontSize=9, # Smaller font for table headers
    alignment=0, # Left align header text
    textColor=colors.white,
    spaceBefore=0,
    spaceAfter=0,
    leading=12 # Line spacing
))

# Style for table cell text
styles.add(ParagraphStyle(
    name='TableCellText',
    fontName='Helvetica',
    fontSize=8, # Smaller font for table cells
    alignment=0, # Left align cell text
    textColor=colors.HexColor(TEXT_COLOR),
    spaceBefore=0,
    spaceAfter=0,
    leading=10 # Line spacing
))

# Style for table cell text - Right Aligned (e.g., Amount)
styles.add(ParagraphStyle(
    name='TableCellTextRight',
    fontName='Helvetica',
    fontSize=8,
    alignment=2, # Right align cell text
    textColor=colors.HexColor(TEXT_COLOR),
    spaceBefore=0,
    spaceAfter=0,
    leading=10
))
styles.add(ParagraphStyle(
    name='ReportSubtitle',
    fontName='Helvetica-Bold',
    fontSize=16,            # bumped up from 14
    alignment=1,            # center
    textColor=colors.HexColor(PRIMARY_COLOR),
    leading=20,             # a bit more line‐height
    spaceAfter=30,          # more space below
    wordWrap='LTR',
    allowWidows=1,
    allowOrphans=1,
))
# Create enhanced header and footer function (adapt from your example)
def header_footer(canvas, doc, data_type, chama):
    # Pass data_type and chama to customize header/footer
    canvas.saveState()
    page_width, page_height = doc.pagesize # Use doc.pagesize for margins calculation

    # HEADER SECTION
    # Create modern header bar
    header_height = 55
    canvas.setFillColor(colors.HexColor(PRIMARY_COLOR))
    canvas.rect(0, page_height - header_height, page_width, header_height, fill=1, stroke=0)

    # Add accent strip below header
    canvas.setFillColor(colors.HexColor(ACCENT_COLOR))
    canvas.rect(0, page_height - header_height - 3, page_width, 3, fill=1, stroke=0)

    # Add logo and company name with premium styling
    # Logo placeholder (replace with actual logo drawing or Image flowable)
    logo_size = 35
    logo_margin = 45
    canvas.setFillColor(colors.white)
    # Simple rounded rect placeholder for logo
    canvas.roundRect(logo_margin, page_height - header_height/2 - logo_size/2 + 5, logo_size, logo_size, 5, fill=1)

    # Add CS icon (placeholder)
    canvas.setFillColor(colors.HexColor(SECONDARY_COLOR))
    canvas.setFont('Helvetica-Bold', 20)
    canvas.drawCentredString(logo_margin + logo_size/2, page_height - header_height/2 - logo_size/2 + 5 + 12, "CS") # Adjust position

    # Add company name with modern typography
    canvas.setFillColor(colors.white)
    canvas.setFont('Helvetica-Bold', 18)
    canvas.drawString(logo_margin + logo_size + 10, page_height - header_height/2 + 5, "CHAMASMART") # Adjust position

    # Add tagline
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor(LIGHT_BG)) # Use a light color for tagline on dark background
    canvas.drawString(logo_margin + logo_size + 10, page_height - header_height/2 - 7, "SMART FINANCIAL MANAGEMENT") # Adjust position


    # — Document type badge —
    badge_text = f"{data_type.upper()} REPORT" # Dynamic badge text
    badge_font  = "Helvetica-Bold"
    badge_size  = 9
    badge_pad_x = 8   # horizontal padding
    badge_pad_y = 4   # vertical padding
    text_w = canvas.stringWidth(badge_text, badge_font, badge_size)
    badge_w = text_w + badge_pad_x * 2
    badge_h = badge_size + badge_pad_y * 2

    # position it 45pt from right edge, vertically centered in the header bar area
    # Adjusted position to be within the colored header bar
    bx = page_width - doc.rightMargin - badge_w
    by = page_height - header_height + (header_height - badge_h) / 2

    # optional shadow for depth
    canvas.setFillColor(colors.HexColor("#000000"), alpha=0.15)
    canvas.roundRect(bx+1.5, by-1.5, badge_w, badge_h, badge_h/2, fill=1, stroke=0) # Adjusted shadow offset

    # fill the badge
    canvas.setFillColor(colors.HexColor(ACCENT_COLOR))
    canvas.roundRect(bx, by, badge_w, badge_h, badge_h/2, fill=1, stroke=0)

    # draw the label
    canvas.setFont(badge_font, badge_size)
    canvas.setFillColor(colors.white)
    canvas.drawString(bx + badge_pad_x, by + badge_pad_y, badge_text)


    # — Page number pill —
    # Positioned relative to the right margin and slightly above the footer area
    page_text = f"{doc.page}"
    page_font = "Helvetica-Bold"
    page_size = 8
    page_pad  = 4
    p_w = canvas.stringWidth(page_text, page_font, page_size) + page_pad*2
    p_h = page_size + page_pad*2
    page_bottom_margin = 20 # Space from bottom of page

    # place it 45pt from right edge, 20pt from bottom edge
    px = page_width - doc.rightMargin - p_w
    py = page_bottom_margin

    # page-pill background
    canvas.setFillColor(colors.HexColor(SECONDARY_COLOR))
    canvas.roundRect(px, py, p_w, p_h, p_h/2, fill=1, stroke=0)

    # page number text
    canvas.setFont(page_font, page_size)
    canvas.setFillColor(colors.white)
    canvas.drawCentredString(px + p_w/2, py + page_pad, page_text)


    # FOOTER SECTION
    footer_height = 40
    canvas.setFillColor(colors.HexColor(LIGHT_BG))
    canvas.rect(0, 0, page_width, footer_height, fill=1, stroke=0)

    # Add accent line above footer
    canvas.setFillColor(colors.HexColor(SECONDARY_COLOR))
    canvas.rect(0, footer_height, page_width, 1, fill=1, stroke=0)

    # Add footer content with enhanced layout
    canvas.setFillColor(colors.HexColor(MUTED_TEXT))
    canvas.setFont('Helvetica', 8)
    current_date = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Left side info (Chama Name, Generated Date)
    # --- FIX: Handle chama being None ---
    chama_name_display = chama.name if chama else 'All Chamas'
    canvas.drawString(doc.leftMargin, 25, f"Chama: {chama_name_display}") # Safely access chama.name
    # --- END FIX ---
    canvas.drawString(doc.leftMargin, 15, f"Generated: {current_date}")

    # Center info (Report Source/Copyright)
    canvas.setFont('Helvetica-Bold', 9)
    canvas.setFillColor(colors.HexColor(PRIMARY_COLOR))
    canvas.drawCentredString(page_width/2, 25, "Report generated by ChamaSmart Software")
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor(MUTED_TEXT))
    canvas.drawCentredString(page_width/2, 15, f"© {datetime.now().year} ChamaSmart Software. All rights reserved.") # Copyright dynamic year

    # Right side info (Contact Info)
    canvas.setFont('Helvetica', 8)
    canvas.drawRightString(page_width - doc.rightMargin, 25, "support@chamasmart.com") # Use doc.rightMargin
    canvas.drawRightString(page_width - doc.rightMargin, 15, "www.chamasmart.com") # Use doc.rightMargin

    # Restore canvas state
    canvas.restoreState()


# --- Main PDF Export Route ---
@contributions_bp.route('/api/export/pdf', methods=['GET'])
@login_required
def export_pdf():
    chama_id = request.args.get('chamaId', 'all')
    search_term = request.args.get('searchTerm', '')
    data_type = request.args.get('dataType', 'contributions') # 'contributions' or 'penalties'

    # Fetch the data using your existing function
    data = get_filtered_data_for_export(chama_id, search_term, data_type)

    # Fetch the Chama object for report details
    chama = None
    if chama_id and chama_id != 'all':
        # Make sure to handle the case where int(chama_id) might fail if chama_id is not numeric
        try:
            chama = Chama.query.get(int(chama_id))
        except ValueError:
            # Handle invalid chamaId format if necessary, maybe return a 400 error
            # For now, leaving chama as None is okay if get_filtered_data_for_export handles it.
             pass # chama remains None

    # Handle case where no data is found OR chama doesn't exist/user not authorized
    # The get_filtered_data_for_export function is assumed to handle authorization internally
    # by returning empty data or raising 403.
    if not data:
         # Improve error message based on whether a specific chama was requested
         if chama_id != 'all':
             # If a specific chama was requested but no data was found (either no records
             # or chama not found/user not authorized which get_filtered_data_for_export handles)
             if not chama:
                 abort(404, description=f"Chama with ID {chama_id} not found.")
             else:
                 # Chama found, but no records matching criteria or user not authorized
                 abort(404, description=f"No {data_type} found for {chama.name} matching your criteria.")
         elif search_term:
             # No specific chama, but search term applied
             abort(404, description=f"No {data_type} found across all chamas matching your search criteria.")
         else:
             # No specific chama, no search term, but no data returned
             abort(404, description=f"No {data_type} records found in the system.")


    # --- PDF Generation Logic ---
    buffer = io.BytesIO()
    page_width, page_height = A4 # Use A4 size

    # Set margins (Adjust top/bottom to accommodate header/footer height)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=80, # Must be > header_height + 3 + padding
        bottomMargin=60 # Must be > footer_height + 1 + padding
    )

    elements = []

    # --- Cover Page ---
    # --- Cover Page ---

    elements.append(Spacer(1, 40))

    # Main Title
    elements.append(
        Paragraph(
            f"{data_type.capitalize()} Report",
            styles['ReportTitle']
        )
    )

    # *** Add an explicit gap here ***
    elements.append(Spacer(1, 10))

    # Subtitle (with wrapping)
    if chama:
        subtitle_text = f"for {chama.name}"
    else:
        subtitle_text = "for All Chamas"

    elements.append(
        Paragraph(
            subtitle_text,
            styles['ReportSubtitle']
        )
    )

    elements.append(Spacer(1, 20))

    today = datetime.now().strftime('%B %d, %Y')
    elements.append(Paragraph(f"Generated on {today}", styles['SubTitle']))
    elements.append(Spacer(1, 15))

    # Decorative line
    line_width = page_width - doc.leftMargin - doc.rightMargin # Line width based on content area
    elements.append(SolidLine(line_width, color=SECONDARY_COLOR)) # Use the SolidLine Flowable
    elements.append(Spacer(1, 20))

    # Report Summary
    summary_text = f"This report provides an overview of {data_type} records within the ChamaSmart system."
    if chama:
         summary_text += f" for {chama.name}."
    else:
         summary_text += f" across all chamas." # Add for All Chamas case

    if search_term:
         summary_text += f" Filtered by search term: '{search_term}'."

    elements.append(Paragraph(summary_text, styles['NormalText']))
    elements.append(Spacer(1, 25))

    # Report Filters/Parameters Section
    elements.append(Paragraph("Report Filters", styles['SectionTitle']))
    elements.append(SolidLine(100, color=ACCENT_COLOR)) # Shorter line for subsection
    elements.append(Spacer(1, 10))

    filter_info = [
        ['Selected Chama:', chama.name if chama else 'All Chamas'], # Safely access chama.name
        ['Search Term:', search_term if search_term else 'None'],
        ['Data Type:', data_type.capitalize()],
        ['Number of Records:', str(len(data))] # Total records in this specific report
    ]

    # Style for filter info table
    filter_table_style = TableStyle([
         ('BACKGROUND', (0, 0), (0, -1), colors.HexColor(LIGHT_BG)),
         ('BACKGROUND', (1, 0), (1, -1), colors.white),
         ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor(PRIMARY_COLOR)),
         ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor(TEXT_COLOR)),
         ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
         ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
         ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
         ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
         ('TOPPADDING', (0, 0), (-1, -1), 6),
         ('LEFTPADDING', (0, 0), (-1, -1), 10),
         ('RIGHTPADDING', (0, 0), (-1, -1), 10),
         ('BOX', (0, 0), (-1, -1), 0.7, colors.HexColor('#DDDDDD')),
    ])
    filter_table = Table(filter_info, [120, line_width - 120])
    
    filter_table.setStyle(filter_table_style)
    elements.append(filter_table)

    elements.append(PageBreak()) # Start main data table on a new page

    # --- Main Data Table Section (Dynamic) ---
    section_title_text = f"{data_type.capitalize()} Details"
    elements.append(Paragraph(section_title_text, styles['SectionTitle']))
    elements.append(SolidLine(150, color=SECONDARY_COLOR))
    elements.append(Spacer(1, 15))

    # Define headers and extract data rows based on data_type
    headers = []
    table_data = []
    col_widths = [] # Store column widths
    total_width = page_width - doc.leftMargin - doc.rightMargin # Usable width

    if data_type == 'contributions':
        headers = ["Date", "Chama", "Member", "Amount", "Status", "Method", "Reference", "Notes"]
        # Example proportional widths (adjust as needed)
        # Ensure sum approximately equals total_width
        col_widths = [total_width * 0.12, total_width * 0.15, total_width * 0.15, total_width * 0.1, total_width * 0.1, total_width * 0.1, total_width * 0.13, total_width * 0.15]

        for item in data:
            table_data.append([
                Paragraph(item.get('date', ''), styles['TableCellText']), # Use Paragraph for text wrapping
                Paragraph(item.get('chamaName', ''), styles['TableCellText']),
                Paragraph(item.get('member', ''), styles['TableCellText']),
                Paragraph(f"KES {item.get('amount', 0):,.2f}", styles['TableCellTextRight']), # Format currency
                Paragraph(item.get('status', ''), styles['TableCellText']),
                Paragraph(item.get('method', ''), styles['TableCellText']),
                Paragraph(item.get('reference_number', ''), styles['TableCellText']),
                Paragraph(item.get('notes', ''), styles['TableCellText']),
            ])

        # Define specific table style for Contributions
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(PRIMARY_COLOR)), # Header background
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), # Header text color
            ('ALIGN', (0, 0), (-1, 0), 'LEFT'), # Header align
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            ('LEFTPADDING', (0, 0), (-1, -1), 8), # Padding for all cells
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),

            ('BACKGROUND', (0, 1), (-1, -1), colors.white), # Body background
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor(TEXT_COLOR)), # Body text color
            ('ALIGN', (0, 1), (-1, -1), 'LEFT'), # Body align (default)
             ('ALIGN', (3, 1), (3, -1), 'RIGHT'), # Right align Amount column (index 3)

            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'), # Body font
            ('FONTSIZE', (0, 1), (-1, -1), 8),

            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor(LIGHT_BG)]), # Zebra striping

            ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor(SECONDARY_COLOR)),  # Header bottom line
            ('LINEBELOW', (0, 1), (-1, -2), 0.3, colors.HexColor('#EEEEEE')),     # Row dividers
            ('BOX', (0, 0), (-1, -1), 0.7, colors.HexColor('#DDDDDD')),           # Table outer border

            # Status colors for Contributions (index 4)
            ('TEXTCOLOR', (4, 1), (4, -1), colors.HexColor(GREEN_COLOR)), # Default Paid
            ('TEXTCOLOR', (4, 1), (4, -1), colors.HexColor(YELLOW_COLOR), lambda data, row, col: data[row][col].get('text') == 'Pending'), # Conditional Pending
            ('TEXTCOLOR', (4, 1), (4, -1), colors.HexColor(RED_COLOR), lambda data, row, col: data[row][col].get('text') == 'Overdue'),   # Conditional Overdue
        ])

    elif data_type == 'penalties':
        headers = ["Date", "Chama", "Member", "Amount", "Reason", "Type", "Status", "Resolved Date"]
        # Example proportional widths (adjust as needed)
        # Ensure sum approximately equals total_width
        col_widths = [total_width * 0.12, total_width * 0.15, total_width * 0.15, total_width * 0.1, total_width * 0.2, total_width * 0.1, total_width * 0.1, total_width * 0.08]

        for item in data:
             table_data.append([
                Paragraph(item.get('date', ''), styles['TableCellText']),
                Paragraph(item.get('chamaName', ''), styles['TableCellText']),
                Paragraph(item.get('member', ''), styles['TableCellText']),
                Paragraph(f"KES {item.get('amount', 0):,.2f}", styles['TableCellTextRight']), # Format currency
                Paragraph(item.get('reason', ''), styles['TableCellText']),
                Paragraph(item.get('penalty_type', ''), styles['TableCellText']),
                Paragraph(item.get('status', ''), styles['TableCellText']),
                Paragraph(item.get('resolved_date', '') if item.get('resolved_date') else 'N/A', styles['TableCellText']),
            ])

        # Define specific table style for Penalties
        table_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(PRIMARY_COLOR)), # Header background
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), # Header text color
            ('ALIGN', (0, 0), (-1, 0), 'LEFT'), # Header align
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 0), (-1, 0), 12),
             ('LEFTPADDING', (0, 0), (-1, -1), 8), # Padding for all cells
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
             ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),

            ('BACKGROUND', (0, 1), (-1, -1), colors.white), # Body background
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor(TEXT_COLOR)), # Body text color
            ('ALIGN', (0, 1), (-1, -1), 'LEFT'), # Body align (default)
            ('ALIGN', (3, 1), (3, -1), 'RIGHT'), # Right align Amount column (index 3)

            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'), # Body font
            ('FONTSIZE', (0, 1), (-1, -1), 8),

            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor(LIGHT_BG)]), # Zebra striping

            ('LINEBELOW', (0, 0), (-1, 0), 1, colors.HexColor(SECONDARY_COLOR)),  # Header bottom line
            ('LINEBELOW', (0, 1), (-1, -2), 0.3, colors.HexColor('#EEEEEE')),     # Row dividers
            ('BOX', (0, 0), (-1, -1), 0.7, colors.HexColor('#DDDDDD')),           # Table outer border

            # Status colors for Penalties (index 6)
            ('TEXTCOLOR', (6, 1), (6, -1), colors.HexColor(RED_COLOR)),      # Default Active
            ('TEXTCOLOR', (6, 1), (6, -1), colors.HexColor(MUTED_TEXT), lambda data, row, col: data[row][col].get('text') == 'Waived'), # Conditional Waived
            ('TEXTCOLOR', (6, 1), (6, -1), colors.HexColor(GREEN_COLOR), lambda data, row, col: data[row][col].get('text') == 'Paid'),   # Conditional Paid
        ])


    # Add styled headers
    # Wrap headers in ParagraphStyle to use font/color from style definition
    styled_headers = [Paragraph(h, styles['TableHeaderText']) for h in headers]
    table_data.insert(0, styled_headers) # Add headers as the first row of table_data

    # Create the table
    # Use dynamic col_widths
    table = Table(table_data, colWidths=col_widths, repeatRows=1) # repeatRows=1 repeats header on new pages

    # Apply the table style
    table.setStyle(table_style)


    # Add table to elements, wrapped in KeepTogether if desired (can break long tables across pages)
    # For potentially very long tables, KeepTogether might not be suitable for the whole table.
    # ReportLab handles breaking tables across pages by default if they exceed page height.
    elements.append(table)


    # Add report notes section
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("Notes", styles['SectionTitle']))
    elements.append(SolidLine(100, color=ACCENT_COLOR)) # Use Accent color for this line
    elements.append(Spacer(1, 10))

    notes_text = """
    1. This report contains financial information about chama activities.
    2. Data reflects the status at the time of report generation.
    3. Amounts are displayed in KES (Kenya Shillings).
    4. For detailed queries, refer to the ChamaSmart application.
    """

    notes = Paragraph(notes_text, styles['NormalText'])
    elements.append(notes)

    # Add legal information at the bottom
    elements.append(Spacer(1, 40))

    # Add disclaimer with more professional styling
    disclaimer_text = "CONFIDENTIALITY NOTICE: This document contains proprietary information belonging to ChamaSmart Software and the respective chama organization. Unauthorized distribution is strictly prohibited. All financial data is provided as-is for informational purposes."
    disclaimer = Paragraph(disclaimer_text, styles['Disclaimer'])
    elements.append(disclaimer)

    # --- Build PDF ---
    # Pass header_footer function and its required arguments (data_type, chama) to the build method
    doc.build(elements, onFirstPage=lambda c, d: header_footer(c, d, data_type, chama),
                      onLaterPages=lambda c, d: header_footer(c, d, data_type, chama))

    # Reset file pointer
    buffer.seek(0)

    # Generate filename with timestamp and chama details
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    # Create a safe filename slug from chama name
    # --- FIX: Handle chama being None for filename ---
    chama_name_slug = ''.join(c if c.isalnum() or c in (' ', '-') else '' for c in (chama.name if chama else 'All Chamas')).replace(' ', '_')
    # --- END FIX ---
    report_name_slug = data_type.lower()
    filename = f"{chama_name_slug}_{report_name_slug}_Report_{timestamp}.pdf"

    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename # Use the dynamically generated filename
    )

# ... rest of your routes.py ...