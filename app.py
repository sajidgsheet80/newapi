from fyers_apiv3 import fyersModel
from flask import Flask, request, render_template_string, jsonify, redirect, url_for
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

# ---- Routes ----
@app.route("/")
def index():
    if fyers is None:
        return redirect(url_for('connect_page'))
    return redirect(url_for('nse_dashboard'))

@app.route("/connect")
def connect_page():
    return render_template_string(CONNECT_TEMPLATE)

@app.route("/login_fyers")
def login_fyers():
    sess = fyersModel.SessionModel(
        client_id=CLIENT_ID, 
        secret_key=SECRET_KEY, 
        redirect_uri=REDIRECT_URI, 
        response_type="code", 
        grant_type="authorization_code"
    )
    auth_url = sess.generate_authcode()
    webbrowser.open(auth_url, new=1)
    return "Opening Fyers login... <br><a href='/connect'>Go Back</a>"

@app.route("/callback")
def callback():
    global auth_code_stored
    auth_code = request.args.get("auth_code")
    if auth_code:
        auth_code_stored = auth_code
        if init_fyers(auth_code):
            return redirect(url_for('nse_dashboard'))
    return "❌ Failed to get auth code. <a href='/connect'>Try Again</a>"

@app.route("/nse")
def nse_dashboard():
    if fyers is None:
        return redirect(url_for('connect_page'))
    selected_base = request.args.get('symbol', 'RELIANCE')
    default_symbol = get_nse_symbol(selected_base)
    return render_template_string(NSE_TEMPLATE, symbols=NSE_STOCKS, selected_base=selected_base, default_symbol=default_symbol)

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
                "open": data.get("open_price", 0)
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
                result.append({"time": datetime.fromtimestamp(c[0]).strftime('%d-%b %H:%M'), "price": c[4]})
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

