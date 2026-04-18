from fyers_apiv3 import fyersModel
from flask import Flask, request, render_template_string, jsonify, redirect, url_for
import webbrowser
import os
import json
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "sajid_secret_key_change_this"

# ---- Configuration & Storage ----
CONFIG_FILE = "api_config.json"

# Global Variables for Single User
fyers_instance = None
app_credentials = {
    "client_id": "",
    "secret_key": "",
    "redirect_uri": "http://127.0.0.1:5000/callback", # Default, will update based on port
    "access_token": ""
}

# Predefined list of NSE Equity Stocks
NSE_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", 
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", 
    "LT", "AXISBANK", "BAJFINANCE", "MARUTI", "ASIANPAINT"
]

# In-Memory Store for Depth History
DEPTH_HISTORY = {}

def load_config():
    """Load credentials from local file if they exist."""
    global app_credentials
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            try:
                data = json.load(f)
                app_credentials.update(data)
            except:
                pass

def save_config():
    """Save current credentials to local file."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(app_credentials, f, indent=4)

# Initialize config on startup
load_config()

# ---- Fyers Functions ----
def init_fyers_model():
    """Initialize the global Fyers model with the stored access token."""
    global fyers_instance
    try:
        if not app_credentials.get('access_token'):
            return False
        
        fyers_instance = fyersModel.FyersModel(
            client_id=app_credentials['client_id'], 
            token=app_credentials['access_token'], 
            is_async=False, 
            log_path=""
        )
        print("✅ Fyers Model Initialized Successfully.")
        return True
    except Exception as e:
        print(f"❌ Failed to init Fyers Model: {e}")
        return False

def place_order(symbol, qty, side, product_type):
    """Place order using global instance."""
    try:
        if fyers_instance is None: 
            return {"error": "Fyers not connected. Please login again."}
        
        data = {
            "symbol": symbol, 
            "qty": int(qty), 
            "type": 2, 
            "side": int(side), 
            "productType": product_type, 
            "limitPrice": 0, 
            "stopPrice": 0, 
            "validity": "DAY", 
            "disclosedQty": 0, 
            "offlineOrder": False, 
            "orderTag": "tag1", 
            "isSliceOrder": False
        }
        return fyers_instance.place_order(data=data)
    except Exception as e: 
        return {"error": str(e)}

# ---- Routes ----

@app.route("/")
def index():
    """If credentials exist, go to dashboard, else go to setup."""
    if app_credentials['client_id'] and app_credentials['secret_key'] and app_credentials['access_token']:
        # Check if instance needs init (e.g. server restart)
        if fyers_instance is None:
            init_fyers_model()
        return redirect(url_for('nse_dashboard'))
    return redirect(url_for('setup_credentials'))

@app.route("/setup_credentials", methods=["GET", "POST"])
def setup_credentials():
    """Page to input Client ID and Secret."""
    if request.method == "POST":
        cid = request.form.get("client_id")
        sec = request.form.get("secret_key")
        if cid and sec:
            app_credentials['client_id'] = cid
            app_credentials['secret_key'] = sec
            save_config()
            return redirect(url_for('fyers_login'))
    
    return render_template_string(CREDENTIALS_TEMPLATE, 
                                 client_id=app_credentials['client_id'], 
                                 secret_key=app_credentials['secret_key'])

@app.route("/fyers_login")
def fyers_login():
    """Generate the Fyers Auth URL."""
    if not app_credentials['client_id'] or not app_credentials['secret_key']:
        return redirect(url_for('setup_credentials'))
    
    # Update redirect URI based on current server port
    port = request.host.split(':')[-1] if ':' in request.host else '5000'
    # Handle proxy/real IP cases if necessary, but defaulting to localhost for local dev
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    app_credentials['redirect_uri'] = redirect_uri

    session = fyersModel.SessionModel(
        client_id=app_credentials['client_id'],
        secret_key=app_credentials['secret_key'],
        redirect_uri=app_credentials['redirect_uri'],
        response_type="code",
        grant_type="authorization_code",
        state="sample"
    )
    
    url = session.generate_authcode()
    return render_template_string(AUTH_REDIRECT_TEMPLATE, auth_url=url)

@app.route("/callback")
def callback():
    """Handle Fyers Callback."""
    auth_code = request.args.get("auth_code")
    if auth_code:
        try:
            session = fyersModel.SessionModel(
                client_id=app_credentials['client_id'],
                secret_key=app_credentials['secret_key'],
                redirect_uri=app_credentials['redirect_uri'],
                response_type="code",
                grant_type="authorization_code"
            )
            session.set_token(auth_code)
            token_response = session.generate_token()
            
            if "access_token" in token_response:
                app_credentials['access_token'] = token_response["access_token"]
                save_config()
                
                if init_fyers_model():
                    return redirect(url_for('nse_dashboard'))
            
            return "❌ Failed to generate access token. Response: " + str(token_response)
        except Exception as e:
            return f"❌ Error during callback: {e}"
    return "❌ No auth code found."

@app.route("/nse")
def nse_dashboard():
    """Main Trading Dashboard."""
    if fyers_instance is None:
        return redirect(url_for('setup_credentials'))
    
    selected_base = request.args.get('symbol', 'RELIANCE')
    default_symbol = get_nse_symbol(selected_base)
    
    return render_template_string(NSE_TEMPLATE, 
                                 symbols=NSE_STOCKS, 
                                 selected_base=selected_base, 
                                 default_symbol=default_symbol)

# ---- Data API Routes ----

@app.route("/get_quote")
def get_quote():
    if fyers_instance is None: return jsonify({"error": "Not connected"})
    symbol = request.args.get('symbol')
    if not symbol: return jsonify({"error": "No symbol"})

    try:
        response = fyers_instance.quotes({"symbols": symbol})
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

@app.route("/get_live_chart")
def get_live_chart():
    if fyers_instance is None: return jsonify({"error": "Not connected"})
    symbol = request.args.get('symbol')
    if not symbol: return jsonify({"error": "No symbol"})

    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
        
        data = {
            "symbol": symbol, "resolution": "1", "date_format": "1", 
            "range_from": start_date, "range_to": end_date, "cont_flag": "0"
        }
        response = fyers_instance.history(data=data)
        
        result = []
        if response.get('s') == 'ok' and 'candles' in response:
            for c in response['candles']:
                result.append({"time": datetime.fromtimestamp(c[0]).strftime('%d-%b %H:%M'), "price": c[4]})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/get_daily_chart")
def get_daily_chart():
    if fyers_instance is None: return jsonify({"error": "Not connected"})
    symbol = request.args.get('symbol')
    if not symbol: return jsonify({"error": "No symbol"})

    try:
        # Fetch last 1 year of daily data
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        
        data = {
            "symbol": symbol, "resolution": "D", "date_format": "1", 
            "range_from": start_date, "range_to": end_date, "cont_flag": "1"
        }
        response = fyers_instance.history(data=data)
        
        result = []
        if response.get('s') == 'ok' and 'candles' in response:
            for c in response['candles']:
                # Using timestamp directly for time scale
                result.append({"time": c[0], "price": c[4]})
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/get_depth_data")
def get_depth_data():
    if fyers_instance is None: return jsonify([]) # Return empty list to prevent chart crash
    symbol = request.args.get('symbol')
    if not symbol: return jsonify([])

    try:
        # Fetch Market Depth
        depth_response = fyers_instance.depth({"symbol": symbol, "depth": 5})
        
        if depth_response.get('s') != 'ok' or 'd' not in depth_response or not depth_response['d']:
            # If bad response, return existing history or empty
            return jsonify(DEPTH_HISTORY.get(symbol, []))

        depth_data = depth_response['d'][0]
        buy_qtys = depth_data.get('bq', []) 
        sell_qtys = depth_data.get('sq', [])
        
        # Calculate Totals
        total_buy_qty = sum(int(q) for q in buy_qtys if str(q).isdigit())
        total_sell_qty = sum(int(q) for q in sell_qtys if str(q).isdigit())
        
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        if symbol not in DEPTH_HISTORY:
            DEPTH_HISTORY[symbol] = []
            
        history = DEPTH_HISTORY[symbol]
        history.append({"time": current_time, "buy_q": total_buy_qty, "sell_q": total_sell_qty})
        
        # Keep history manageable
        if len(history) > 500:
            DEPTH_HISTORY[symbol] = history[-500:]
            
        return jsonify(DEPTH_HISTORY[symbol])
        
    except Exception as e:
        print(f"Depth Error: {e}")
        return jsonify([]) # Return empty list on error

@app.route("/place_nse_order", methods=["POST"])
def place_nse_order():
    data = request.json
    symbol = data.get('symbol')
    try: 
        qty, side = int(data.get('qty', 1)), int(data.get('side'))
    except: 
        return jsonify({"error": "Invalid numbers"})
    
    if not symbol or not side: 
        return jsonify({"error": "Missing data"})
    
    return jsonify(place_order(symbol, qty, side, data.get('product_type', 'INTRADAY')))

@app.route("/reset_connection")
def reset_connection():
    """Clear access token and force re-login."""
    global fyers_instance
    fyers_instance = None
    app_credentials['access_token'] = ""
    save_config()
    return redirect(url_for('setup_credentials'))

# ---- Helper ----
def get_nse_symbol(base_name):
    return f"NSE:{base_name}-EQ"

# ---- Templates ----

CREDENTIALS_TEMPLATE = """
<!DOCTYPE html><html><head><title>Setup</title>
<style>body{font-family:Arial;background:#f4f4f9;padding:20px;display:flex;justify-content:center;align-items:center;height:100vh}
.box{max-width:500px;background:#fff;padding:40px;border-radius:10px;box-shadow:0 4px 15px rgba(0,0,0,0.1)}
h2{text-align:center;color:#333}input{width:100%;padding:12px;margin:10px 0;border:1px solid #ddd;border-radius:5px;box-sizing:border-box}
button{width:100%;padding:12px;background:#1a73e8;color:#fff;border:none;border-radius:5px;cursor:pointer;font-size:16px;margin-top:10px}
button:hover{background:#1557b0}</style></head>
<body><div class="box"><h2>🔑 API Credentials</h2>
<form method="POST"><input name="client_id" placeholder="App ID (e.g. XX...)" value="{{client_id}}" required>
<input name="secret_key" placeholder="Secret Key" value="{{secret_key}}" required>
<button>Connect to Fyers</button></form></div></body></html>
"""

AUTH_REDIRECT_TEMPLATE = """
<!DOCTYPE html><html><head><title>Login</title><style>
body{font-family:Arial;background:#f4f4f9;text-align:center;padding-top:50px}
h2{color:#333} .btn{display:inline-block;padding:15px 30px;background:#28a745;color:#fff;text-decoration:none;border-radius:5px;font-size:18px;margin-top:20px}
.btn:hover{background:#218838}</style></head>
<body>
<h2>Step 2: Authorize App</h2>
<p>Please click the button below to open the Fyers login page.</p>
<a href="{{ auth_url }}" class="btn" target="_blank">Open Fyers Login</a>
<p style="margin-top:20px; font-size:12px; color:#666;">After logging in, you will be redirected to the callback page automatically.</p>
</body></html>
"""

NSE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>NSE Equity Live Terminal</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #f4f4f9; margin: 0; }
        .header { background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%); color: white; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; }
        .nav-link { padding: 8px 15px; background: #0d47a1; color: white; text-decoration: none; border-radius: 4px; margin-left: 10px; font-size: 14px;}
        
        .container { display: flex; height: auto; min-height: calc(100vh - 70px); flex-direction: column; }
        .top-row { display: flex; flex: 1; }
        .sidebar { width: 250px; background: white; border-right: 1px solid #ddd; overflow-y: auto; flex-shrink: 0; min-height: 100vh; }
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
        .chart-box { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); position: relative; }
        
        /* Specific sizing for charts */
        .chart-sm { flex: 1; height: 300px; }
        .chart-lg { width: 100%; height: 350px; margin-bottom: 20px; }

        .chart-title { position: absolute; top: 10px; left: 20px; font-weight: bold; color: #555; z-index: 10; background: rgba(255,255,255,0.8); padding: 2px 8px; border-radius: 4px;}
        
        .trade-panel { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: flex; align-items: center; gap: 15px; flex-wrap: wrap; }
        
        input, select { padding: 8px; border: 1px solid #ccc; border-radius: 4px; }
        input[type="number"] { width: 80px; }
        input[type="text"] { width: 200px; font-weight: bold; }
        .btn { padding: 10px 20px; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .btn-buy { background-color: #4caf50; }
        .btn-sell { background-color: #f44336; }
        .btn:hover { opacity: 0.9; }
        
        .status-bar { margin-top: 10px; padding: 10px; background: #e8f5e9; border-radius: 4px; display: none; }
    </style>
</head>
<body>
    <div class="header">
        <h1>📈 NSE Equity Terminal</h1>
        <div>
            <a href="/reset_connection" class="nav-link">🔄 Reset Connection</a>
        </div>
    </div>

    <div class="container">
        <div class="top-row">
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
                
                <!-- Daily Chart (Full Width) -->
                <div class="chart-box chart-lg">
                    <div class="chart-title">Daily Trend (1 Year)</div>
                    <canvas id="dailyChart"></canvas>
                </div>

                <div class="chart-wrapper">
                    <div class="chart-box chart-sm">
                        <div class="chart-title">Intraday Price (1 Min)</div>
                        <canvas id="stockChart"></canvas>
                    </div>
                    <div class="chart-box chart-sm">
                        <div class="chart-title">Market Depth (Buy vs Sell Qty)</div>
                        <canvas id="depthChart"></canvas>
                    </div>
                </div>

                <div class="trade-panel">
                    <label>Symbol:</label>
                    <input type="text" id="symbolInput" value="{{ default_symbol }}">
                    
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
    </div>

    <script>
        // --- Chart Setup ---
        const ctxPrice = document.getElementById('stockChart').getContext('2d');
        const ctxDepth = document.getElementById('depthChart').getContext('2d');
        const ctxDaily = document.getElementById('dailyChart').getContext('2d');

        // 1. Intraday Price Chart (Line)
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

        // 2. Daily Chart (Line)
        let dailyChart = new Chart(ctxDaily, {
            type: 'line',
            data: {
                datasets: [{
                    label: 'Daily Close',
                    data: [], // Format: {x: timestamp, y: price}
                    borderColor: '#673ab7',
                    backgroundColor: 'rgba(103, 58, 183, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: true,
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: false },
                    x: {
                        type: 'time',
                        time: { unit: 'month', displayFormats: { month: 'MMM yyyy' } },
                        ticks: { maxTicksLimit: 12 }
                    }
                }
            }
        });

        // 3. Depth Chart (Time Series)
        let depthChart = new Chart(ctxDepth, {
            type: 'line',
            data: {
                datasets: [
                    { label: 'Total Buy Qty', data: [], borderColor: 'rgba(76, 175, 80, 1)', backgroundColor: 'rgba(76, 175, 80, 0.2)', fill: true, tension: 0.3, pointRadius: 0 },
                    { label: 'Total Sell Qty', data: [], borderColor: 'rgba(244, 67, 54, 1)', backgroundColor: 'rgba(244, 67, 54, 0.2)', fill: true, tension: 0.3, pointRadius: 0 }
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
                        time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
                        min: getMarketStart(),
                        max: getMarketEnd(),
                        title: { display: true, text: 'Time (Market Hours)' }
                    }
                }
            }
        });

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
            
            dailyChart.data.datasets[0].data = [];
            dailyChart.update();
            
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
            depthInterval = setInterval(() => updateDepthChart(symbol), 5000);

            updateDailyChart(symbol);
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

        function updateDailyChart(symbol){
            fetch("/get_daily_chart?symbol=" + encodeURIComponent(symbol))
            .then(res => res.json())
            .then(data => {
                if (Array.isArray(data) && data.length > 0) {
                    // Map timestamp directly to 'x' for time scale
                    const chartData = data.map(d => ({ x: d.time, y: d.price }));
                    dailyChart.data.datasets[0].data = chartData;
                    dailyChart.update('none');
                }
            });
        }

        function updateDepthChart(symbol){
            fetch("/get_depth_data?symbol=" + encodeURIComponent(symbol))
            .then(res => res.json())
            .then(rawData => {
                if (Array.isArray(rawData) && rawData.length > 0) {
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
    print("🚀 NSE EQUITY LIVE Trading Bot (Single User)")
    print("="*60)
    print(f"📍 Server: http://127.0.0.1:{port}")
    print("📈 Segment: NSE Equity (Cash)")
    print("="*60 + "\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)