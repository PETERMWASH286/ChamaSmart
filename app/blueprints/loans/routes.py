# Skeleton: app/blueprints/loans/routes.py
from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required

from app.models.contribution import Contribution, Penalty

loans_bp = Blueprint('loans', __name__, url_prefix='/loans')

@loans_bp.route('/')
@login_required
def list_loans():
    # View loan requests
    return render_template('loans/index.html')

@loans_bp.route('/request', methods=['GET', 'POST'])
@login_required
def request_loan():
    # Request a new loan
    return render_template('loans/request.html')



# app/blueprints/loans/routes.py

from flask import Blueprint, request, jsonify, abort
from app.models.chama import chama_admins  # Import the chama_admins table
from flask_login import login_required, current_user
from app.extensions import db
from app.models.loan import Loan, LoanRepayment # Import your Loan and LoanRepayment models
from app.models.chama import Chama # Import Chama model
from app.models.user import User # Import User model
from datetime import datetime
from sqlalchemy.orm import joinedload # For eager loading relationships
from sqlalchemy import func # For potential aggregations if needed for stats calculation server-side

loans_bp = Blueprint('loans_bp', __name__, url_prefix='/api/loans')

# --- Serialization Helpers ---
# These functions convert database models to dictionaries for JSON response
# Ensure these include all fields needed by the frontend script

def serialize_repayment(repayment):
    """Serializes a LoanRepayment object."""
    return {
        'id': repayment.id,
        'loanId': repayment.loan_id, # Use camelCase for frontend
        'userId': repayment.user_id,
        'amount': float(repayment.amount), # Convert Decimal to float
        'payment_date': repayment.payment_date.strftime('%Y-%m-%d') if repayment.payment_date else None, # Format date
        'status': repayment.status,
        'method': repayment.method,
        'reference_number': repayment.reference_number,
        'notes': repayment.notes,
        'created_at': repayment.created_at.isoformat() if repayment.created_at else None # ISO format for datetime
    }

def serialize_loan(loan):
    """Serializes a Loan object, including nested repayments."""
    # Assuming loan has a 'remaining_balance' property or method
    # You might need to calculate total paid and remaining balance here or in the model
    total_paid = sum(repayment.amount for repayment in loan.repayments)
    # Assuming loan.amount is the principal and loan.interest_rate is annual percentage
    # A proper loan amortization schedule is complex, this is a simplified balance
    # Total expected repayment might be amount * (1 + interest_rate/100) if interest is simple
    # Or calculate based on installment schedule if you have one
    # For now, let's use the remaining_balance property from your model if available
    remaining_balance = loan.remaining_balance if hasattr(loan, 'remaining_balance') else (loan.amount - total_paid) # Fallback calculation


    return {
        'id': loan.id,
        'userId': loan.user_id,
        'chamaId': loan.chama_id,
        'member': loan.user.full_name if loan.user else 'N/A', # Assuming User model has full_name
        'chamaName': loan.chama.name if loan.chama else 'N/A', # Assuming Chama model has name
        'amount': float(loan.amount), # Principal amount lent
        'interest_rate': float(loan.interest_rate),
        'purpose': loan.purpose,
        'status': loan.status.capitalize(), # Capitalize status for display
        'loan_type': loan.loan_type.capitalize(),
        'issued_date': loan.issued_date.strftime('%Y-%m-%d') if loan.issued_date else None,
        'due_date': loan.due_date.strftime('%Y-%m-%d') if loan.due_date else None, # Ensure due_date is included
        'repayment_period': loan.repayment_period,
        'notes': loan.notes,
        'created_at': loan.created_at.isoformat() if loan.created_at else None,
        # Calculated fields needed by frontend
        'totalPaid': float(total_paid),
        'balance': float(remaining_balance), # Remaining balance
        # Include nested repayments, serialized
        'repayments': [serialize_repayment(r) for r in loan.repayments]
    }

