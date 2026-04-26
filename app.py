from fyers_apiv3 import fyersModel
from flask import Flask, request, render_template_string, jsonify, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import webbrowser
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "sajid_secret_key_change_this"

# Text files for storing data
USERS_FILE = "users.txt"
CREDENTIALS_FILE = "user_credentials.txt"

# Predefined list of NSE Equity Stocks
NSE_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", 
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", 
    "LT", "AXISBANK", "BAJFINANCE", "MARUTI", "ASIANPAINT"
]

# Initialize files
def init_files():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'w') as f: f.write("")
    if not os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, 'w') as f: f.write("")

init_files()

# ---- User Management Functions ----
def save_user(username, password, email):
    with open(USERS_FILE, 'a') as f:
        f.write(f"{username}|{generate_password_hash(password)}|{email}\n")

def get_user(username):
    if not os.path.exists(USERS_FILE): return None
    with open(USERS_FILE, 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 3 and parts[0] == username:
                return {'username': parts[0], 'password': parts[1], 'email': parts[2]}
    return None

def verify_user(username, password):
    user = get_user(username)
    if user and check_password_hash(user['password'], password): return user
    return None

def save_user_credentials(username, client_id=None, secret_key=None, auth_code=None):
    credentials = {}
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, 'r') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) >= 4: credentials[parts[0]] = {'client_id': parts[1], 'secret_key': parts[2], 'auth_code': parts[3]}
    if username not in credentials: credentials[username] = {'client_id': '', 'secret_key': '', 'auth_code': ''}
    if client_id: credentials[username]['client_id'] = client_id
    if secret_key: credentials[username]['secret_key'] = secret_key
    if auth_code: credentials[username]['auth_code'] = auth_code
    with open(CREDENTIALS_FILE, 'w') as f:
        for u, c in credentials.items(): f.write(f"{u}|{c['client_id']}|{c['secret_key']}|{c['auth_code']}\n")

def get_user_credentials(username):
    if not os.path.exists(CREDENTIALS_FILE): return None
    with open(CREDENTIALS_FILE, 'r') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) >= 4 and parts[0] == username: return {'client_id': parts[1], 'secret_key': parts[2], 'auth_code': parts[3]}
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session: return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# ---- User-specific sessions ----
user_sessions = {}

# ---- In-Memory Store for Depth History ----
# Structure: { 'NSE:RELIANCE-EQ': [ {'time': '2023-10-27 09:20', 'buy_q': 1000, 'sell_q': 1200}, ... ] }
DEPTH_HISTORY = {}

def get_user_session(username):
    if username not in user_sessions:
        user_sessions[username] = {'fyers': None, 'redirect_uri': f'https://127.0.0.1/callback/{username}'}
    return user_sessions[username]

# ---- Fyers Functions ----
def init_fyers_for_user(username, client_id, secret_key, auth_code):
    user_sess = get_user_session(username)
    try:
        appSession = fyersModel.SessionModel(client_id=client_id, secret_key=secret_key, redirect_uri=user_sess['redirect_uri'], response_type="code", grant_type="authorization_code", state="sample")
        appSession.set_token(auth_code)
        token_response = appSession.generate_token()
        access_token = token_response.get("access_token")
        user_sess['fyers'] = fyersModel.FyersModel(client_id=client_id, token=access_token, is_async=False, log_path="")
        print(f"✅ Fyers initialized for {username}")
        return True
    except Exception as e:
        print(f"❌ Failed to init Fyers for {username}:", e)
        return False

def place_order(username, symbol, qty, side, product_type):
    user_sess = get_user_session(username)
    try:
        if user_sess['fyers'] is None: return {"error": "Fyers not initialized"}
        data = {"symbol": symbol, "qty": int(qty), "type": 2, "side": int(side), "productType": product_type, "limitPrice": 0, "stopPrice": 0, "validity": "DAY", "disclosedQty": 0, "offlineOrder": False, "orderTag": "tag1", "isSliceOrder": False}
        return user_sess['fyers'].place_order(data=data)
    except Exception as e: return {"error": str(e)}