# ---- Templates ----
CONNECT_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>Connect Fyers</title>
    <style>
        body { font-family: Arial; background: linear-gradient(135deg, #667eea, #764ba2); display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .box { background: #fff; padding: 40px; border-radius: 10px; width: 450px; box-shadow: 0 10px 25px rgba(0,0,0,0.2); text-align: center; }
        h2 { color: #333; }
        .cred { background: #f5f5f5; padding: 15px; border-radius: 8px; margin: 20px 0; text-align: left; font-family: monospace; font-size: 13px; }
        .cred div { margin: 5px 0; }
        button { padding: 15px 40px; background: #667eea; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; }
        button:hover { background: #5a6fd6; }
    </style>
</head>
<body>
    <div class="box">
        <h2>🔗 Connect to Fyers</h2>
        <div class="cred">
            <div><strong>Client ID:</strong> JFSHKMD0A8-200</div>
            <div><strong>Redirect URI:</strong> http://127.0.0.1:5000/callback</div>
        </div>
        <p>Click below to login with your Fyers account</p>
        <br>
        <a href="/login_fyers"><button>🚀 Login with Fyers</button></a>
    </div>
</body>
</html>"""

NSE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>NSE Equity Live Trading</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #f4f4f9; margin: 0; }
        .header { background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%); color: white; padding: 15px 30px; display: flex; justify-content: space-between; align-items: center; }
        .container { display: flex; height: calc(100vh - 70px); }
        .sidebar { width: 250px; background: white; border-right: 1px solid #ddd; overflow-y: auto; }
        .main-content { flex: 1; padding: 20px; overflow-y: auto; }
        .stock-item { padding: 12px; cursor: pointer; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; }
        .stock-item:hover { background: #f0f0f0; }
        .stock-item.active { background: #1a73e8; color: white; font-weight: bold; }
        .price-box { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        .ltp { font-size: 36px; font-weight: bold; color: #333; }
        .change { font-size: 18px; font-weight: bold; margin-top: 5px; }
        .change.green { color: #4caf50; }
        .change.red { color: #f44336; }
        .ohlc { text-align: right; color: #666; font-size: 14px; }
        .live-badge { background: #4caf50; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; margin-left: 10px; }
        .chart-wrapper { display: flex; gap: 20px; margin-bottom: 20px; }
        .chart-box { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); flex: 1; position: relative; height: 300px; }
        .chart-title { position: absolute; top: 10px; left: 20px; font-weight: bold; color: #555; z-index: 10; background: rgba(255,255,255,0.8); padding: 2px 8px; border-radius: 4px; }
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
        <div><span class="live-badge">🔴 LIVE</span></div>
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
            <h2>{{ selected_base }} <span class="live-badge">LIVE</span></h2>

            <div class="price-box">
                <div>
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
        const ctxPrice = document.getElementById('stockChart').getContext('2d');
        const ctxDepth = document.getElementById('depthChart').getContext('2d');

        let priceChart = new Chart(ctxPrice, {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Price', data: [], borderColor: '#1a73e8', backgroundColor: 'rgba(26, 115, 232, 0.1)', borderWidth: 2, fill: true, tension: 0.1, pointRadius: 0 }] },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: false }, x: { ticks: { maxTicksLimit: 6 } } } }
        });

        let depthChart = new Chart(ctxDepth, {
            type: 'line',
            data: {
                datasets: [
                    { label: 'Buy Qty', data: [], borderColor: 'rgba(76, 175, 80, 1)', backgroundColor: 'rgba(76, 175, 80, 0.2)', fill: true, tension: 0.3, pointRadius: 0 },
                    { label: 'Sell Qty', data: [], borderColor: 'rgba(244, 67, 54, 1)', backgroundColor: 'rgba(244, 67, 54, 0.2)', fill: true, tension: 0.3, pointRadius: 0 }
                ]
            },
            options: {
                responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: 'index' },
                plugins: { legend: { position: 'bottom' } },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Quantity' } },
                    x: { type: 'time', time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } } }
                }
            }
        });

        let liveInterval, depthInterval, priceChartInterval;

        function selectStock(baseSym) { window.location.href = "/nse?symbol=" + baseSym; }

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
                    ltpDiv.innerText = data.ltp.toFixed(2);
                    const changeDiv = document.getElementById("changeDisplay");
                    const ch = data.change || 0, chp = data.change_pct || 0;
                    if(ch >= 0) { changeDiv.className = "change green"; changeDiv.innerText = "+" + ch.toFixed(2) + " (+" + chp.toFixed(2) + "%)"; ltpDiv.style.color = "#4caf50"; }
                    else { changeDiv.className = "change red"; changeDiv.innerText = ch.toFixed(2) + " (" + chp.toFixed(2) + "%)"; ltpDiv.style.color = "#f44336"; }
                    document.getElementById("openDisplay").innerText = data.open || '-';
                    document.getElementById("highDisplay").innerText = data.high || '-';
                    document.getElementById("lowDisplay").innerText = data.low || '-';
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

        function placeOrder(side) {
            const symbol = document.getElementById("symbolInput").value;
            const qtyVal = document.getElementById("qty").value;
            const productType = document.getElementById("productType").value;
            const statusDiv = document.getElementById("statusBar");
            statusDiv.style.display = "block"; statusDiv.style.background = "#fff3e0"; statusDiv.innerHTML = "⏳ Placing order...";
            fetch("/place_order", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, qty: qtyVal, side, product_type: productType }) })
            .then(res => res.json())
            .then(data => {
                if(data.id) { statusDiv.style.background = "#e8f5e9"; statusDiv.innerHTML = "✅ Order Placed! ID: " + data.id; }
                else { statusDiv.style.background = "#ffebee"; statusDiv.innerHTML = "❌ Error: " + (data.message || data.error || JSON.stringify(data)); }
            })
            .catch(err => { statusDiv.style.background = "#ffebee"; statusDiv.innerHTML = "❌ Failed: " + err; });
        }

        window.onload = startLiveStreams;
    </script>
</body>
</html>"""

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 NSE EQUITY LIVE Trading Terminal")
    print("="*60)
    print(f"📍 Server: http://127.0.0.1:5000")
    print(f"🔑 Client ID: {CLIENT_ID}")
    print(f"🔗 Callback: {REDIRECT_URI}")
    print("="*60 + "\n")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