# Helper function to get accessible chama IDs for the current user
def get_user_accessible_chama_ids():
    """Returns a list of chama IDs the current user has access to."""
    # This logic should align with your application's authorization rules.
    # Example: user is super_admin or belongs to the chama_admins relationship
    if current_user.is_authenticated:
        if hasattr(current_user, 'role') and current_user.role == 'super_admin':
            # Super admin can see all chamas
            return [c.id for c in Chama.query.all()] # Adjust if Chamas are too many

        if hasattr(current_user, 'chamas'):
            # User is an admin of these chamas
            return [chama.id for chama in current_user.chamas]

    return [] # No access

# --- API Endpoints ---
# --- Serialization Helper ---
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
@loans_bp.route('/api/chamas', methods=['GET'])
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


    
@loans_bp.route('/', methods=['GET'])
@login_required
def get_loans():
    """Fetches loans with filtering, searching, and nested repayments."""
    chama_id = request.args.get('chama', 'all') # 'chama' parameter from frontend
    search_term = request.args.get('q', '') # 'q' parameter from frontend

    accessible_chama_ids = get_user_accessible_chama_ids()

    # Base query for loans, eagerly load user, chama, and repayments
    query = Loan.query.options(
        joinedload(Loan.user),
        joinedload(Loan.chama),
        joinedload(Loan.repayments)
    )

    # Filter by accessible chamas (unless super admin)
    if current_user.role != 'super_admin':
         if not accessible_chama_ids:
             return jsonify([]), 200 # No access to any chamas

         query = query.filter(Loan.chama_id.in_(accessible_chama_ids))


    # Filter by specific chama if requested
    if chama_id != 'all':
        try:
            chama_id_int = int(chama_id)
            # Ensure the requested chama is in the user's accessible list (redundant if filtering by accessible_chama_ids first, but safe)
            if chama_id_int not in accessible_chama_ids and current_user.role != 'super_admin':
                 abort(403) # Forbidden

            query = query.filter(Loan.chama_id == chama_id_int)

        except ValueError:
            # Invalid chama ID format
            return jsonify({'message': 'Invalid chama ID format'}), 400
        # If chama_id is requested but not found (e.g. deleted), query will return empty list

    # Apply search term filtering
    if search_term:
        # Case-insensitive search on member name (User.full_name), loan status, loan ID, loan amount/balance (as string)
        # Note: Searching numeric fields as strings might not be efficient for large datasets
        lower_search = search_term.lower()
        query = query.join(User, Loan.user_id == User.id).filter(
            (User.full_name.ilike(f'%{lower_search}%')) |
            (Loan.status.ilike(f'%{lower_search}%')) | # Search loan status
            (Loan.id.cast(db.String).ilike(f'%{lower_search}%')) | # Search loan ID as string
            (Loan.amount.cast(db.String).ilike(f'%{lower_search}%')) # Search loan amount as string
            # Note: Filtering by balance would require calculating it in the query which is complex
            # You might omit balance search or do it on the frontend
        )
        # You could also add search on loan purpose if needed

    # Order the results (default ordering, frontend handles sorting of filtered data)
    # Or apply server-side sorting if needed, but frontend sorting is often sufficient for moderate data sets
    query = query.order_by(Loan.issued_date.desc()) # Example default order

    loans = query.all()

    # Serialize the results
    serialized_loans = [serialize_loan(loan) for loan in loans]

    return jsonify(serialized_loans), 200