# ---- Auth Routes ----
@app.route('/sp', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        u, p, e = request.form.get('username'), request.form.get('password'), request.form.get('email')
        if not u or not p or not e: return render_template_string(SIGNUP_TEMPLATE, error="All fields required!")
        if get_user(u): return render_template_string(SIGNUP_TEMPLATE, error="User exists!")
        save_user(u, p, e); return redirect(url_for('login_page'))
    return render_template_string(SIGNUP_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        u, p = request.form.get('username'), request.form.get('password')
        user = verify_user(u, p)
        if user:
            session['username'], session['email'] = user['username'], user['email']
            creds = get_user_credentials(u)
            if creds and creds['client_id'] and creds['secret_key'] and creds['auth_code']: init_fyers_for_user(u, creds['client_id'], creds['secret_key'], creds['auth_code'])
            return redirect(url_for('index'))
        return render_template_string(LOGIN_TEMPLATE, error="Invalid!")
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login_page'))

# ---- Helper ----
def get_nse_symbol(base_name):
    return f"NSE:{base_name}-EQ"

# ---- Main App Routes ----
@app.route("/")
@login_required
def index(): return redirect(url_for('nse_dashboard'))

@app.route("/nse")
@login_required
def nse_dashboard():
    username = session['username']
    selected_base = request.args.get('symbol', 'RELIANCE')
    default_symbol = get_nse_symbol(selected_base)
    return render_template_string(NSE_TEMPLATE, symbols=NSE_STOCKS, selected_base=selected_base, default_symbol=default_symbol, username=username)

# Route to get Live Quotes (LTP)
@app.route("/get_quote")
@login_required
def get_quote():
    username = session['username']
    user_sess = get_user_session(username)
    symbol = request.args.get('symbol')
    
    if not symbol: return jsonify({"error": "No symbol"})
    if user_sess['fyers'] is None: return jsonify({"error": "Not logged in"})

    try:
        response = user_sess['fyers'].quotes({"symbols": symbol})
        
        if "d" in response and len(response["d"]) > 0:
            data = response["d"][0]["v"]
            return jsonify({
                "ltp": data.get("lp", 0),
                "change": data.get("ch", 0),
                "change_pct": round(data.get("chp", 0), 2),
                "high": data.get("high", 0),
                "low": data.get("low", 0),
                "open": data.get("open_price", 0)
            })
        return jsonify({"error": "No data"})
    except Exception as e:
        return jsonify({"error": str(e)})

# Route for Live Intraday Data
@app.route("/get_live_chart")
@login_required
def get_live_chart():
    username = session['username']
    user_sess = get_user_session(username)
    symbol = request.args.get('symbol')
    
    if not symbol: return jsonify({"error": "No symbol"})
    if user_sess['fyers'] is None: return jsonify({"error": "Not logged in"})

    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        
        data = {
            "symbol": symbol, 
            "resolution": "1", 
            "date_format": "1", 
            "range_from": start_date, 
            "range_to": end_date, 
            "cont_flag": "0"
        }
        response = user_sess['fyers'].history(data=data)
        
        result = []
        if response.get('s') == 'ok' and 'candles' in response:
            for c in response['candles']:
                result.append({"time": datetime.fromtimestamp(c[0]).strftime('%d-%b %H:%M'), "price": c[4]})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})

# ---- FIXED: Route for Depth Chart Data ----
@app.route("/get_depth_data")
@login_required
def get_depth_data():
    username = session['username']
    user_sess = get_user_session(username)
    symbol = request.args.get('symbol')
    
    if not symbol: return jsonify({"error": "No symbol"})
    if user_sess['fyers'] is None: return jsonify({"error": "Not logged in"})

    try:
        # Fetch Market Depth
        depth_response = user_sess['fyers'].depth({"symbol": symbol, "depth": 5})
        
        if depth_response.get('s') != 'ok' or 'd' not in depth_response:
            return jsonify(DEPTH_HISTORY.get(symbol, []))

        depth_data = depth_response['d'][0]
        
        # CORRECTED PARSING: Fyers returns lists 'bq' (Buy Qty) and 'sq' (Sell Qty)
        # These are lists of strings or numbers representing quantity at each level
        buy_qtys = depth_data.get('bq', []) 
        sell_qtys = depth_data.get('sq', [])
        
        # Calculate Totals (handling string/int conversion safely)
        total_buy_qty = sum(int(q) for q in buy_qtys if str(q).isdigit())
        total_sell_qty = sum(int(q) for q in sell_qtys if str(q).isdigit())
        
        # Create a timestamp formatted for Chart.js Time Axis (YYYY-MM-DD HH:MM)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        # Initialize history for symbol if not exists
        if symbol not in DEPTH_HISTORY:
            DEPTH_HISTORY[symbol] = []
            
        # Append new data point
        history = DEPTH_HISTORY[symbol]
        history.append({
            "time": current_time, 
            "buy_q": total_buy_qty, 
            "sell_q": total_sell_qty
        })
        
        # Keep history manageable (last 500 points ~ 4 hours of 30s updates)
        if len(history) > 500:
            DEPTH_HISTORY[symbol] = history[-500:]
            
        return jsonify(DEPTH_HISTORY[symbol])
        
    except Exception as e:
        print(f"Depth Error: {e}")
        return jsonify({"error": str(e)})

