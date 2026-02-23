"""
Backend API Server for Book Purchase Tracking
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import json
from pathlib import Path
from datetime import datetime
import secrets
import requests

app = Flask(__name__)
CORS(app)

# Data files
PURCHASES_FILE = Path("data/purchases.json")
STATS_FILE     = Path("data/stats.json")
PENDING_FILE   = Path("data/pending.json")
ADMIN_KEY      = "LiveKitaabAdminHaiAC@2014"

Path("data").mkdir(exist_ok=True)

def load_json(filepath, default=None):
    if not filepath.exists():
        return default or {}
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except:
        return default or {}

def save_json(filepath, data):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

def init_stats():
    if not STATS_FILE.exists():
        save_json(STATS_FILE, {
            "books": {},
            "total_revenue": 0,
            "total_purchases": 0
        })

init_stats()

# ==================== PROXY ====================

@app.route('/proxy')
def proxy():
    target = request.args.get('url')
    if not target:
        return jsonify({'error': 'Missing url'}), 400
    try:
        session = requests.Session()
        session.max_redirects = 10
        r = session.get(
            target,
            stream=True,
            allow_redirects=True,
            headers={
                'User-Agent': 'Mozilla/5.0',
                'Accept': '*/*'
            },
            timeout=60
        )
        if r.status_code != 200:
            return jsonify({'error': f'Upstream returned {r.status_code}', 'url': r.url}), 502

        return Response(
            r.iter_content(chunk_size=8192),
            content_type='application/octet-stream',
            headers={'Access-Control-Allow-Origin': '*'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== PUBLIC ENDPOINTS ====================

@app.route('/')
def home():
    return jsonify({'status': 'online', 'service': 'Book Purchase API'})

@app.route('/api/request-purchase', methods=['POST'])
def request_purchase():
    data = request.json
    book_id        = data.get('book_id')
    price          = data.get('price', 0)
    transaction_id = data.get('transaction_id')

    if not book_id or not transaction_id:
        return jsonify({'error': 'Missing required fields'}), 400

    verification_code = secrets.token_hex(4).upper()
    pending   = load_json(PENDING_FILE, {"purchases": []})
    purchases = load_json(PURCHASES_FILE, {"purchases": []})

    for purchase in purchases.get('purchases', []):
        if purchase.get('transaction_id') == transaction_id:
            return jsonify({'error': 'Transaction ID already used'}), 400

    pending['purchases'].append({
        'verification_code': verification_code,
        'book_id':           book_id,
        'price':             price,
        'transaction_id':    transaction_id,
        'timestamp':         datetime.now().isoformat(),
        'status':            'pending'
    })
    save_json(PENDING_FILE, pending)

    return jsonify({
        'success':           True,
        'verification_code': verification_code,
        'message':           f'Please confirm this code: {verification_code}'
    })

@app.route('/api/verify-purchase', methods=['POST'])
def verify_purchase():
    data              = request.json
    verification_code = data.get('verification_code')
    admin_key         = data.get('admin_key')

    if admin_key != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    if not verification_code:
        return jsonify({'error': 'Missing verification code'}), 400

    pending = load_json(PENDING_FILE, {"purchases": []})
    purchase_to_verify = None
    remaining = []

    for p in pending.get('purchases', []):
        if p.get('verification_code') == verification_code:
            purchase_to_verify = p
        else:
            remaining.append(p)

    if not purchase_to_verify:
        return jsonify({'error': 'Verification code not found'}), 404

    purchases = load_json(PURCHASES_FILE, {"purchases": []})
    purchase_to_verify['status']       = 'confirmed'
    purchase_to_verify['confirmed_at'] = datetime.now().isoformat()
    purchases['purchases'].append(purchase_to_verify)
    save_json(PURCHASES_FILE, purchases)

    pending['purchases'] = remaining
    save_json(PENDING_FILE, pending)
    update_stats(purchase_to_verify['book_id'], purchase_to_verify['price'])

    return jsonify({
        'success':        True,
        'book_id':        purchase_to_verify['book_id'],
        'transaction_id': purchase_to_verify['transaction_id']
    })

@app.route('/api/check-purchase', methods=['POST'])
def check_purchase():
    data           = request.json
    book_id        = data.get('book_id')
    transaction_id = data.get('transaction_id')

    if not book_id or not transaction_id:
        return jsonify({'error': 'Missing required fields'}), 400

    purchases = load_json(PURCHASES_FILE, {"purchases": []})
    for p in purchases.get('purchases', []):
        if (p.get('book_id') == book_id and
                p.get('transaction_id') == transaction_id and
                p.get('status') == 'confirmed'):
            return jsonify({'purchased': True, 'confirmed_at': p.get('confirmed_at')})

    pending = load_json(PENDING_FILE, {"purchases": []})
    for p in pending.get('purchases', []):
        if p.get('book_id') == book_id and p.get('transaction_id') == transaction_id:
            return jsonify({
                'purchased':         False,
                'status':            'pending',
                'verification_code': p.get('verification_code')
            })

    return jsonify({'purchased': False, 'status': 'not_found'})

@app.route('/api/track-download', methods=['POST'])
def track_download():
    data    = request.json
    book_id = data.get('book_id')
    is_free = data.get('is_free', False)

    if not book_id:
        return jsonify({'error': 'Missing book_id'}), 400

    stats = load_json(STATS_FILE)
    if book_id not in stats['books']:
        stats['books'][book_id] = {
            'total_downloads': 0, 'free_downloads': 0,
            'paid_downloads': 0,  'revenue': 0
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
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(load_json(STATS_FILE))

@app.route('/api/admin/pending', methods=['GET'])
def get_pending():
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(load_json(PENDING_FILE, {"purchases": []}))

@app.route('/api/admin/recent-purchases', methods=['GET'])
def get_recent_purchases():
    if request.headers.get('X-Admin-Key') != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    purchases = load_json(PURCHASES_FILE, {"purchases": []})
    recent = sorted(
        purchases.get('purchases', []),
        key=lambda x: x.get('confirmed_at', ''),
        reverse=True
    )[:50]
    return jsonify({'purchases': recent})

# ==================== HELPERS ====================

def update_stats(book_id, price):
    stats = load_json(STATS_FILE)
    if book_id not in stats['books']:
        stats['books'][book_id] = {
            'total_downloads': 0, 'free_downloads': 0,
            'paid_downloads': 0,  'revenue': 0
        }
    stats['books'][book_id]['paid_downloads'] += 1
    stats['books'][book_id]['revenue']         += price
    stats['total_purchases'] = stats.get('total_purchases', 0) + 1
    stats['total_revenue']   = stats.get('total_revenue', 0)   + price
    save_json(STATS_FILE, stats)

# ==================== RUN ====================

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    print("=" * 60)
    print("📊 Book Purchase API Server")
    print(f"Port: {port}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False)