@loans_bp.route('/', methods=['POST'])
@login_required
def create_loan():
    """Creates a new loan application."""
    data = request.get_json()

    if not data:
        return jsonify({'message': 'No input data provided'}), 400

    # --- Input Validation ---
    required_fields = ['chamaId', 'userId', 'amount', 'due_date', 'repayment_period'] # Add other required fields from newLoanData
    for field in required_fields:
        if field not in data or not data[field]:
            return jsonify({'message': f'Missing required field: {field}'}), 400

    try:
        chama_id = int(data['chamaId'])
        user_id = int(data['userId'])
        amount = float(data['amount'])
        repayment_period = int(data['repayment_period'])
        due_date_str = data['due_date']
        # Add validation for other fields
        interest_rate = float(data.get('interestRate', 0.0)) # Default to 0 if not provided
        loan_type = data.get('loan_type', 'personal') # Default if not provided
        status = data.get('status', 'pending') # Default to pending
        purpose = data.get('purpose')
        notes = data.get('notes')


        # Validate status against allowed statuses
        if status.lower() not in Loan.STATUSES:
             return jsonify({'message': f'Invalid status: {status}'}), 400

         # Validate loan_type against allowed types
        if loan_type.lower() not in Loan.TYPES:
             return jsonify({'message': f'Invalid loan type: {loan_type}'}), 400

        # Validate amount and repayment_period
        if amount <= 0:
            return jsonify({'message': 'Amount must be positive'}), 400
        if repayment_period <= 0:
             return jsonify({'message': 'Repayment period must be positive'}), 400
        if interest_rate < 0:
             return jsonify({'message': 'Interest rate cannot be negative'}), 400


        # Validate due date format and parse
        try:
             due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
        except ValueError:
             return jsonify({'message': 'Invalid due date format. Use YYYY-MM-DD'}), 400

    except (ValueError, TypeError) as e:
        return jsonify({'message': f'Invalid data type or format: {e}'}), 400


    # --- Authorization Check ---
    accessible_chama_ids = get_user_accessible_chama_ids()
    if chama_id not in accessible_chama_ids and current_user.role != 'super_admin':
        abort(403) # Forbidden - User cannot create a loan in a chama they don't manage

    # Check if the user (borrower) is associated with the chama (optional, but good practice)
    # You might need to fetch the User object and check its relation to the Chama
    # borrower_user = User.query.get(user_id)
    # if not borrower_user or chama not in borrower_user.chamas:
    #      return jsonify({'message': 'Borrower is not a member of this chama'}), 400


    # --- Create Loan ---
    new_loan = Loan(
        chama_id=chama_id,
        user_id=user_id,
        amount=amount,
        interest_rate=interest_rate,
        purpose=purpose,
        status=status.lower(), # Store status in lowercase
        loan_type=loan_type.lower(), # Store type in lowercase
        due_date=due_date,
        repayment_period=repayment_period,
        notes=notes,
        # issued_date defaults to utcnow()
    )

    db.session.add(new_loan)

    try:
        db.session.commit()
        # Optionally fetch the newly created loan with relations to return it
        # created_loan = Loan.query.options(joinedload(Loan.user), joinedload(Loan.chama), joinedload(Loan.repayments)).get(new_loan.id)
        # return jsonify(serialize_loan(created_loan)), 201
        return jsonify({'message': 'Loan application created successfully', 'loanId': new_loan.id}), 201 # Return success message and ID
    except Exception as e:
        db.session.rollback()
        print(f"Error creating loan: {e}") # Log the error
        return jsonify({'message': 'Failed to create loan application'}), 500


