"""
Backend API Server for Book Purchase Tracking
Run this on a server (Heroku, Render, PythonAnywhere, etc.)
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import json
from pathlib import Path
from datetime import datetime
import secrets

app = Flask(__name__)
CORS(app)  # Allow requests from launcher

# Data files
PURCHASES_FILE = Path("data/purchases.json")
STATS_FILE = Path("data/stats.json")
PENDING_FILE = Path("data/pending.json")
ADMIN_KEY = "LiveKitaabAdminHaiAC@2014"  # Change this!

# Ensure data directory exists
Path("data").mkdir(exist_ok=True)

def load_json(filepath, default=None):
    """Load JSON file safely"""
    if not filepath.exists():
        return default or {}
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except:
        return default or {}

def save_json(filepath, data):
    """Save JSON file safely"""
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

def init_stats():
    """Initialize stats file if needed"""
    if not STATS_FILE.exists():
        save_json(STATS_FILE, {
            "books": {},
            "total_revenue": 0,
            "total_purchases": 0
        })

init_stats()

# ==================== PUBLIC ENDPOINTS ====================

@app.route('/api/request-purchase', methods=['POST'])
def request_purchase():
    """
    User requests to purchase a book
    Launcher sends: book_id, price, transaction_id
    Returns: verification_code (user must confirm this)
    """
    data = request.json
    book_id = data.get('book_id')
    price = data.get('price', 0)
    transaction_id = data.get('transaction_id')
    
    if not book_id or not transaction_id:
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Generate verification code
    verification_code = secrets.token_hex(4).upper()  # 8-char code
    
    # Load pending purchases
    pending = load_json(PENDING_FILE, {"purchases": []})
    
    # Check for duplicate transaction ID
    purchases = load_json(PURCHASES_FILE, {"purchases": []})
    for purchase in purchases.get('purchases', []):
        if purchase.get('transaction_id') == transaction_id:
            return jsonify({'error': 'Transaction ID already used'}), 400
    
    # Add to pending
    pending_purchase = {
        'verification_code': verification_code,
        'book_id': book_id,
        'price': price,
        'transaction_id': transaction_id,
        'timestamp': datetime.now().isoformat(),
        'status': 'pending'
    }
    
    pending['purchases'].append(pending_purchase)
    save_json(PENDING_FILE, pending)
    
    return jsonify({
        'success': True,
        'verification_code': verification_code,
        'message': f'Please confirm this code: {verification_code}'
    })

@app.route('/api/verify-purchase', methods=['POST'])
def verify_purchase():
    """
    Admin verifies purchase by entering verification code
    This can be called from admin app or manually
    """
    data = request.json
    verification_code = data.get('verification_code')
    admin_key = data.get('admin_key')
    
    if admin_key != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    
    if not verification_code:
        return jsonify({'error': 'Missing verification code'}), 400
    
    # Load pending
    pending = load_json(PENDING_FILE, {"purchases": []})
    
    # Find purchase
    purchase_to_verify = None
    remaining_pending = []
    
    for purchase in pending.get('purchases', []):
        if purchase.get('verification_code') == verification_code:
            purchase_to_verify = purchase
        else:
            remaining_pending.append(purchase)
    
    if not purchase_to_verify:
        return jsonify({'error': 'Verification code not found'}), 404
    
    # Move to confirmed purchases
    purchases = load_json(PURCHASES_FILE, {"purchases": []})
    purchase_to_verify['status'] = 'confirmed'
    purchase_to_verify['confirmed_at'] = datetime.now().isoformat()
    purchases['purchases'].append(purchase_to_verify)
    save_json(PURCHASES_FILE, purchases)
    
    # Update pending
    pending['purchases'] = remaining_pending
    save_json(PENDING_FILE, pending)
    
    # Update stats
    update_stats(purchase_to_verify['book_id'], purchase_to_verify['price'])
    
    return jsonify({
        'success': True,
        'book_id': purchase_to_verify['book_id'],
        'transaction_id': purchase_to_verify['transaction_id']
    })

@app.route('/api/check-purchase', methods=['POST'])
def check_purchase():
    """
    Check if user has purchased a book
    Launcher calls this before allowing download
    """
    data = request.json
    book_id = data.get('book_id')
    transaction_id = data.get('transaction_id')
    
    if not book_id or not transaction_id:
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Check in confirmed purchases
    purchases = load_json(PURCHASES_FILE, {"purchases": []})
    
    for purchase in purchases.get('purchases', []):
        if (purchase.get('book_id') == book_id and 
            purchase.get('transaction_id') == transaction_id and
            purchase.get('status') == 'confirmed'):
            return jsonify({
                'purchased': True,
                'confirmed_at': purchase.get('confirmed_at')
            })
    
    # Check if pending
    pending = load_json(PENDING_FILE, {"purchases": []})
    for purchase in pending.get('purchases', []):
        if (purchase.get('book_id') == book_id and 
            purchase.get('transaction_id') == transaction_id):
            return jsonify({
                'purchased': False,
                'status': 'pending',
                'verification_code': purchase.get('verification_code')
            })
    
    return jsonify({'purchased': False, 'status': 'not_found'})

@app.route('/api/track-download', methods=['POST'])
def track_download():
    """Track when a book is downloaded (free or paid)"""
    data = request.json
    book_id = data.get('book_id')
    is_free = data.get('is_free', False)
    
    if not book_id:
        return jsonify({'error': 'Missing book_id'}), 400
    
    # Update stats
    stats = load_json(STATS_FILE)
    
    if book_id not in stats['books']:
        stats['books'][book_id] = {
            'total_downloads': 0,
            'free_downloads': 0,
            'paid_downloads': 0,
            'revenue': 0
        }
    
    stats['books'][book_id]['total_downloads'] += 1
    
    if is_free:
        stats['books'][book_id]['free_downloads'] += 1
    else:
        stats['books'][book_id]['paid_downloads'] += 1
    
    save_json(STATS_FILE, stats)
    
    return jsonify({'success': True})

# ==================== ADMIN ENDPOINTS ====================

@app.route('/api/admin/stats', methods=['GET'])
def get_stats():
    """Get all statistics (for admin dashboard)"""
    admin_key = request.headers.get('X-Admin-Key')
    
    if admin_key != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    
    stats = load_json(STATS_FILE)
    return jsonify(stats)

@app.route('/api/admin/pending', methods=['GET'])
def get_pending():
    """Get pending purchases waiting for verification"""
    admin_key = request.headers.get('X-Admin-Key')
    
    if admin_key != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    
    pending = load_json(PENDING_FILE, {"purchases": []})
    return jsonify(pending)

@app.route('/api/admin/recent-purchases', methods=['GET'])
def get_recent_purchases():
    """Get recent confirmed purchases"""
    admin_key = request.headers.get('X-Admin-Key')
    
    if admin_key != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    
    purchases = load_json(PURCHASES_FILE, {"purchases": []})
    
    # Sort by timestamp, most recent first
    recent = sorted(
        purchases.get('purchases', []),
        key=lambda x: x.get('confirmed_at', ''),
        reverse=True
    )[:50]  # Last 50 purchases
    
    return jsonify({'purchases': recent})

# ==================== HELPER FUNCTIONS ====================

def update_stats(book_id, price):
    """Update statistics after confirmed purchase"""
    stats = load_json(STATS_FILE)
    
    # Initialize book stats if needed
    if book_id not in stats['books']:
        stats['books'][book_id] = {
            'total_downloads': 0,
            'free_downloads': 0,
            'paid_downloads': 0,
            'revenue': 0
        }
    
    # Update book stats
    stats['books'][book_id]['paid_downloads'] += 1
    stats['books'][book_id]['revenue'] += price
    
    # Update global stats
    stats['total_purchases'] = stats.get('total_purchases', 0) + 1
    stats['total_revenue'] = stats.get('total_revenue', 0) + price
    
    save_json(STATS_FILE, stats)

# ==================== RUN SERVER ====================

if __name__ == '__main__':
    print("=" * 60)
    print("📊 Book Purchase API Server")
    print("=" * 60)
    print(f"Admin Key: {ADMIN_KEY}")
    print("IMPORTANT: Change ADMIN_KEY before deploying!")
    print("=" * 60)
    
    # Development server (use gunicorn for production)

    app.run(host='0.0.0.0', port=5000, debug=True)
