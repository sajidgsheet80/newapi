from fyers_apiv3 import fyersModel
from flask import Flask, request, render_template_string, jsonify, redirect, url_for, session
import webbrowser
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "simple_secret"

# ---- HARDCODED CREDENTIALS ----
CLIENT_ID = "JFSHKMD0A8-200"
SECRET_KEY = "xFB61Xa58rBN8SWP"
REDIRECT_URI = "http://127.0.0.1:5000/callback"

# ---- GLOBAL SESSION ----
fyers = None
auth_code_stored = None

# Predefined NSE Stocks
NSE_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", 
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", 
    "LT", "AXISBANK", "BAJFINANCE", "MARUTI", "ASIANPAINT"
]

# Depth History
DEPTH_HISTORY = {}

def get_nse_symbol(base_name):
    return f"NSE:{base_name}-EQ"

def init_fyers(auth_code):
    global fyers
    try:
        sess = fyersModel.SessionModel(
            client_id=CLIENT_ID, 
            secret_key=SECRET_KEY, 
            redirect_uri=REDIRECT_URI, 
            response_type="code", 
            grant_type="authorization_code"
        )
        sess.set_token(auth_code)
        token_response = sess.generate_token()
        access_token = token_response.get("access_token")
        fyers = fyersModel.FyersModel(client_id=CLIENT_ID, token=access_token, is_async=False, log_path="")
        print("✅ Fyers initialized successfully!")
        return True
    except Exception as e:
        print(f"❌ Failed to init Fyers: {e}")
        return False

# =====================================================
#              LOGIN SCREEN ROUTES
# =====================================================

@app.route("/login")
def login_page():
    # If already connected, redirect to main screen
    if fyers is not None:
        return redirect(url_for('main_dashboard'))
    return render_template_string(LOGIN_TEMPLATE)

@app.route("/")
def index():
    if fyers is not None:
        return redirect(url_for('main_dashboard'))
    return redirect(url_for('login_page'))

@app.route("/do_login")
def do_login():
    sess = fyersModel.SessionModel(
        client_id=CLIENT_ID, 
        secret_key=SECRET_KEY, 
        redirect_uri=REDIRECT_URI, 
        response_type="code", 
        grant_type="authorization_code"
    )
    auth_url = sess.generate_authcode()
    webbrowser.open(auth_url, new=1)
    return render_template_string(LOGIN_WAITING_TEMPLATE)

@app.route("/callback")
def callback():
    global auth_code_stored
    auth_code = request.args.get("auth_code")
    if auth_code:
        auth_code_stored = auth_code
        if init_fyers(auth_code):
            return redirect(url_for('main_dashboard'))
    return render_template_string(LOGIN_ERROR_TEMPLATE)

# =====================================================
#           MAIN TRADING DASHBOARD ROUTES
# =====================================================

@app.route("/dashboard")
def main_dashboard():
    if fyers is None:
        return redirect(url_for('login_page'))
    selected_base = request.args.get('symbol', 'RELIANCE')
    default_symbol = get_nse_symbol(selected_base)
    return render_template_string(DASHBOARD_TEMPLATE, symbols=NSE_STOCKS, selected_base=selected_base, default_symbol=default_symbol)

@app.route("/logout")
def logout():
    global fyers, DEPTH_HISTORY
    fyers = None
    DEPTH_HISTORY = {}
    return redirect(url_for('login_page'))