@loans_bp.route('/repayments', methods=['POST'])
@login_required
def record_repayment():
    """Records a new loan repayment."""
    data = request.get_json()

    if not data:
        return jsonify({'message': 'No input data provided'}), 400

    # --- Input Validation ---
    required_fields = ['loanId', 'amount', 'date', 'method']
    for field in required_fields:
        if field not in data or not data[field]:
            return jsonify({'message': f'Missing required field: {field}'}), 400

    try:
        loan_id = int(data['loanId'])
        amount = float(data['amount'])
        payment_date_str = data['date']
        method = data['method']
        reference_number = data.get('reference')
        notes = data.get('notes')

        # Validate amount
        if amount <= 0:
            return jsonify({'message': 'Repayment amount must be positive'}), 400

        # Validate payment date format and parse
        try:
             payment_date = datetime.strptime(payment_date_str, '%Y-%m-%d')
        except ValueError:
             return jsonify({'message': 'Invalid payment date format. Use YYYY-MM-DD'}), 400

    except (ValueError, TypeError) as e:
        return jsonify({'message': f'Invalid data type or format: {e}'}), 400

    # --- Fetch Loan and Authorization Check ---
    loan = Loan.query.options(joinedload(Loan.chama)).get(loan_id)

    if not loan:
        return jsonify({'message': 'Loan not found'}), 404

    accessible_chama_ids = get_user_accessible_chama_ids()
    if loan.chama_id not in accessible_chama_ids and current_user.role != 'super_admin':
        abort(403) # Forbidden - User cannot record repayment for a loan in a chama they don't manage


    # --- Create Repayment ---
    new_repayment = LoanRepayment(
        loan_id=loan_id,
        user_id=current_user.id, # Assuming the user recording is the current user
        amount=amount,
        payment_date=payment_date,
        method=method,
        reference_number=reference_number,
        notes=notes,
        # status defaults to 'paid'
    )

    db.session.add(new_repayment)

    # --- Update Loan Status/Balance (Backend Logic) ---
    # This is crucial backend logic to keep loan state accurate.
    # A simple approach: if total paid >= loan amount + interest, set status to 'paid'.
    # More complex logic needed for partial payments, installments, due date tracking.
    # Let's assume a simple check based on balance for now.
    try:
        db.session.flush() # Use flush to make the new repayment available for balance calculation without committing

        if loan.remaining_balance <= 0.01: # Use a small tolerance for floating point comparisons
             loan.status = 'paid'
             # Optionally set a paid_date on the loan model
             # loan.paid_date = datetime.utcnow() # If you add this field to the Loan model

        db.session.commit()

        return jsonify({'message': 'Repayment recorded successfully', 'repaymentId': new_repayment.id}), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error recording repayment: {e}") # Log the error
        return jsonify({'message': 'Failed to record repayment'}), 500