@app.route("/place_nse_order", methods=["POST"])
@login_required
def place_nse_order():
    username = session['username']
    data = request.json
    symbol = data.get('symbol')
    try: qty, side = int(data.get('qty', 1)), int(data.get('side'))
    except: return jsonify({"error": "Invalid numbers"})
    
    if not symbol or not side: return jsonify({"error": "Missing data"})
    if not symbol.startswith("NSE:"): return jsonify({"error": "Must start with NSE:"})
    
    return jsonify(place_order(username, symbol, qty, side, data.get('product_type', 'INTRADAY')))

@app.route("/setup_credentials", methods=["GET", "POST"])
@login_required
def setup_credentials():
    username = session['username']
    creds = get_user_credentials(username)
    if request.method == "POST":
        cid, sec = request.form.get("client_id"), request.form.get("secret_key")
        if cid and sec: save_user_credentials(username, client_id=cid, secret_key=sec); return redirect(url_for('fyers_login'))
    return render_template_string(CREDENTIALS_TEMPLATE, client_id=creds['client_id'] if creds else "", secret_key=creds['secret_key'] if creds else "")

@app.route("/fyers_login")
@login_required
def fyers_login():
    username = session['username']
    creds = get_user_credentials(username)
    user_sess = get_user_session(username)
    if not creds or not creds['client_id'] or not creds['secret_key']: return redirect(url_for('setup_credentials'))
    sess = fyersModel.SessionModel(client_id=creds['client_id'], secret_key=creds['secret_key'], redirect_uri=user_sess['redirect_uri'], response_type="code", grant_type="authorization_code", state="sample")
    url = sess.generate_authcode(); webbrowser.open(url, new=1); return redirect(url)

@app.route("/callback/<username>")
def callback(username):
    auth_code = request.args.get("auth_code")
    if auth_code:
        creds = get_user_credentials(username)
        if creds:
            save_user_credentials(username, auth_code=auth_code)
            if init_fyers_for_user(username, creds['client_id'], creds['secret_key'], auth_code): return "<h2>✅ Success!</h2>"
    return "❌ Failed"

# ---- Templates ----
SIGNUP_TEMPLATE = """<!DOCTYPE html><html><head><title>Sign Up</title><style>body{font-family:Arial;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;justify-content:center;align-items:center;height:100vh}.box{background:#fff;padding:40px;border-radius:10px;width:400px;box-shadow:0 10px 25px rgba(0,0,0,0.2)}h2{text-align:center}input{width:100%;padding:12px;margin:10px 0;border:1px solid #ddd;border-radius:5px}button{width:100%;padding:12px;background:#667eea;color:#fff;border:none;border-radius:5px;cursor:pointer;margin-top:10px}.error{color:red;text-align:center}</style></head><body><div class="box"><h2>📝 Sign Up</h2>{% if error %}<div class="error">{{error}}</div>{% endif %}<form method="POST"><input name="username" placeholder="Username" required><input name="email" placeholder="Email" required><input name="password" type="password" placeholder="Password" required><button>Create</button></form></div></body></html>"""
LOGIN_TEMPLATE = """<!DOCTYPE html><html><head><title>Login</title><style>body{font-family:Arial;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;justify-content:center;align-items:center;height:100vh}.box{background:#fff;padding:40px;border-radius:10px;width:400px;box-shadow:0 10px 25px rgba(0,0,0,0.2)}h2{text-align:center}input{width:100%;padding:12px;margin:10px 0;border:1px solid #ddd;border-radius:5px}button{width:100%;padding:12px;background:#667eea;color:#fff;border:none;border-radius:5px;cursor:pointer;margin-top:10px}.error{color:red;text-align:center}</style></head><body><div class="box"><h2>🔐 Login</h2>{% if error %}<div class="error">{{error}}</div>{% endif %}<form method="POST"><input name="username" placeholder="Username" required><input name="password" type="password" placeholder="Password" required><button>Login</button></form></div></body></html>"""
CREDENTIALS_TEMPLATE = """<!DOCTYPE html><html><head><title>Creds</title><style>body{font-family:Arial;background:#f4f4f9;padding:20px}.box{max-width:600px;margin:50px auto;background:#fff;padding:40px;border-radius:10px}h2{color:#1a73e8;text-align:center}input{width:100%;padding:12px;margin:10px 0;border:1px solid #ddd;border-radius:5px}button{width:100%;padding:12px;background:#1a73e8;color:#fff;border:none;border-radius:5px;cursor:pointer;margin-top:10px}</style></head><body><div class="box"><h2>🔑 API Keys</h2><form method="POST"><input name="client_id" placeholder="Client ID" value="{{client_id}}" required><input name="secret_key" placeholder="Secret Key" value="{{secret_key}}" required><button>Save</button></form></div></body></html>"""