@app.route("/get_quote")
def get_quote():
    if fyers is None: return jsonify({"error": "Not connected"})
    symbol = request.args.get('symbol')
    if not symbol: return jsonify({"error": "No symbol"})
    try:
        response = fyers.quotes({"symbols": symbol})
        if "d" in response and len(response["d"]) > 0:
            data = response["d"][0]["v"]
            return jsonify({
                "ltp": data.get("lp", 0),
                "change": data.get("ch", 0),
                "change_pct": round(data.get("chp", 0), 2),
                "high": data.get("high", 0),
                "low": data.get("low", 0),
                "open": data.get("open_price", 0),
                "close": data.get("close_price", 0),
                "volume": data.get("total_traded_volume", 0)
            })
        return jsonify({"error": "No data"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/get_live_chart")
def get_live_chart():
    if fyers is None: return jsonify({"error": "Not connected"})
    symbol = request.args.get('symbol')
    if not symbol: return jsonify({"error": "No symbol"})
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        data = {
            "symbol": symbol, "resolution": "1", "date_format": "1",
            "range_from": start_date, "range_to": end_date, "cont_flag": "0"
        }
        response = fyers.history(data=data)
        result = []
        if response.get('s') == 'ok' and 'candles' in response:
            for c in response['candles']:
                result.append({"time": datetime.fromtimestamp(c[0]).strftime('%d-%b %H:%M'), "price": c[4], "open": c[1], "high": c[2], "low": c[3], "vol": c[5]})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/get_depth_data")
def get_depth_data():
    if fyers is None: return jsonify({"error": "Not connected"})
    symbol = request.args.get('symbol')
    if not symbol: return jsonify({"error": "No symbol"})
    try:
        depth_response = fyers.depth({"symbol": symbol, "depth": 5})
        if depth_response.get('s') != 'ok' or 'd' not in depth_response:
            return jsonify(DEPTH_HISTORY.get(symbol, []))
        
        depth_data = depth_response['d'][0]
        buy_qtys = depth_data.get('bq', [])
        sell_qtys = depth_data.get('sq', [])
        
        total_buy_qty = sum(int(q) for q in buy_qtys if str(q).isdigit())
        total_sell_qty = sum(int(q) for q in sell_qtys if str(q).isdigit())
        
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        if symbol not in DEPTH_HISTORY:
            DEPTH_HISTORY[symbol] = []
        
        DEPTH_HISTORY[symbol].append({
            "time": current_time,
            "buy_q": total_buy_qty,
            "sell_q": total_sell_qty
        })
        
        if len(DEPTH_HISTORY[symbol]) > 500:
            DEPTH_HISTORY[symbol] = DEPTH_HISTORY[symbol][-500:]
        
        return jsonify(DEPTH_HISTORY[symbol])
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/get_orderbook")
def get_orderbook():
    if fyers is None: return jsonify({"error": "Not connected"})
    try:
        response = fyers.orderbook()
        return jsonify(response)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/get_positions")
def get_positions():
    if fyers is None: return jsonify({"error": "Not connected"})
    try:
        response = fyers.positions()
        return jsonify(response)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/place_order", methods=["POST"])
def place_order():
    if fyers is None: return jsonify({"error": "Not connected"})
    data = request.json
    symbol = data.get('symbol')
    try:
        qty, side = int(data.get('qty', 1)), int(data.get('side'))
    except:
        return jsonify({"error": "Invalid numbers"})
    
    if not symbol or not side: return jsonify({"error": "Missing data"})
    
    try:
        order_data = {
            "symbol": symbol, "qty": qty, "type": 2, "side": side,
            "productType": data.get('product_type', 'INTRADAY'),
            "limitPrice": 0, "stopPrice": 0, "validity": "DAY",
            "disclosedQty": 0, "offlineOrder": False, "orderTag": "tag1"
        }
        return jsonify(fyers.place_order(data=order_data))
    except Exception as e:
        return jsonify({"error": str(e)})

# =====================================================
#              LOGIN SCREEN TEMPLATE
# =====================================================

LOGIN_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fyers Login - NSE Trading Terminal</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', sans-serif;
            min-height: 100vh;
            background: #0a0e17;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            position: relative;
        }

        /* Animated Background */
        .bg-grid {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background-image: 
                linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
            background-size: 50px 50px;
            animation: gridMove 20s linear infinite;
        }
        @keyframes gridMove {
            0% { transform: translate(0, 0); }
            100% { transform: translate(50px, 50px); }
        }

        .bg-glow {
            position: absolute;
            border-radius: 50%;
            filter: blur(100px);
            opacity: 0.3;
            animation: floatGlow 8s ease-in-out infinite;
        }
        .bg-glow-1 { width: 400px; height: 400px; background: #00d4aa; top: -100px; right: -100px; }
        .bg-glow-2 { width: 350px; height: 350px; background: #0066ff; bottom: -100px; left: -100px; animation-delay: -4s; }
        .bg-glow-3 { width: 200px; height: 200px; background: #ff6b35; top: 50%; left: 50%; transform: translate(-50%, -50%); animation-delay: -2s; }
        @keyframes floatGlow {
            0%, 100% { transform: translate(0, 0) scale(1); }
            50% { transform: translate(30px, -30px) scale(1.1); }
        }

        /* Login Card */
        .login-container {
            position: relative;
            z-index: 10;
            width: 100%;
            max-width: 480px;
            padding: 20px;
        }

        .login-card {
            background: rgba(15, 20, 35, 0.85);
            backdrop-filter: blur(40px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 24px;
            padding: 50px 40px;
            text-align: center;
            box-shadow: 
                0 25px 60px rgba(0, 0, 0, 0.5),
                inset 0 1px 0 rgba(255, 255, 255, 0.05);
        }

        .logo-section {
            margin-bottom: 40px;
        }

        .logo-icon {
            width: 80px;
            height: 80px;
            margin: 0 auto 20px;
            background: linear-gradient(135deg, #00d4aa, #0066ff);
            border-radius: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 36px;
            box-shadow: 0 10px 30px rgba(0, 212, 170, 0.3);
            animation: logoPulse 3s ease-in-out infinite;
        }
        @keyframes logoPulse {
            0%, 100% { box-shadow: 0 10px 30px rgba(0, 212, 170, 0.3); }
            50% { box-shadow: 0 10px 50px rgba(0, 212, 170, 0.5); }
        }

        .login-card h1 {
            color: #ffffff;
            font-size: 26px;
            font-weight: 700;
            letter-spacing: -0.5px;
            margin-bottom: 8px;
        }

        .login-card .subtitle {
            color: rgba(255, 255, 255, 0.5);
            font-size: 14px;
            font-weight: 400;
        }

        /* Connection Info */
        .connection-info {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 32px;
            text-align: left;
        }

        .info-row {
            display: flex;
            align-items: center;
            padding: 8px 0;
        }
        .info-row:not(:last-child) {
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        }

        .info-label {
            color: rgba(255, 255, 255, 0.4);
            font-size: 11px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            width: 100px;
            flex-shrink: 0;
        }

        .info-value {
            color: rgba(255, 255, 255, 0.8);
            font-size: 13px;
            font-family: 'Courier New', monospace;
            font-weight: 500;
        }

        /* Login Button */
        .login-btn {
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #00d4aa 0%, #00b894 100%);
            color: #0a0e17;
            border: none;
            border-radius: 14px;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s ease;
            letter-spacing: 0.3px;
            position: relative;
            overflow: hidden;
        }
        .login-btn::before {
            content: '';
            position: absolute;
            top: 0; left: -100%; width: 100%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            transition: left 0.5s ease;
        }
        .login-btn:hover::before { left: 100%; }
        .login-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(0, 212, 170, 0.4);
        }
        .login-btn:active { transform: translateY(0); }

        /* Features */
        .features {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 12px;
            margin-top: 32px;
            padding-top: 28px;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
        }

        .feature-item {
            text-align: center;
        }

        .feature-icon {
            font-size: 20px;
            margin-bottom: 6px;
        }

        .feature-text {
            color: rgba(255, 255, 255, 0.35);
            font-size: 11px;
            font-weight: 500;
        }

        /* Footer */
        .login-footer {
            margin-top: 24px;
            color: rgba(255, 255, 255, 0.2);
            font-size: 12px;
        }

        /* Ticker Animation */
        .ticker-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: rgba(15, 20, 35, 0.9);
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            padding: 10px 0;
            overflow: hidden;
            z-index: 20;
        }

        .ticker-content {
            display: flex;
            animation: tickerScroll 30s linear infinite;
            white-space: nowrap;
        }

        .ticker-item {
            padding: 0 30px;
            color: rgba(255, 255, 255, 0.4);
            font-size: 12px;
            font-family: 'Courier New', monospace;
        }
        .ticker-item .green { color: #00d4aa; }
        .ticker-item .red { color: #ff4757; }

        @keyframes tickerScroll {
            0% { transform: translateX(0); }
            100% { transform: translateX(-50%); }
        }
    </style>
</head>
<body>
    <div class="bg-grid"></div>
    <div class="bg-glow bg-glow-1"></div>
    <div class="bg-glow bg-glow-2"></div>
    <div class="bg-glow bg-glow-3"></div>

    <div class="login-container">
        <div class="login-card">
            <div class="logo-section">
                <div class="logo-icon">📈</div>
                <h1>NSE Trading Terminal</h1>
                <p class="subtitle">Connect your Fyers account to start trading</p>
            </div>

            <div class="connection-info">
                <div class="info-row">
                    <span class="info-label">Client ID</span>
                    <span class="info-value">JFSHKMD0A8-200</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Exchange</span>
                    <span class="info-value">NSE (National Stock Exchange)</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Callback</span>
                    <span class="info-value">127.0.0.1:5000/callback</span>
                </div>
            </div>

            <a href="/do_login" style="text-decoration:none;">
                <button class="login-btn">
                    🔐 Connect with Fyers
                </button>
            </a>

            <div class="features">
                <div class="feature-item">
                    <div class="feature-icon">⚡</div>
                    <div class="feature-text">Live Quotes</div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">📊</div>
                    <div class="feature-text">Depth Data</div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">🎯</div>
                    <div class="feature-text">Quick Order</div>
                </div>
            </div>

            <p class="login-footer">Secure • Encrypted • SEBI Registered</p>
        </div>
    </div>

    <div class="ticker-bar">
        <div class="ticker-content">
            <span class="ticker-item">RELIANCE <span class="green">+2.45%</span> ₹2,945.30</span>
            <span class="ticker-item">TCS <span class="red">-0.82%</span> ₹3,812.55</span>
            <span class="ticker-item">HDFCBANK <span class="green">+1.12%</span> ₹1,687.20</span>
            <span class="ticker-item">INFY <span class="green">+0.95%</span> ₹1,534.80</span>
            <span class="ticker-item">ICICIBANK <span class="red">-0.34%</span> ₹1,098.45</span>
            <span class="ticker-item">SBIN <span class="green">+1.87%</span> ₹758.90</span>
            <span class="ticker-item">BAJFINANCE <span class="green">+3.21%</span> ₹7,234.10</span>
            <span class="ticker-item">ITC <span class="red">-0.15%</span> ₹445.60</span>
            <span class="ticker-item">RELIANCE <span class="green">+2.45%</span> ₹2,945.30</span>
            <span class="ticker-item">TCS <span class="red">-0.82%</span> ₹3,812.55</span>
            <span class="ticker-item">HDFCBANK <span class="green">+1.12%</span> ₹1,687.20</span>
            <span class="ticker-item">INFY <span class="green">+0.95%</span> ₹1,534.80</span>
        </div>
    </div>
</body>
</html>"""

LOGIN_WAITING_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>Connecting...</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', sans-serif; min-height: 100vh; background: #0a0e17; display: flex; align-items: center; justify-content: center; }
        .waiting-card {
            background: rgba(15, 20, 35, 0.9);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 24px;
            padding: 60px 50px;
            text-align: center;
            max-width: 420px;
        }
        .spinner {
            width: 60px; height: 60px;
            border: 3px solid rgba(255,255,255,0.1);
            border-top-color: #00d4aa;
            border-radius: 50%;
            margin: 0 auto 30px;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        h2 { color: #fff; font-size: 22px; margin-bottom: 12px; }
        p { color: rgba(255,255,255,0.5); font-size: 14px; line-height: 1.6; }
        .steps { margin-top: 30px; text-align: left; }
        .step { display: flex; align-items: flex-start; gap: 12px; padding: 10px 0; color: rgba(255,255,255,0.6); font-size: 13px; }
        .step-num { 
            width: 24px; height: 24px; border-radius: 50%; 
            background: rgba(0,212,170,0.15); color: #00d4aa;
            display: flex; align-items: center; justify-content: center;
            font-size: 12px; font-weight: 600; flex-shrink: 0;
        }
        .back-link { margin-top: 30px; }
        .back-link a { color: rgba(255,255,255,0.4); text-decoration: none; font-size: 13px; }
        .back-link a:hover { color: #00d4aa; }
    </style>
</head>
<body>
    <div class="waiting-card">
        <div class="spinner"></div>
        <h2>Connecting to Fyers</h2>
        <p>Complete the login in the browser window that opened</p>
        <div class="steps">
            <div class="step"><span class="step-num">1</span><span>Login with your Fyers credentials</span></div>
            <div class="step"><span class="step-num">2</span><span>Approve the access if prompted</span></div>
            <div class="step"><span class="step-num">3</span><span>You'll be redirected automatically</span></div>
        </div>
        <div class="back-link"><a href="/login">← Back to Login</a></div>
    </div>
</body>
</html>"""

LOGIN_ERROR_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>Login Failed</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', sans-serif; min-height: 100vh; background: #0a0e17; display: flex; align-items: center; justify-content: center; }
        .error-card {
            background: rgba(15, 20, 35, 0.9);
            border: 1px solid rgba(255,67,67,0.2);
            border-radius: 24px;
            padding: 60px 50px;
            text-align: center;
            max-width: 420px;
        }
        .error-icon { font-size: 60px; margin-bottom: 20px; }
        h2 { color: #ff4757; font-size: 22px; margin-bottom: 12px; }
        p { color: rgba(255,255,255,0.5); font-size: 14px; line-height: 1.6; margin-bottom: 30px; }
        .retry-btn {
            padding: 14px 40px;
            background: linear-gradient(135deg, #00d4aa, #00b894);
            color: #0a0e17;
            border: none;
            border-radius: 12px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }
        .retry-btn:hover { opacity: 0.9; }
    </style>
</head>
<body>
    <div class="error-card">
        <div class="error-icon">⚠️</div>
        <h2>Authentication Failed</h2>
        <p>Could not retrieve authorization code. This might happen if the session expired or you denied access.</p>
        <a href="/login" class="retry-btn">Try Again</a>
    </div>
</body>
</html>"""

# =====================================================
#           MAIN DASHBOARD TEMPLATE
# =====================================================

DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ selected_base }} - NSE Trading Terminal</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', sans-serif; background: #0a0e17; color: #fff; overflow: hidden; height: 100vh; }

        /* Top Bar */
        .topbar {
            height: 56px;
            background: rgba(15, 20, 35, 0.95);
            border-bottom: 1px solid rgba(255,255,255,0.06);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 20px;
            backdrop-filter: blur(20px);
        }
        .topbar-left { display: flex; align-items: center; gap: 16px; }
        .topbar-logo { font-size: 20px; }
        .topbar-title { font-size: 14px; color: rgba(255,255,255,0.7); font-weight: 500; }
        .topbar-right { display: flex; align-items: center; gap: 12px; }
        .live-dot { width: 8px; height: 8px; background: #00d4aa; border-radius: 50%; animation: blink 1.5s infinite; }
        @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
        .live-label { font-size: 11px; color: #00d4aa; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
        .logout-btn {
            padding: 6px 16px;
            background: rgba(255,67,67,0.1);
            border: 1px solid rgba(255,67,67,0.2);
            color: #ff4757;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
        }
        .logout-btn:hover { background: rgba(255,67,67,0.2); }

        /* Main Layout */
        .main-layout { display: flex; height: calc(100vh - 56px); }

        /* Sidebar */
        .sidebar {
            width: 240px;
            background: rgba(15, 20, 35, 0.6);
            border-right: 1px solid rgba(255,255,255,0.06);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }
        .sidebar-header {
            padding: 14px 16px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: rgba(255,255,255,0.3);
        }
        .stock-list { flex: 1; overflow-y: auto; }
        .stock-list::-webkit-scrollbar { width: 4px; }
        .stock-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
        .stock-item {
            padding: 12px 16px;
            cursor: pointer;
            border-bottom: 1px solid rgba(255,255,255,0.03);
            transition: all 0.15s;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .stock-item:hover { background: rgba(255,255,255,0.04); }
        .stock-item.active { background: rgba(0, 212, 170, 0.1); border-left: 3px solid #00d4aa; }
        .stock-item .name { font-size: 13px; font-weight: 500; color: rgba(255,255,255,0.8); }
        .stock-item.active .name { color: #00d4aa; }
        .stock-item .arrow { color: rgba(255,255,255,0.2); font-size: 12px; }

        /* Content Area */
        .content { flex: 1; overflow-y: auto; padding: 20px; }
        .content::-webkit-scrollbar { width: 6px; }
        .content::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }

        /* Stock Header */
        .stock-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        .stock-name-section h2 { font-size: 24px; font-weight: 700; margin-bottom: 4px; }
        .stock-name-section .exchange { font-size: 12px; color: rgba(255,255,255,0.4); }
        .stock-price-section { text-align: right; }
        .ltp-price { font-size: 32px; font-weight: 800; letter-spacing: -0.5px; }
        .ltp-price.green { color: #00d4aa; }
        .ltp-price.red { color: #ff4757; }
        .price-change { font-size: 14px; font-weight: 600; margin-top: 2px; }
        .price-change.green { color: #00d4aa; }
        .price-change.red { color: #ff4757; }

        /* Stats Row */
        .stats-row {
            display: grid;
            grid-template-columns: repeat(6, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 12px;
            padding: 14px;
        }
        .stat-label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: rgba(255,255,255,0.3); margin-bottom: 6px; }
        .stat-value { font-size: 15px; font-weight: 600; color: rgba(255,255,255,0.9); }

        /* Charts Grid */
        .charts-grid {
            display: grid;
            grid-template-columns: 1.5fr 1fr;
            gap: 16px;
            margin-bottom: 20px;
        }
        .chart-card {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 14px;
            padding: 20px;
            position: relative;
        }
        .chart-card-title {
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: rgba(255,255,255,0.4);
            margin-bottom: 16px;
        }
        .chart-container { position: relative; height: 250px; }

        /* Trading Panel */
        .trade-panel {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 14px;
            padding: 20px;
        }
        .trade-panel-header {
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: rgba(255,255,255,0.4);
            margin-bottom: 16px;
        }
        .trade-form {
            display: flex;
            align-items: center;
            gap: 14px;
            flex-wrap: wrap;
        }
        .trade-form label { font-size: 12px; color: rgba(255,255,255,0.5); font-weight: 500; }
        .trade-input {
            padding: 10px 14px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            color: #fff;
            font-size: 13px;
            font-family: 'Inter', sans-serif;
            outline: none;
            transition: border-color 0.2s;
        }
        .trade-input:focus { border-color: #00d4aa; }
        .trade-input[type="number"] { width: 80px; }
        .trade-input[type="text"] { width: 220px; font-family: 'Courier New', monospace; font-weight: 600; }
        .trade-select {
            padding: 10px 14px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            color: #fff;
            font-size: 13px;
            font-family: 'Inter', sans-serif;
            outline: none;
            cursor: pointer;
        }
        .trade-select option { background: #1a1f2e; color: #fff; }
        .btn-buy, .btn-sell {
            padding: 12px 32px;
            border: none;
            border-radius: 10px;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .btn-buy { background: linear-gradient(135deg, #00d4aa, #00b894); color: #0a0e17; }
        .btn-buy:hover { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(0,212,170,0.3); }
        .btn-sell { background: linear-gradient(135deg, #ff4757, #ff3344); color: #fff; }
        .btn-sell:hover { transform: translateY(-1px); box-shadow: 0 6px 20px rgba(255,71,87,0.3); }

        /* Status Toast */
        .status-toast {
            margin-top: 14px;
            padding: 12px 16px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 500;
            display: none;
        }
        .status-toast.success { display: block; background: rgba(0,212,170,0.1); border: 1px solid rgba(0,212,170,0.2); color: #00d4aa; }
        .status-toast.error { display: block; background: rgba(255,71,87,0.1); border: 1px solid rgba(255,71,87,0.2); color: #ff4757; }
        .status-toast.pending { display: block; background: rgba(255,165,0,0.1); border: 1px solid rgba(255,165,0,0.2); color: #ffa500; }

        /* Bottom Bar */
        .bottom-bar {
            position: fixed;
            bottom: 0;
            left: 240px;
            right: 0;
            height: 32px;
            background: rgba(15, 20, 35, 0.95);
            border-top: 1px solid rgba(255,255,255,0.06);
            display: flex;
            align-items: center;
            padding: 0 16px;
            font-size: 11px;
            color: rgba(255,255,255,0.3);
            gap: 20px;
            z-index: 10;
        }
        .bottom-bar .sep { width: 1px; height: 14px; background: rgba(255,255,255,0.1); }
    </style>
</head>
<body>
    <!-- TOP BAR -->
    <div class="topbar">
        <div class="topbar-left">
            <span class="topbar-logo">📈</span>
            <span class="topbar-title">NSE Equity Terminal</span>
        </div>
        <div class="topbar-right">
            <div class="live-dot"></div>
            <span class="live-label">Live</span>
            <a href="/logout" class="logout-btn">⏻ Disconnect</a>
        </div>
    </div>

    <!-- MAIN LAYOUT -->
    <div class="main-layout">
        <!-- SIDEBAR -->
        <div class="sidebar">
            <div class="sidebar-header">Watchlist</div>
            <div class="stock-list">
                {% for sym in symbols %}
                    <div class="stock-item {% if sym == selected_base %}active{% endif %}" onclick="selectStock('{{ sym }}')">
                        <span class="name">{{ sym }}</span>
                        <span class="arrow">›</span>
                    </div>
                {% endfor %}
            </div>
        </div>

        <!-- CONTENT -->
        <div class="content">
            <!-- Stock Header -->
            <div class="stock-header">
                <div class="stock-name-section">
                    <h2>{{ selected_base }}</h2>
                    <div class="exchange">NSE • Equity • {{ default_symbol }}</div>
                </div>
                <div class="stock-price-section">
                    <div id="ltpDisplay" class="ltp-price green">0.00</div>
                    <div id="changeDisplay" class="price-change green">+0.00 (+0.00%)</div>
                </div>
            </div>

            <!-- Stats Row -->
            <div class="stats-row">
                <div class="stat-card">
                    <div class="stat-label">Open</div>
                    <div class="stat-value" id="openDisplay">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">High</div>
                    <div class="stat-value" id="highDisplay">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Low</div>
                    <div class="stat-value" id="lowDisplay">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Close</div>
                    <div class="stat-value" id="closeDisplay">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Volume</div>
                    <div class="stat-value" id="volDisplay">-</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Last Update</div>
                    <div class="stat-value" id="timeDisplay" style="font-size:12px;">--:--:--</div>
                </div>
            </div>

            <!-- Charts -->
            <div class="charts-grid">
                <div class="chart-card">
                    <div class="chart-card-title">📊 Price History (Intraday)</div>
                    <div class="chart-container">
                        <canvas id="stockChart"></canvas>
                    </div>
                </div>
                <div class="chart-card">
                    <div class="chart-card-title">📉 Market Depth (Buy vs Sell)</div>
                    <div class="chart-container">
                        <canvas id="depthChart"></canvas>
                    </div>
                </div>
            </div>

            <!-- Trading Panel -->
            <div class="trade-panel">
                <div class="trade-panel-header">⚡ Quick Order</div>
                <div class="trade-form">
                    <label>Symbol</label>
                    <input type="text" class="trade-input" id="symbolInput" value="{{ default_symbol }}" readonly>
                    <label>Qty</label>
                    <input type="number" class="trade-input" id="qty" value="1" min="1">
                    <label>Type</label>
                    <select class="trade-select" id="productType">
                        <option value="INTRADAY">Intraday (MIS)</option>
                        <option value="CNC">Delivery (CNC)</option>
                    </select>
                    <button class="btn-buy" onclick="placeOrder(1)">▲ Buy</button>
                    <button class="btn-sell" onclick="placeOrder(-1)">▼ Sell</button>
                </div>
                <div id="statusToast" class="status-toast"></div>
            </div>

            <div style="height: 50px;"></div>
        </div>
    </div>

    <!-- BOTTOM BAR -->
    <div class="bottom-bar">
        <span>Client: JFSHKMD0A8-200</span>
        <span class="sep"></span>
        <span>Exchange: NSE</span>
        <span class="sep"></span>
        <span id="bottomClock"></span>
        <span class="sep"></span>
        <span style="margin-left:auto;">Market Hours: 09:15 - 15:30 IST</span>
    </div>

    <script>
        // Clock
        function updateClock() {
            const now = new Date();
            const time = now.toLocaleTimeString('en-IN', { hour12: false });
            document.getElementById('bottomClock').textContent = time;
            document.getElementById('timeDisplay').textContent = time;
        }
        setInterval(updateClock, 1000);
        updateClock();

        // Charts
        const ctxPrice = document.getElementById('stockChart').getContext('2d');
        const ctxDepth = document.getElementById('depthChart').getContext('2d');

        let priceChart = new Chart(ctxPrice, {
            type: 'line',
            data: { 
                labels: [], 
                datasets: [{
                    label: 'Price',
                    data: [],
                    borderColor: '#00d4aa',
                    backgroundColor: 'rgba(0, 212, 170, 0.08)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.2,
                    pointRadius: 0,
                    pointHitRadius: 10
                }] 
            },
            options: { 
                responsive: true, 
                maintainAspectRatio: false, 
                plugins: { 
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(10, 14, 23, 0.95)',
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1,
                        titleColor: '#fff',
                        bodyColor: '#00d4aa',
                        padding: 12,
                        displayColors: false,
                        callbacks: {
                            label: function(ctx) { return '₹ ' + ctx.parsed.y.toFixed(2); }
                        }
                    }
                }, 
                scales: { 
                    y: { 
                        beginAtZero: false,
                        grid: { color: 'rgba(255,255,255,0.04)' },
                        ticks: { color: 'rgba(255,255,255,0.4)', font: { size: 11 } }
                    }, 
                    x: { 
                        grid: { display: false },
                        ticks: { maxTicksLimit: 6, color: 'rgba(255,255,255,0.3)', font: { size: 10 } }
                    } 
                },
                interaction: { intersect: false, mode: 'index' }
            }
        });

        let depthChart = new Chart(ctxDepth, {
            type: 'line',
            data: {
                datasets: [
                    { label: 'Buy Qty', data: [], borderColor: '#00d4aa', backgroundColor: 'rgba(0, 212, 170, 0.15)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
                    { label: 'Sell Qty', data: [], borderColor: '#ff4757', backgroundColor: 'rgba(255, 71, 87, 0.15)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: { 
                    legend: { 
                        position: 'bottom',
                        labels: { color: 'rgba(255,255,255,0.5)', font: { size: 11 }, boxWidth: 12, padding: 16 }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(10, 14, 23, 0.95)',
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1,
                        titleColor: '#fff',
                        bodyColor: 'rgba(255,255,255,0.7)',
                        padding: 12
                    }
                },
                scales: {
                    y: { 
                        beginAtZero: true,
                        grid: { color: 'rgba(255,255,255,0.04)' },
                        ticks: { color: 'rgba(255,255,255,0.4)', font: { size: 11 } }
                    },
                    x: { 
                        type: 'time', 
                        time: { unit: 'minute', displayFormats: { minute: 'HH:mm' } },
                        grid: { display: false },
                        ticks: { color: 'rgba(255,255,255,0.3)', font: { size: 10 }, maxTicksLimit: 6 }
                    }
                }
            }
        });

        let liveInterval, depthInterval, priceChartInterval;

        function selectStock(baseSym) { window.location.href = "/dashboard?symbol=" + baseSym; }

        function formatVolume(vol) {
            if (vol >= 10000000) return (vol / 10000000).toFixed(2) + ' Cr';
            if (vol >= 100000) return (vol / 100000).toFixed(2) + ' L';
            if (vol >= 1000) return (vol / 1000).toFixed(1) + ' K';
            return vol.toString();
        }

        function startLiveStreams() {
            const symbol = document.getElementById("symbolInput").value;
            
            if(liveInterval) clearInterval(liveInterval);
            if(depthInterval) clearInterval(depthInterval);
            if(priceChartInterval) clearInterval(priceChartInterval);

            priceChart.data.labels = []; priceChart.data.datasets[0].data = []; priceChart.update();
            depthChart.data.datasets[0].data = []; depthChart.data.datasets[1].data = []; depthChart.update();

            updatePrice(symbol);
            liveInterval = setInterval(() => updatePrice(symbol), 2000);
            updatePriceChart(symbol);
            priceChartInterval = setInterval(() => updatePriceChart(symbol), 10000);
            updateDepthChart(symbol);
            depthInterval = setInterval(() => updateDepthChart(symbol), 5000);
        }

        function updatePrice(symbol) {
            fetch("/get_quote?symbol=" + encodeURIComponent(symbol))
            .then(res => res.json())
            .then(data => {
                if(data.ltp) {
                    const ltpDiv = document.getElementById("ltpDisplay");
                    const changeDiv = document.getElementById("changeDisplay");
                    const ltp = data.ltp;
                    const ch = data.change || 0, chp = data.change_pct || 0;
                    
                    ltpDiv.innerText = '₹ ' + ltp.toFixed(2);
                    
                    if(ch >= 0) { 
                        ltpDiv.className = "ltp-price green"; 
                        changeDiv.className = "price-change green"; 
                        changeDiv.innerText = '+' + ch.toFixed(2) + ' (+' + chp.toFixed(2) + '%)';
                        priceChart.data.datasets[0].borderColor = '#00d4aa';
                        priceChart.data.datasets[0].backgroundColor = 'rgba(0, 212, 170, 0.08)';
                    } else { 
                        ltpDiv.className = "ltp-price red"; 
                        changeDiv.className = "price-change red"; 
                        changeDiv.innerText = ch.toFixed(2) + ' (' + chp.toFixed(2) + '%)';
                        priceChart.data.datasets[0].borderColor = '#ff4757';
                        priceChart.data.datasets[0].backgroundColor = 'rgba(255, 71, 87, 0.08)';
                    }
                    
                    document.getElementById("openDisplay").innerText = data.open ? '₹ ' + data.open.toFixed(2) : '-';
                    document.getElementById("highDisplay").innerText = data.high ? '₹ ' + data.high.toFixed(2) : '-';
                    document.getElementById("lowDisplay").innerText = data.low ? '₹ ' + data.low.toFixed(2) : '-';
                    document.getElementById("closeDisplay").innerText = data.close ? '₹ ' + data.close.toFixed(2) : '-';
                    document.getElementById("volDisplay").innerText = data.volume ? formatVolume(data.volume) : '-';
                }
            });
        }

        function updatePriceChart(symbol) {
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

        function updateDepthChart(symbol) {
            fetch("/get_depth_data?symbol=" + encodeURIComponent(symbol))
            .then(res => res.json())
            .then(rawData => {
                if (Array.isArray(rawData) && rawData.length > 0) {
                    depthChart.data.datasets[0].data = rawData.map(d => ({ x: d.time, y: d.buy_q }));
                    depthChart.data.datasets[1].data = rawData.map(d => ({ x: d.time, y: d.sell_q }));
                    depthChart.update('none');
                }
            });
        }

        function showStatus(message, type) {
            const el = document.getElementById('statusToast');
            el.className = 'status-toast ' + type;
            el.textContent = message;
            if (type !== 'pending') {
                setTimeout(() => { el.className = 'status-toast'; }, 8000);
            }
        }

        function placeOrder(side) {
            const symbol = document.getElementById("symbolInput").value;
            const qtyVal = document.getElementById("qty").value;
            const productType = document.getElementById("productType").value;
            const sideLabel = side === 1 ? 'BUY' : 'SELL';
            
            showStatus('⏳ Placing ' + sideLabel + ' order...', 'pending');
            
            fetch("/place_order", { 
                method: "POST", 
                headers: { "Content-Type": "application/json" }, 
                body: JSON.stringify({ symbol, qty: qtyVal, side, product_type: productType }) 
            })
            .then(res => res.json())
            .then(data => {
                if(data.id) { 
                    showStatus('✅ Order Placed Successfully! ID: ' + data.id, 'success'); 
                } else { 
                    showStatus('❌ Error: ' + (data.message || data.error || JSON.stringify(data)), 'error'); 
                }
            })
            .catch(err => { showStatus('❌ Network Error: ' + err, 'error'); });
        }

        window.onload = startLiveStreams;
    </script>
</body>
</html>"""

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 NSE EQUITY LIVE Trading Terminal")
    print("="*60)
    print(f"📍 Login Screen:  http://127.0.0.1:5000/login")
    print(f"📍 Dashboard:     http://127.0.0.1:5000/dashboard")
    print(f"🔑 Client ID:     {CLIENT_ID}")
    print(f"🔗 Callback:      {REDIRECT_URI}")
    print("="*60 + "\n")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