@loans_bp.route('/<int:loan_id>', methods=['PUT', 'PATCH'])
@login_required
def update_loan(loan_id):
    """Updates an existing loan."""
    loan = Loan.query.options(joinedload(Loan.chama)).get(loan_id)

    if not loan:
        return jsonify({'message': 'Loan not found'}), 404

    # --- Authorization Check ---
    accessible_chama_ids = get_user_accessible_chama_ids()
    if loan.chama_id not in accessible_chama_ids and current_user.role != 'super_admin':
        abort(403) # Forbidden

    data = request.get_json()

    if not data:
        return jsonify({'message': 'No update data provided'}), 400

    # --- Apply Updates and Validate ---
    # Only update fields that are allowed to be edited from the frontend
    if 'amount' in data and data['amount'] is not None:
        try:
            amount = float(data['amount'])
            if amount <= 0:
                 return jsonify({'message': 'Amount must be positive'}), 400
            loan.amount = amount
        except (ValueError, TypeError):
             return jsonify({'message': 'Invalid amount format'}), 400

    if 'status' in data and data['status'] is not None:
         status = data['status'].lower()
         if status not in Loan.STATUSES:
              return jsonify({'message': f'Invalid status: {data["status"]}'}), 400
         loan.status = status

    if 'due_date' in data and data['due_date'] is not None:
         try:
             # Handle potential empty string for date input
             if data['due_date'] == '':
                  loan.due_date = None # Allow setting due date to null if needed
             else:
                 due_date = datetime.strptime(data['due_date'], '%Y-%m-%d')
                 loan.due_date = due_date
         except ValueError:
             return jsonify({'message': 'Invalid due date format. Use YYYY-MM-DD'}), 400

    # Add other editable fields (e.g., interest_rate, purpose, notes, repayment_period)
    if 'interest_rate' in data and data['interest_rate'] is not None:
         try:
             interest_rate = float(data['interest_rate'])
             if interest_rate < 0:
                 return jsonify({'message': 'Interest rate cannot be negative'}), 400
             loan.interest_rate = interest_rate
         except (ValueError, TypeError):
             return jsonify({'message': 'Invalid interest rate format'}), 400

    if 'purpose' in data: # Allow setting to empty string
         loan.purpose = data['purpose'] if data['purpose'] else None

    if 'notes' in data: # Allow setting to empty string
         loan.notes = data['notes'] if data['notes'] else None

    if 'repayment_period' in data and data['repayment_period'] is not None:
         try:
             repayment_period = int(data['repayment_period'])
             if repayment_period <= 0:
                  return jsonify({'message': 'Repayment period must be positive'}), 400
             loan.repayment_period = repayment_period
         except (ValueError, TypeError):
             return jsonify({'message': 'Invalid repayment period format'}), 400


    loan.updated_at = datetime.utcnow() # Update updated_at timestamp

    try:
        db.session.commit()
        # Optionally return the updated loan data
        # db.session.refresh(loan) # Refresh to get latest state if needed
        # updated_loan = Loan.query.options(joinedload(Loan.user), joinedload(Loan.chama), joinedload(Loan.repayments)).get(loan.id)
        # return jsonify(serialize_loan(updated_loan)), 200
        return jsonify({'message': 'Loan updated successfully', 'loanId': loan.id}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error updating loan {loan_id}: {e}") # Log error
        return jsonify({'message': 'Failed to update loan'}), 500


@loans_bp.route('/<int:loan_id>', methods=['DELETE'])
@login_required
def delete_loan(loan_id):
    """Deletes a loan."""
    loan = Loan.query.options(joinedload(Loan.chama)).get(loan_id)

    if not loan:
        return jsonify({'message': 'Loan not found'}), 404

    # --- Authorization Check ---
    accessible_chama_ids = get_user_accessible_chama_ids()
    if loan.chama_id not in accessible_chama_ids and current_user.role != 'super_admin':
        abort(403) # Forbidden

    # Note: Using cascade='all, delete-orphan' on the 'repayments' relationship
    # in the Loan model will automatically delete associated repayments when the loan is deleted.

    db.session.delete(loan)

    try:
        db.session.commit()
        return jsonify({'message': 'Loan deleted successfully', 'loanId': loan_id}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting loan {loan_id}: {e}") # Log error
        # Check if deletion failed due to related records if cascade wasn't set
        # For example, if there are loan repayments that are not set to cascade on delete
        return jsonify({'message': 'Failed to delete loan. It might have associated records.'}), 500

@loans_bp.route('/repayments/<int:repayment_id>', methods=['DELETE'])
@login_required
def delete_repayment(repayment_id):
    """Deletes a loan repayment."""
    repayment = LoanRepayment.query.options(joinedload(LoanRepayment.loan).joinedload(Loan.chama)).get(repayment_id)

    if not repayment:
        return jsonify({'message': 'Repayment not found'}), 404

    # --- Authorization Check ---
    # Check access based on the related loan's chama
    accessible_chama_ids = get_user_accessible_chama_ids()
    if repayment.loan and repayment.loan.chama_id not in accessible_chama_ids and current_user.role != 'super_admin':
        abort(403) # Forbidden

    db.session.delete(repayment)

    # --- Update Loan Status/Balance After Deletion (Backend Logic) ---
    # If a repayment is deleted, the loan's status/balance might change.
    # Re-calculate the balance and update status if needed.
    loan = repayment.loan # Get the related loan before committing deletion
    if loan:
        try:
            db.session.flush() # Flush deletion to recalculate balance
            # Re-evaluate loan status based on new remaining balance
            if loan.status == 'paid' and loan.remaining_balance > 0.01: # If it was paid but now has balance after deletion
                 loan.status = 'active' # Or 'overdue' depending on due date

            # You might need more complex logic here depending on your loan terms and statuses

            db.session.commit()

            return jsonify({'message': 'Repayment deleted successfully', 'repaymentId': repayment_id}), 200
        except Exception as e:
            db.session.rollback()
            print(f"Error deleting repayment {repayment_id} or updating loan status: {e}") # Log error
            return jsonify({'message': 'Failed to delete repayment or update loan status'}), 500
    else:
         # Should not happen if repayment is found, but as a safeguard
         try:
             db.session.commit()
             return jsonify({'message': 'Repayment deleted successfully', 'repaymentId': repayment_id}), 200
         except Exception as e:
             db.session.rollback()
             print(f"Error deleting repayment {repayment_id}: {e}")
             return jsonify({'message': 'Failed to delete repayment'}), 500


# GET Members for a Specific Chama
@loans_bp.route('/chamas/<int:chama_id>/members', methods=['GET'])
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
             db.session.rollback()
             print(f"Error fetching members for Chama {chama_id}: {e}")