NSE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>NSE Equity Live Trading</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #f4f4f9; margin: 0; }
        .header { background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%); color: white; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; }
        .logout-btn { padding: 8px 15px; background: rgba(255,255,255,0.2); color: white; text-decoration: none; border-radius: 4px; margin-left: 10px; }
        .nav-link { padding: 8px 15px; background: #0d47a1; color: white; text-decoration: none; border-radius: 4px; margin-left: 10px; }
        
        .container { display: flex; height: calc(100vh - 70px); }
        .sidebar { width: 250px; background: white; border-right: 1px solid #ddd; overflow-y: auto; }
        .main-content { flex: 1; padding: 20px; overflow-y: auto; }
        
        .stock-item { padding: 12px; cursor: pointer; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; }
        .stock-item:hover { background: #f0f0f0; }
        .stock-item.active { background: #1a73e8; color: white; font-weight: bold; }

        .price-box { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        .price-main { display: flex; flex-direction: column; }
        .ltp { font-size: 36px; font-weight: bold; color: #333; }
        .change { font-size: 18px; font-weight: bold; margin-top: 5px; }
        .change.green { color: #4caf50; }
        .change.red { color: #f44336; }
        .ohlc { text-align: right; color: #666; font-size: 14px; }
        .live-badge { background: #4caf50; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; margin-left: 10px; }
        
        .chart-wrapper { display: flex; gap: 20px; margin-bottom: 20px; }
        .chart-box { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); flex: 1; position: relative; height: 300px; }
        .chart-title { position: absolute; top: 10px; left: 20px; font-weight: bold; color: #555; z-index: 10; background: rgba(255,255,255,0.8); padding: 2px 8px; border-radius: 4px;}
        
        .trade-panel { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: flex; align-items: center; gap: 15px; flex-wrap: wrap; }
        
        input, select { padding: 8px; border: 1px solid #ccc; border-radius: 4px; }
        input[type="number"] { width: 80px; }
        input[type="text"] { width: 200px; font-weight: bold; }
        .btn { padding: 10px 20px; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .btn-buy { background-color: #4caf50; }
        .btn-sell { background-color: #f44336; }
        .btn-search { background-color: #2196F3; padding: 8px 12px; }
        .btn:hover { opacity: 0.9; }
        
        .status-bar { margin-top: 10px; padding: 10px; background: #e8f5e9; border-radius: 4px; display: none; }
    </style>
</head>
<body>
    <div class="header">
        <h1>📈 NSE Equity Terminal</h1>
        <div>
            <span>Welcome, <strong>{{ username }}</strong>!</span>
            <a href="/setup_credentials" class="nav-link">⚙️ Credentials</a>
            <a href="/logout" class="logout-btn">Logout</a>
        </div>
    </div>

    <div class="container">
        <div class="sidebar">
            <h3 style="margin:0;padding:10px;border-bottom:1px solid #ddd">Top Stocks</h3>
            {% for sym in symbols %}
                <div class="stock-item {% if sym == selected_base %}active{% endif %}" onclick="selectStock('{{ sym }}')">
                    <span>{{ sym }}</span><span>▸</span>
                </div>
            {% endfor %}
        </div>

        <div class="main-content">
            <h2>{{ selected_base }} <span class="live-badge">🔴 LIVE</span></h2>

            <div class="price-box">
                <div class="price-main">
                    <div id="ltpDisplay" class="ltp">0.00</div>
                    <div id="changeDisplay" class="change green">+0.00 (0.00%)</div>
                </div>
                <div class="ohlc">
                    <div><strong>Open:</strong> <span id="openDisplay">0</span></div>
                    <div><strong>High:</strong> <span id="highDisplay">0</span></div>
                    <div><strong>Low:</strong> <span id="lowDisplay">0</span></div>
                </div>
            </div>
            
            <div class="chart-wrapper">
                <div class="chart-box">
                    <div class="chart-title">Price History</div>
                    <canvas id="stockChart"></canvas>
                </div>
                <div class="chart-box">
                    <div class="chart-title">Market Depth (Buy vs Sell Qty)</div>
                    <canvas id="depthChart"></canvas>
                </div>
            </div>

            <div class="trade-panel">
                <label>Symbol:</label>
                <input type="text" id="symbolInput" value="{{ default_symbol }}">
                <button class="btn btn-search" onclick="changeSymbol()">🔍</button>
                
                <label>Qty:</label>
                <input type="number" id="qty" value="1" min="1">
                
                <label>Type:</label>
                <select id="productType"><option value="INTRADAY">Intraday</option><option value="CNC">Delivery (CNC)</option></select>

                <button class="btn btn-buy" onclick="placeOrder(1)">BUY</button>
                <button class="btn btn-sell" onclick="placeOrder(-1)">SELL</button>
            </div>

            <div id="statusBar" class="status-bar"></div>
        </div>
    </div>

    <script>
        // --- Chart Setup ---
        const ctxPrice = document.getElementById('stockChart').getContext('2d');
        const ctxDepth = document.getElementById('depthChart').getContext('2d');

        // 1. Price Chart
        let priceChart = new Chart(ctxPrice, {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Price', data: [], borderColor: '#1a73e8', backgroundColor: 'rgba(26, 115, 232, 0.1)', borderWidth: 2, fill: true, tension: 0.1, pointRadius: 0 }] },
            options: { 
                responsive: true, 
                maintainAspectRatio: false,
                plugins: { legend: { display: false } }, 
                scales: { y: { beginAtZero: false }, x: { ticks: { maxTicksLimit: 6 } } } 
            }
        });

        // 2. Depth Chart (Time Series)
        let depthChart = new Chart(ctxDepth, {
            type: 'line',
            data: {
                datasets: [
                    {
                        label: 'Total Buy Qty',
                        data: [], // Will be [{x: '2023-10-27 09:15', y: 1000}, ...]
                        borderColor: 'rgba(76, 175, 80, 1)',
                        backgroundColor: 'rgba(76, 175, 80, 0.2)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: 0
                    },
                    {
                        label: 'Total Sell Qty',
                        data: [],
                        borderColor: 'rgba(244, 67, 54, 1)',
                        backgroundColor: 'rgba(244, 67, 54, 0.2)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: { legend: { position: 'bottom' } },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Quantity' } },
                    x: {
                        type: 'time',
                        time: {
                            unit: 'hour',
                            displayFormats: { hour: 'HH:mm' }
                        },
                        min: getMarketStart(), // 9:15 AM
                        max: getMarketEnd(),   // 3:30 PM
                        title: { display: true, text: 'Time (Market Hours)' }
                    }
                }
            }
        });

        // Helper for fixed axis
        function getMarketStart() {
            const d = new Date();
            return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 9, 15, 0);
        }
        function getMarketEnd() {
            const d = new Date();
            return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 15, 30, 0);
        }

        let liveInterval = null;
        let depthInterval = null;

        function selectStock(baseSym){
            window.location.href = "/nse?symbol=" + baseSym;
        }

        function changeSymbol(){
            if(liveInterval) clearInterval(liveInterval);
            if(depthInterval) clearInterval(depthInterval);
            
            priceChart.data.labels = []; 
            priceChart.data.datasets[0].data = []; 
            priceChart.update();
            
            depthChart.data.datasets[0].data = [];
            depthChart.data.datasets[1].data = [];
            depthChart.update();

            startLiveStreams();
        }

        function startLiveStreams(){
            const symbol = document.getElementById("symbolInput").value;
            
            updatePrice(symbol);
            liveInterval = setInterval(() => updatePrice(symbol), 2000);

            updatePriceChart(symbol);
            setInterval(() => updatePriceChart(symbol), 10000);

            updateDepthChart(symbol);
            depthInterval = setInterval(() => updateDepthChart(symbol), 5000); // 5 second update
        }

        function updatePrice(symbol){
            fetch("/get_quote?symbol=" + encodeURIComponent(symbol))
            .then(res => res.json())
            .then(data => {
                if(data.ltp){
                    const ltpDiv = document.getElementById("ltpDisplay");
                    ltpDiv.innerText = data.ltp.toFixed(2);

                    const changeDiv = document.getElementById("changeDisplay");
                    const ch = data.change || 0;
                    const chp = data.change_pct || 0;
                    
                    if(ch >= 0){
                        changeDiv.className = "change green";
                        changeDiv.innerText = "+" + ch.toFixed(2) + " (+" + chp.toFixed(2) + "%)";
                        ltpDiv.style.color = "#4caf50";
                    } else {
                        changeDiv.className = "change red";
                        changeDiv.innerText = ch.toFixed(2) + " (" + chp.toFixed(2) + "%)";
                        ltpDiv.style.color = "#f44336";
                    }

                    document.getElementById("openDisplay").innerText = data.open || '-';
                    document.getElementById("highDisplay").innerText = data.high || '-';
                    document.getElementById("lowDisplay").innerText = data.low || '-';
                }
            });
        }

        function updatePriceChart(symbol){
            fetch("/get_live_chart?symbol=" + encodeURIComponent(symbol))
            .then(res => res.json())
            .then(data => {
                if (Array.isArray(data) && data.length > 0) {
                    priceChart.data.labels = data.map(d => d.time);
                    priceChart.data.datasets[0].data = data.map(d => d.price);
                    priceChart.update('none');
                }
            });
        }

        // --- Depth Chart Logic ---
        function updateDepthChart(symbol){
            fetch("/get_depth_data?symbol=" + encodeURIComponent(symbol))
            .then(res => res.json())
            .then(rawData => {
                // Expecting format: [ {'time': '2023-10-27 09:20', 'buy_q': 1000, 'sell_q': 1200}, ... ]
                if (Array.isArray(rawData) && rawData.length > 0) {
                    // Map to Chart.js Time Series format: {x: time, y: value}
                    const buyData = rawData.map(d => ({ x: d.time, y: d.buy_q }));
                    const sellData = rawData.map(d => ({ x: d.time, y: d.sell_q }));

                    depthChart.data.datasets[0].data = buyData;
                    depthChart.data.datasets[1].data = sellData;
                    depthChart.update('none');
                }
            });
        }

        window.onload = startLiveStreams;

        function placeOrder(side){
            const symbol = document.getElementById("symbolInput").value;
            const qtyVal = document.getElementById("qty").value;
            const productType = document.getElementById("productType").value;
            const statusDiv = document.getElementById("statusBar");
            
            if(!symbol.startsWith("NSE:")) {
                statusDiv.style.display = "block"; statusDiv.style.background = "#ffebee"; statusDiv.innerHTML = "❌ Symbol must start with NSE:"; return;
            }

            statusDiv.style.display = "block"; statusDiv.style.background = "#fff3e0"; statusDiv.innerHTML = "⏳ Placing order...";

            fetch("/place_nse_order", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ symbol: symbol, qty: qtyVal, side: side, product_type: productType })
            })
            .then(res => res.json())
            .then(data => {
                if(data.id){
                    statusDiv.style.background = "#e8f5e9"; statusDiv.innerHTML = "✅ Order Placed! ID: " + data.id;
                } else {
                    statusDiv.style.background = "#ffebee"; statusDiv.innerHTML = "❌ Error: " + (data.message || data.error || JSON.stringify(data));
                }
            })
            .catch(err => { statusDiv.style.background = "#ffebee"; statusDiv.innerHTML = "❌ Request Failed: " + err; });
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    print("\n" + "="*60)
    print("🚀 NSE EQUITY LIVE Trading Bot")
    print("="*60)
    print(f"📍 Server: http://127.0.0.1:{port}")
    print("📈 Segment: NSE Equity (Cash)")
    print("="*60 + "\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
