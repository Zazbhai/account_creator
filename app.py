from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
from datetime import datetime
import json
import caller

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key-change-this-in-production")

# Simple file-based user storage (replace with database.py if available)
USERS_FILE = Path("users.json")
if not USERS_FILE.exists():
    with open(USERS_FILE, 'w') as f:
        json.dump({"users": []}, f)

def load_users():
    try:
        with open(USERS_FILE, 'r') as f:
            data = json.load(f)
            return data.get("users", [])
    except:
        return []

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump({"users": users}, f, indent=2)

def get_user_by_username(username):
    users = load_users()
    for user in users:
        if user.get("username") == username:
            return user
    return None

def create_user(username, password_hash, role="user", expiry_days=None):
    users = load_users()
    user_id = len(users) + 1
    expiry_date = None
    if expiry_days:
        from datetime import date, timedelta
        expiry_date = (date.today() + timedelta(days=expiry_days)).isoformat()
    users.append({
        "id": user_id,
        "username": username,
        "password_hash": password_hash,
        "role": role,
        "expiry_date": expiry_date,
        "created_at": datetime.now().isoformat()
    })
    save_users(users)
    return user_id

# Initialize default admin user if no users exist
if not load_users():
    admin_hash = generate_password_hash("admin")
    create_user("admin", admin_hash, role="admin", expiry_days=365)

# Cache for API settings
_api_settings_cache = None
_api_settings_cache_time = None
_api_settings_cache_lock = threading.Lock()
CACHE_TTL = 300

# Shared HTML template with navigation
BASE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - Account Creator</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #2d545e 0%, #12343b 100%);
            min-height: 100vh;
            padding: 20px;
            padding-bottom: 100px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            animation: fadeInUp 0.5s ease-out;
        }
        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .page-loader {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(135deg, #2d545e 0%, #12343b 100%);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 9999;
            transition: opacity 0.3s ease-out;
        }
        .page-loader.hidden {
            opacity: 0;
            pointer-events: none;
        }
        .page-loader .loader-spinner {
            width: 50px;
            height: 50px;
            border: 4px solid rgba(225, 179, 130, 0.3);
            border-radius: 50%;
            border-top-color: #e1b382;
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            flex-wrap: wrap;
            gap: 10px;
        }
        h1 {
            color: #333;
            font-size: 2em;
        }
        .nav-links {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .nav-btn, .logout-btn {
            padding: 8px 16px;
            background: #e1b382;
            color: #12343b;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            text-decoration: none;
            display: inline-block;
            transition: background 0.3s;
            font-weight: 600;
        }
        .nav-btn:hover, .logout-btn:hover {
            background: #c89666;
        }
        .logout-btn {
            background: #c89666;
            color: white;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: 600;
        }
        input, select, textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
            font-family: inherit;
        }
        input:focus, select:focus, textarea:focus {
            outline: none;
            border-color: #e1b382;
        }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #2d545e 0%, #12343b 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(45, 84, 94, 0.4);
        }
        button:disabled {
            opacity: 0.7;
            cursor: not-allowed;
        }
        #start-button.running {
            background: linear-gradient(135deg, #c89666 0%, #a67a4d 100%);
        }
        .info-pill {
            display: inline-block;
            background: #e1b382;
            color: #12343b;
            padding: 8px 16px;
            border-radius: 20px;
            margin: 5px;
            font-size: 14px;
            font-weight: 600;
        }
        .balance-skeleton {
            display: inline-block;
            background: #e0e0e0;
            border-radius: 20px;
            padding: 8px 16px;
            margin: 5px;
            min-width: 120px;
            height: 36px;
            position: relative;
            overflow: hidden;
        }
        .skeleton-bar {
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.6), transparent);
            animation: shimmer 1.5s infinite;
        }
        @keyframes shimmer {
            0% { left: -100%; }
            100% { left: 100%; }
        }
        .error {
            background: #ffebee;
            color: #c62828;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #c62828;
        }
        .success {
            background: #e8f5e9;
            color: #2e7d32;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #2e7d32;
        }
        .log-container {
            margin-top: 30px;
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 20px;
            border-radius: 8px;
            max-height: 400px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            line-height: 1.6;
        }
        .log-line {
            margin-bottom: 5px;
            word-wrap: break-word;
            animation: fadeIn 0.3s ease-in;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(-5px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .spinner {
            display: inline-block;
            width: 14px;
            height: 14px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 0.8s linear infinite;
            margin-right: 8px;
            vertical-align: middle;
        }
        .popup-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 10000;
        }
        .popup {
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            max-width: 400px;
            width: 90%;
            text-align: center;
        }
        .popup button {
            width: auto;
            padding: 10px 30px;
            margin-top: 15px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e0e0e0;
        }
        th {
            background: #f5f5f5;
            font-weight: 600;
        }
        .bottom-nav {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: rgba(255, 255, 255, 0.98);
            padding: 10px;
            display: flex;
            justify-content: space-around;
            box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
            z-index: 1000;
        }
        .bottom-nav .link-btn {
            padding: 10px 15px;
            background: transparent;
            color: #2d545e;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            text-decoration: none;
            transition: background 0.3s;
            font-weight: 600;
        }
        .bottom-nav .link-btn:hover {
            background: #f0f0f0;
        }
        .bottom-nav .link-btn.active {
            background: #e1b382;
            color: #12343b;
        }
        @media (min-width: 769px) {
            .bottom-nav { display: none; }
        }
    </style>
    <script>
        let loaderElement = null;
        let hideTimer = null;
        let loaderShown = false;
        
        function showLoader() {
            if (!document.body) return;
            if (loaderShown && loaderElement && document.body.contains(loaderElement)) return;
            if (hideTimer) {
                clearTimeout(hideTimer);
                hideTimer = null;
            }
            const oldLoader = document.getElementById('page-loader');
            if (oldLoader && oldLoader.parentNode) {
                try { oldLoader.remove(); } catch(e) {}
            }
            loaderElement = document.createElement('div');
            loaderElement.id = 'page-loader';
            loaderElement.className = 'page-loader';
            loaderElement.innerHTML = '<div class="loader-spinner"></div>';
            document.body.appendChild(loaderElement);
            loaderShown = true;
            hideTimer = setTimeout(function() {
                forceHideLoader();
            }, 5000);
        }
        
        function hideLoader() {
            if (hideTimer) {
                clearTimeout(hideTimer);
                hideTimer = null;
            }
            const elapsed = Date.now() - (loaderElement?.startTime || Date.now());
            const remaining = elapsed < 700 ? 700 - elapsed : 0;
            setTimeout(function() {
                loaderShown = false;
                if (loaderElement && document.body.contains(loaderElement)) {
                    loaderElement.classList.add('hidden');
                    setTimeout(function() {
                        try {
                            if (loaderElement && loaderElement.parentNode) {
                                loaderElement.remove();
                            }
                        } catch(e) {}
                        loaderElement = null;
                    }, 300);
                }
            }, remaining);
        }
        
        function forceHideLoader() {
            if (hideTimer) {
                clearTimeout(hideTimer);
                hideTimer = null;
            }
            loaderShown = false;
            const loaders = document.querySelectorAll('#page-loader, .page-loader');
            loaders.forEach(function(loader) {
                try {
                    loader.classList.add('hidden');
                    if (loader.parentNode) {
                        loader.remove();
                    }
                } catch(e) {}
            });
            loaderElement = null;
        }
        
        if (document.readyState === 'loading') {
            showLoader();
        } else {
            showLoader();
        }
        
        window.addEventListener('load', function() {
            setTimeout(function() {
                hideLoader();
            }, 800);
        });
        
        window.addEventListener('beforeunload', function() {
            forceHideLoader();
        });
        
        // Real-time log updates
        let lastLogPosition = {{ user_logs|length if user_logs is defined else 0 }};
        let logUpdateInterval = null;
        let popupShown = false;
        let processedErrorLines = new Set();
        
        function showNoNumbersPopup() {
            if (document.querySelector('.popup-overlay') || popupShown) return;
            popupShown = true;
            const overlay = document.createElement('div');
            overlay.className = 'popup-overlay';
            overlay.innerHTML = `
                <div class="popup">
                    <h3>⚠️ No Numbers Available</h3>
                    <p>No numbers are available right now. Please try again later.</p>
                    <button onclick="this.closest('.popup-overlay').remove()">OK</button>
                </div>
            `;
            document.body.appendChild(overlay);
            setTimeout(() => {
                if (overlay.parentNode) overlay.remove();
            }, 10000);
        }
        
        function appendLogLine(line) {
            const logContainer = document.getElementById('log-container');
            if (!logContainer) return;
            const text = (line || '').trim();
            if (!text) return;
            const existingLines = logContainer.querySelectorAll('.log-line');
            if (existingLines.length && existingLines[existingLines.length - 1].textContent.trim() === text) {
                return;
            }
            const logLine = document.createElement('div');
            logLine.className = 'log-line';
            logLine.textContent = text;
            logContainer.appendChild(logLine);
            logContainer.scrollTop = logContainer.scrollHeight;
            if (text.includes('[ERROR] NO_NUMBERS') || text.includes('NO_NUMBERS')) {
                if (!processedErrorLines.has(text)) {
                    processedErrorLines.add(text);
                    showNoNumbersPopup();
                }
            }
        }
        
        function updateLogs() {
            const logContainer = document.getElementById('log-container');
            if (!logContainer) return;
            fetch(`/api/logs?last_position=${lastLogPosition}`)
                .then(response => response.json())
                .then(data => {
                    if (data.logs && data.logs.length > 0) {
                        data.logs.forEach((line) => {
                            if (!line || !line.trim()) return;
                            const existingLines = logContainer.querySelectorAll('.log-line');
                            let isDuplicate = false;
                            for (let existingLine of existingLines) {
                                if (existingLine.textContent.trim() === line.trim()) {
                                    isDuplicate = true;
                                    break;
                                }
                            }
                            if (isDuplicate) return;
                            const logLine = document.createElement('div');
                            logLine.className = 'log-line';
                            logLine.textContent = line.trim();
                            logContainer.appendChild(logLine);
                            logContainer.scrollTop = logContainer.scrollHeight;
                            if (line.includes('[ERROR] NO_NUMBERS') || line.includes('NO_NUMBERS')) {
                                if (!processedErrorLines.has(line.trim())) {
                                    processedErrorLines.add(line.trim());
                                    showNoNumbersPopup();
                                }
                            }
                        });
                        lastLogPosition = data.position || lastLogPosition;
                    }
                    const startButton = document.getElementById('start-button');
                    if (startButton) {
                        checkWorkerStatus();
                    }
                })
                .catch(err => {
                    console.error('Error fetching logs:', err);
                });
        }
        
        function applyBalance(data) {
            const balanceInfo = document.getElementById('balance-info');
            const totalInput = document.getElementById('total_accounts');
            if (!balanceInfo) return;
            balanceInfo.style.display = 'block';
            const balancePill = document.getElementById('balance-pill');
            const pricePill = document.getElementById('price-pill');
            const capacityPill = document.getElementById('capacity-pill');
            if (data.error) {
                balancePill.textContent = `Balance: ${data.error}`;
                pricePill.textContent = 'Price: N/A';
                capacityPill.textContent = 'Can create: 0 account(s)';
                if (totalInput) totalInput.removeAttribute('max');
            } else {
                const bal = data.balance !== undefined && data.balance !== null ? Number(data.balance) : null;
                const price = data.price !== undefined && data.price !== null ? Number(data.price) : null;
                const cap = data.capacity !== undefined && data.capacity !== null ? Number(data.capacity) : 0;
                balancePill.textContent = bal !== null ? `Balance: ₹${bal.toFixed(2)}` : 'Balance: N/A';
                pricePill.textContent = price !== null ? `Price: ₹${price.toFixed(2)}` : 'Price: N/A';
                capacityPill.textContent = `Can create: ${cap} account(s)`;
                if (totalInput) {
                    totalInput.setAttribute('max', cap);
                    if (Number(totalInput.value) > cap) {
                        totalInput.value = cap;
                    }
                }
            }
            balancePill.classList.remove('balance-skeleton');
            pricePill.classList.remove('balance-skeleton');
            capacityPill.classList.remove('balance-skeleton');
            const skeletons = balanceInfo.querySelectorAll('.skeleton-bar');
            skeletons.forEach(s => s.remove());
        }
        
        function checkWorkerStatus() {
            const startButton = document.getElementById('start-button');
            if (!startButton) return;
            fetch('/api/worker-status')
                .then(response => response.json())
                .then(data => {
                    const buttonText = document.getElementById('button-text');
                    const buttonLoader = document.getElementById('button-loader');
                    if (data.running) {
                        if (!startButton.disabled) {
                            startButton.disabled = true;
                            startButton.classList.add('running');
                            if (buttonText) {
                                buttonText.style.display = 'none';
                                buttonText.style.visibility = 'hidden';
                            }
                            if (buttonLoader) {
                                buttonLoader.style.display = 'inline';
                                buttonLoader.style.visibility = 'visible';
                            }
                        }
                    } else {
                        if (startButton.disabled) {
                            startButton.disabled = false;
                            startButton.classList.remove('running');
                            if (buttonText) {
                                buttonText.style.display = 'inline';
                                buttonText.style.visibility = 'visible';
                                buttonText.textContent = 'Start Creating Accounts';
                            }
                            if (buttonLoader) {
                                buttonLoader.style.display = 'none';
                                buttonLoader.style.visibility = 'hidden';
                            }
                        }
                    }
                })
                .catch(err => {
                    console.error('Error checking worker status:', err);
                });
        }
        
        function loadBalanceInfo() {
            if (window._evtStream) return;
            fetch('/api/balance?ts=' + Date.now())
                .then(response => response.json())
                .then(data => {
                    applyBalance(data);
                })
                .catch(err => {
                    console.error('Error loading balance:', err);
                });
        }
        
        function initializePage() {
            const runForm = document.getElementById('run-form');
            const startButton = document.getElementById('start-button');
            const buttonText = document.getElementById('button-text');
            const buttonLoader = document.getElementById('button-loader');
            
            if (runForm) {
                runForm.addEventListener('submit', function(e) {
                    popupShown = false;
                    processedErrorLines.clear();
                    const logContainer = document.getElementById('log-container');
                    if (logContainer) {
                        logContainer.innerHTML = '<div class="log-line">Starting account creation...</div>';
                        lastLogPosition = 0;
                    }
                    if (startButton) {
                        startButton.disabled = true;
                        startButton.classList.add('running');
                        if (buttonText) {
                            buttonText.style.display = 'none';
                            buttonText.style.visibility = 'hidden';
                        }
                        if (buttonLoader) {
                            buttonLoader.style.display = 'inline';
                            buttonLoader.style.visibility = 'visible';
                        }
                    }
                });
            }
            
            const logContainer = document.getElementById('log-container');
            if (logContainer) {
                logContainer.scrollTop = logContainer.scrollHeight;
                const existingLines = logContainer.querySelectorAll('.log-line');
                lastLogPosition = existingLines.length;
            }
            
            if (!!window.EventSource) {
                const evt = new EventSource('/stream');
                evt.onmessage = function(ev) {
                    try {
                        const payload = JSON.parse(ev.data);
                        if (payload.type === 'log') {
                            appendLogLine(payload.line);
                        } else if (payload.type === 'balance') {
                            applyBalance(payload);
                        }
                    } catch (err) {
                        console.error('SSE parse error', err);
                    }
                };
                evt.onerror = function(err) {
                    console.error('SSE error', err);
                };
                window._evtStream = evt;
            }
            
            if (startButton) {
                checkWorkerStatus();
                setInterval(function() {
                    checkWorkerStatus();
                }, 2000);
            }
            
            loadBalanceInfo();
            setInterval(function() {
                if (!window._evtStream) loadBalanceInfo();
            }, 10000);
            
            if (logContainer) {
                setInterval(updateLogs, 300);
            }
        }
        
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initializePage);
        } else {
            initializePage();
        }
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{{ title }}</h1>
            <div class="nav-links">
                {% if not is_admin %}
                <a href="{{ url_for('launcher') }}" class="nav-btn">Launcher</a>
                <a href="{{ url_for('imap_settings') }}" class="nav-btn">IMAP</a>
                <a href="{{ url_for('reports') }}" class="nav-btn">Reports</a>
                <a href="{{ url_for('logs') }}" class="nav-btn">Logs</a>
                {% endif %}
                {% if is_admin %}
                <a href="{{ url_for('admin_dashboard') }}" class="nav-btn">Dashboard</a>
                <a href="{{ url_for('admin_users') }}" class="nav-btn">Users</a>
                {% endif %}
                <form method="POST" action="{{ url_for('logout') }}" style="margin:0; display:inline;">
                    <button type="submit" class="logout-btn">Logout</button>
                </form>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="{{ 'error' if category == 'error' else 'success' }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        {{ content|safe }}
    </div>
    
    <div class="bottom-nav">
        {% if not is_admin %}
        <a href="{{ url_for('launcher') }}" class="link-btn {% if view == 'launcher' %}active{% endif %}">Launcher</a>
        <a href="{{ url_for('imap_settings') }}" class="link-btn {% if view == 'imap' %}active{% endif %}">IMAP</a>
        <a href="{{ url_for('reports') }}" class="link-btn {% if view == 'reports' %}active{% endif %}">Reports</a>
        <a href="{{ url_for('logs') }}" class="link-btn {% if view == 'logs' %}active{% endif %}">Logs</a>
        {% endif %}
        {% if is_admin %}
        <a href="{{ url_for('admin_dashboard') }}" class="link-btn {% if view == 'dashboard' %}active{% endif %}">Dashboard</a>
        <a href="{{ url_for('admin_users') }}" class="link-btn {% if view == 'users' %}active{% endif %}">Users</a>
        {% endif %}
    </div>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Account Creator</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #2d545e 0%, #12343b 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 100%;
            max-width: 400px;
        }
        h1 {
            text-align: center;
            color: #333;
            margin-bottom: 30px;
            font-size: 2em;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: 600;
        }
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
        }
        input:focus {
            outline: none;
            border-color: #e1b382;
        }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #2d545e 0%, #12343b 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
        }
        .error {
            background: #ffebee;
            color: #c62828;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #c62828;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>Account Creator</h1>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form method="POST" action="/login">
            <div class="form-group">
                <label for="username">Username:</label>
                <input type="text" id="username" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label for="password">Password:</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit">Login</button>
        </form>
    </div>
</body>
</html>
"""

# In-memory log buffer for REAL-TIME log updates
log_buffer = {}
log_lock = threading.Lock()
MAX_LOG_BUFFER_SIZE = 10000

# SSE subscribers per user
from queue import Queue
event_subscribers = {}
event_lock = threading.Lock()

def push_event(user_id, payload: dict):
    """Push an SSE event to all subscribers for a user."""
    with event_lock:
        subs = list(event_subscribers.get(user_id, []))
    for q in subs:
        try:
            q.put(payload, block=False)
        except Exception:
            pass

def add_log(user_id, message):
    """Add log message to in-memory buffer (REAL-TIME, thread-safe)."""
    with log_lock:
        if user_id not in log_buffer:
            log_buffer[user_id] = []
        log_buffer[user_id].append(message)
        if len(log_buffer[user_id]) > MAX_LOG_BUFFER_SIZE:
            log_buffer[user_id] = log_buffer[user_id][-MAX_LOG_BUFFER_SIZE:]
        print(f"[User {user_id}] {message}")
    push_event(user_id, {"type": "log", "line": message})

def clear_user_logs(user_id):
    """Clear logs for a user."""
    with log_lock:
        log_buffer[user_id] = []

def get_user_logs(user_id, limit=100):
    """Get logs for a user."""
    with log_lock:
        logs = log_buffer.get(user_id, [])
        return logs[-limit:] if limit else logs

# Worker process tracking
user_processes = {}
user_processes_lock = threading.Lock()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = get_user_by_username(session.get('username'))
        if not user or user.get('role') != 'admin':
            flash('Admin access required', 'error')
            return redirect(url_for('launcher'))
        return f(*args, **kwargs)
    return decorated_function

def is_admin():
    if 'username' not in session:
        return False
    user = get_user_by_username(session.get('username'))
    return user and user.get('role') == 'admin'

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            return render_template_string(LOGIN_HTML, error="Please enter both username and password")
        user = get_user_by_username(username)
        if user and check_password_hash(user.get("password_hash"), password):
            session['user_id'] = user.get("id")
            session['username'] = username
            return redirect(url_for('launcher'))
        return render_template_string(LOGIN_HTML, error="Invalid username or password")
    error = request.args.get('error')
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

@app.route("/check-expiry")
@login_required
def check_expiry():
    user = get_user_by_username(session.get('username'))
    if user and user.get('expiry_date'):
        from datetime import date
        expiry = date.fromisoformat(user['expiry_date'])
        if expiry < date.today():
            return jsonify({"valid": False, "error": "Your subscription has expired"})
    return jsonify({"valid": True})

def compute_balance_and_capacity(user_id, include_price=False):
    """Compute balance and capacity."""
    try:
        balance_text = caller.get_balance()
        balance = caller.parse_balance(balance_text)
        if balance is None:
            return None, None, None if include_price else None, "Failed to parse balance"
        price_text = caller.get_price_for_service()
        if not price_text:
            api_settings = {"default_price": 6.99}
            price = float(api_settings.get('default_price', 6.99))
        else:
            try:
                price = float(price_text)
            except ValueError:
                price = 6.99
        capacity = int(balance / price) if price > 0 else 0
        if include_price:
            return balance, capacity, price, None
        return balance, capacity, None
    except Exception as e:
        return None, None, None if include_price else None, str(e)

@app.route("/")
@login_required
def launcher():
    """Launcher page for users."""
    user_id = session.get('user_id')
    user_logs = get_user_logs(user_id, limit=100)
    
    user = get_user_by_username(session.get('username'))
    from datetime import date, datetime, timedelta
    today = date.today()
    expiry_date = None
    expiry_status = "Active"
    days_left = 0
    if user and user.get('expiry_date'):
        expiry_date = date.fromisoformat(user['expiry_date'])
        if expiry_date < today:
            expiry_status = "Expired"
        else:
            days_left = (expiry_date - today).days
            expiry_status = f"Active ({days_left} days left)"
    
    balance, capacity, price, error_msg = None, None, None, None
    try:
        balance, capacity, price, error_msg = compute_balance_and_capacity(user_id, include_price=True)
    except Exception as e:
        error_msg = str(e)
    
    content_template = """
    <h2>Account Launcher</h2>
    {% if error_msg %}
    <div class="error">Error: {{ error_msg }}</div>
    {% endif %}
    <div style="margin: 20px 0;">
        <span class="info-pill" style="{% if expiry_status == 'Expired' %}background: #f5e6d3; color: #c89666;{% else %}background: #e1b382; color: #12343b;{% endif %}">
            Account Status: {{ expiry_status }}
        </span>
        {% if expiry_date %}
        <span class="info-pill">Expiry Date: {{ expiry_date.strftime('%Y-%m-%d') if expiry_date else 'Never' }}</span>
        {% endif %}
    </div>
    <div style="margin: 20px 0;" id="balance-info">
        <span class="info-pill balance-skeleton" id="balance-pill">
            <span class="skeleton-bar"></span>
            Loading balance...
        </span>
        <span class="info-pill balance-skeleton" id="price-pill">
            <span class="skeleton-bar"></span>
            Loading price...
        </span>
        <span class="info-pill balance-skeleton" id="capacity-pill">
            <span class="skeleton-bar"></span>
            Loading capacity...
        </span>
    </div>
    
    <form method="POST" action="/run" id="run-form">
        <div class="form-group">
            <label for="total_accounts">Total Accounts to Create:</label>
            <input type="number" id="total_accounts" name="total_accounts" min="1" required value="10">
        </div>
        <div class="form-group">
            <label for="max_parallel">Maximum Parallel Windows:</label>
            <input type="number" id="max_parallel" name="max_parallel" min="1" required value="4">
        </div>
        <button type="submit" id="start-button">
            <span id="button-text">Start Creating Accounts</span>
            <span id="button-loader" style="display: none;">
                <span class="spinner"></span> Running...
            </span>
        </button>
        <button type="button" id="stop-button" style="background: #c62828; margin-top: 10px; display: none;" onclick="stopWorkers()">
            Stop All Workers
        </button>
    </form>
    
    <div class="log-container" id="log-container">
        {% if user_logs %}
        {% for line in user_logs %}
        <div class="log-line">{{ line|safe }}</div>
        {% endfor %}
        {% else %}
        <div class="log-line">No logs yet. Start creating accounts to see logs here.</div>
        {% endif %}
    </div>
    <script>
    function stopWorkers() {
        fetch('/api/stop', {method: 'POST'})
            .then(() => {
                alert('Stop requested. Workers will terminate shortly.');
            })
            .catch(err => {
                console.error('Error stopping workers:', err);
            });
    }
    </script>
    """
    
    content = render_template_string(
        content_template,
        error_msg=error_msg,
        user_logs=user_logs,
        expiry_date=expiry_date,
        expiry_status=expiry_status
    )
    
    return render_template_string(
        BASE_HTML,
        title="Launcher",
        view="launcher",
        is_admin=is_admin(),
        content=content
    )

@app.route("/imap", methods=["GET", "POST"])
@login_required
def imap_settings():
    """IMAP settings page."""
    import imap as imap_module
    if request.method == "POST":
        host = request.form.get("host", "").strip()
        port = request.form.get("port", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        mailbox = request.form.get("mailbox", "").strip()
        if host and port and email and password and mailbox:
            try:
                config = {
                    "host": host,
                    "port": int(port),
                    "email": email,
                    "password": password,
                    "mailbox": mailbox
                }
                import json
                with open("imap_config.json", "w") as f:
                    json.dump(config, f, indent=4)
                flash('IMAP settings saved successfully', 'success')
            except Exception as e:
                flash(f'Error saving settings: {str(e)}', 'error')
        else:
            flash('Please fill all fields', 'error')
        return redirect(url_for('imap_settings'))
    
    try:
        import json
        with open("imap_config.json", "r") as f:
            config = json.load(f)
    except:
        config = {}
    
    content_template = """
    <h2>IMAP Settings</h2>
    <form method="POST">
        <div class="form-group">
            <label for="host">IMAP Host:</label>
            <input type="text" id="host" name="host" value="{{ config.get('host', '') }}" required>
        </div>
        <div class="form-group">
            <label for="port">Port:</label>
            <input type="number" id="port" name="port" value="{{ config.get('port', '993') }}" required>
        </div>
        <div class="form-group">
            <label for="email">Email:</label>
            <input type="email" id="email" name="email" value="{{ config.get('email', '') }}" required>
        </div>
        <div class="form-group">
            <label for="password">Password:</label>
            <input type="password" id="password" name="password" value="{{ config.get('password', '') }}" required>
        </div>
        <div class="form-group">
            <label for="mailbox">Mailbox:</label>
            <input type="text" id="mailbox" name="mailbox" value="{{ config.get('mailbox', 'INBOX') }}" required>
        </div>
        <button type="submit">Save Settings</button>
    </form>
    """
    
    content = render_template_string(content_template, config=config)
    return render_template_string(
        BASE_HTML,
        title="IMAP Settings",
        view="imap",
        is_admin=is_admin(),
        content=content
    )

@app.route("/reports")
@login_required
def reports():
    """Reports page."""
    content_template = """
    <h2>Reports</h2>
    <p>Reports functionality coming soon.</p>
    """
    content = render_template_string(content_template)
    return render_template_string(
        BASE_HTML,
        title="Reports",
        view="reports",
        is_admin=is_admin(),
        content=content
    )

@app.route("/logs")
@login_required
def logs():
    """Logs page."""
    user_id = session.get('user_id')
    user_logs = get_user_logs(user_id, limit=5000)
    content_template = """
    <h2>Logs</h2>
    <div class="log-container">
        {% if user_logs %}
        {% for line in user_logs %}
        <div class="log-line">{{ line|safe }}</div>
        {% endfor %}
        {% else %}
        <div class="log-line">No logs available.</div>
        {% endif %}
    </div>
    """
    content = render_template_string(content_template, user_logs=user_logs)
    return render_template_string(
        BASE_HTML,
        title="Logs",
        view="logs",
        is_admin=is_admin(),
        content=content
    )

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """Admin dashboard."""
    users = load_users()
    content_template = """
    <h2>Dashboard</h2>
    <div style="margin: 20px 0;">
        <span class="info-pill">Total Users: {{ total_users }}</span>
    </div>
    <h3 style="margin-top: 30px;">Users</h3>
    <table>
        <tr>
            <th>Username</th>
            <th>Role</th>
            <th>Expiry Date</th>
        </tr>
        {% for user in users %}
        <tr>
            <td>{{ user.username }}</td>
            <td>{{ user.role }}</td>
            <td>{{ user.expiry_date or 'Never' }}</td>
        </tr>
        {% endfor %}
    </table>
    """
    content = render_template_string(content_template, total_users=len(users), users=users)
    return render_template_string(
        BASE_HTML,
        title="Admin Dashboard",
        view="dashboard",
        is_admin=True,
        content=content
    )

@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    """User management page."""
    if request.method == "POST":
        action = request.form.get('action')
        if action == 'add':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            role = request.form.get('role', 'user').strip()
            expiry_days_str = request.form.get('expiry_days', '').strip()
            expiry_days = None
            if expiry_days_str:
                try:
                    expiry_days = int(expiry_days_str)
                except ValueError:
                    flash('Invalid expiry days', 'error')
                    return redirect(url_for('admin_users'))
            if username and password:
                try:
                    password_hash = generate_password_hash(password)
                    create_user(username, password_hash, role, expiry_days)
                    flash('User created successfully', 'success')
                except Exception as e:
                    flash(f'Error: {str(e)}', 'error')
        elif action == 'delete':
            user_id = int(request.form.get('user_id', 0))
            if user_id:
                users = load_users()
                users = [u for u in users if u.get('id') != user_id]
                save_users(users)
                flash('User deleted successfully', 'success')
    
    users = load_users()
    content_template = """
    <h2>User Management</h2>
    <h3>Add New User</h3>
    <form method="POST" style="margin-bottom: 30px;">
        <input type="hidden" name="action" value="add">
        <div class="form-group">
            <label>Username:</label>
            <input type="text" name="username" required>
        </div>
        <div class="form-group">
            <label>Password:</label>
            <input type="password" name="password" required>
        </div>
        <div class="form-group">
            <label>Role:</label>
            <select name="role">
                <option value="user">User</option>
                <option value="admin">Admin</option>
            </select>
        </div>
        <div class="form-group">
            <label>Expiry Days (optional):</label>
            <input type="number" name="expiry_days" min="1">
        </div>
        <button type="submit">Create User</button>
    </form>
    <h3>Existing Users</h3>
    <table>
        <tr>
            <th>ID</th>
            <th>Username</th>
            <th>Role</th>
            <th>Expiry Date</th>
            <th>Actions</th>
        </tr>
        {% for user in users %}
        <tr>
            <td>{{ user.id }}</td>
            <td>{{ user.username }}</td>
            <td>{{ user.role }}</td>
            <td>{{ user.expiry_date or 'Never' }}</td>
            <td>
                <form method="POST" style="display:inline;">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="user_id" value="{{ user.id }}">
                    <button type="submit" style="background: #c62828; width: auto; padding: 6px 12px; font-size: 14px;">Delete</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
    """
    content = render_template_string(content_template, users=users)
    return render_template_string(
        BASE_HTML,
        title="User Management",
        view="users",
        is_admin=True,
        content=content
    )

@app.route("/api/balance")
@login_required
def api_balance():
    """Get balance and capacity."""
    user_id = session.get('user_id')
    balance, capacity, price, error_msg = compute_balance_and_capacity(user_id, include_price=True)
    if error_msg:
        return jsonify({"error": error_msg})
    push_event(user_id, {"type": "balance", "balance": balance, "price": price, "capacity": capacity})
    return jsonify({"balance": balance, "price": price, "capacity": capacity})

@app.route("/api/logs")
@login_required
def api_logs():
    """Get logs for user."""
    user_id = session.get('user_id')
    last_position = int(request.args.get("last_position", 0))
    logs = get_user_logs(user_id, limit=5000)
    new_logs = logs[last_position:]
    return jsonify({
        "logs": new_logs,
        "position": last_position + len(new_logs)
    })

@app.route("/api/worker-status")
@login_required
def api_worker_status():
    """Check if workers are still running."""
    user_id = session.get('user_id')
    LOG_DIR = Path("logs")
    completion_file = LOG_DIR / f"user_{user_id}_running.flag"
    running = False
    try:
        if completion_file.exists():
            # Check if file is stale (older than 15 minutes)
            file_age = time.time() - completion_file.stat().st_mtime
            if file_age > 900:  # 15 minutes
                completion_file.unlink()
                running = False
            else:
                # Check if completion message exists in logs
                latest_log = LOG_DIR / "latest_logs.txt"
                if latest_log.exists():
                    with open(latest_log, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if "[INFO] All workers completed!" in content:
                            completion_file.unlink()
                            running = False
                        else:
                            running = True
                else:
                    running = True
    except Exception:
        pass
    return jsonify({'running': running})

@app.route("/api/stop", methods=["POST"])
@login_required
def api_stop():
    """Stop all workers for current user."""
    user_id = session.get('user_id')
    with user_processes_lock:
        processes = user_processes.get(user_id, [])
        for process in processes:
            try:
                process.kill()
            except Exception:
                pass
        user_processes[user_id] = []
    
    LOG_DIR = Path("logs")
    completion_file = LOG_DIR / f"user_{user_id}_running.flag"
    try:
        if completion_file.exists():
            completion_file.unlink()
    except Exception:
        pass
    
    add_log(user_id, "[INFO] Stop requested by user. Terminating all workers.")
    return jsonify({"status": "stopped"})

@app.route("/stream")
@login_required
def stream():
    """SSE stream for real-time updates."""
    user_id = session.get('user_id')
    def generate():
        q = Queue()
        with event_lock:
            if user_id not in event_subscribers:
                event_subscribers[user_id] = []
            event_subscribers[user_id].append(q)
        try:
            while True:
                try:
                    payload = q.get(timeout=30)
                    yield f"data: {json.dumps(payload)}\n\n"
                except:
                    yield ": keepalive\n\n"
        finally:
            with event_lock:
                if user_id in event_subscribers:
                    event_subscribers[user_id].remove(q)
    return Response(generate(), mimetype='text/event-stream')

def run_account_creator(session_num, total_sessions, user_id):
    """Run a single account creator session."""
    session_id = f"{session_num}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    worker_num = session_num
    LOG_DIR = Path("logs")
    LOG_DIR.mkdir(exist_ok=True)
    latest_log = LOG_DIR / "latest_logs.txt"
    
    try:
        env = os.environ.copy()
        env['USER_ID'] = str(user_id)
        env['SESSION_ID'] = session_id
        env['WORKER_NUM'] = str(worker_num)
        env['PYTHONUNBUFFERED'] = '1'
        
        process = subprocess.Popen(
            ["python", "-u", "account_creator.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )
        
        # Register process
        with user_processes_lock:
            if user_id not in user_processes:
                user_processes[user_id] = []
            user_processes[user_id].append(process)
        
        def read_output():
            try:
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break
                    line = line.rstrip('\n\r')
                    if line:
                        add_log(user_id, line)
            except Exception as e:
                error_msg = f"[ERROR] Worker {worker_num} output read error: {e}"
                add_log(user_id, error_msg)
        
        output_thread = threading.Thread(target=read_output, daemon=True)
        output_thread.start()
        
        process.wait()
        output_thread.join(timeout=5)
        
    except Exception as e:
        error_msg = f"[ERROR] Worker {worker_num} Exception: {e}"
        add_log(user_id, error_msg)
    finally:
        # Unregister process
        with user_processes_lock:
            if user_id in user_processes:
                user_processes[user_id] = [p for p in user_processes[user_id] if p.poll() is None]

def run_parallel_sessions(total_accounts, max_parallel, user_id):
    """Run sessions in batches."""
    LOG_DIR = Path("logs")
    LOG_DIR.mkdir(exist_ok=True)
    clear_user_logs(user_id)
    completion_file = LOG_DIR / f"user_{user_id}_running.flag"
    
    try:
        for log_file in LOG_DIR.glob("*"):
            if log_file.is_file() and log_file.name != completion_file.name:
                try:
                    log_file.unlink()
                except Exception:
                    pass
        latest_log = LOG_DIR / "latest_logs.txt"
        start_msg = "[INFO] Starting new batch..."
        add_log(user_id, start_msg)
        with open(latest_log, 'w', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {start_msg}\n")
        
        with open(completion_file, 'w', encoding='utf-8') as f:
            f.write(f"running\n")
    except Exception as e:
        print(f"[ERROR] Failed to clear logs: {e}")
    
    remaining = total_accounts
    session_num = 1
    
    try:
        while remaining > 0:
            batch_size = min(max_parallel, remaining)
            futures = []
            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                for i in range(batch_size):
                    current_session = session_num + i
                    if i == 0:
                        futures.append(executor.submit(run_account_creator, current_session, total_accounts, user_id))
                    else:
                        time.sleep(2)
                        futures.append(executor.submit(run_account_creator, current_session, total_accounts, user_id))
                
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        error_msg = f"[ERROR] Batch session error: {e}"
                        add_log(user_id, error_msg)
            
            session_num += batch_size
            remaining -= batch_size
        
        completion_msg = "[INFO] All workers completed!"
        add_log(user_id, completion_msg)
        latest_log = LOG_DIR / "latest_logs.txt"
        try:
            with open(latest_log, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {completion_msg}\n")
        except Exception:
            pass
    finally:
        try:
            if completion_file.exists():
                completion_file.unlink()
        except Exception:
            pass

@app.route("/run", methods=["POST"])
@login_required
def run():
    user_id = session.get('user_id')
    total_accounts = int(request.form.get("total_accounts", 10))
    max_parallel = int(request.form.get("max_parallel", 4))
    
    balance, capacity, price, error_msg = compute_balance_and_capacity(user_id, include_price=True)
    if error_msg:
        flash(f'Error: {error_msg}', 'error')
        return redirect(url_for('launcher'))
    
    if capacity is not None and total_accounts > capacity:
        flash(f'Insufficient balance. You can only create {capacity} account(s).', 'error')
        return redirect(url_for('launcher'))
    
    if total_accounts < 1 or max_parallel < 1:
        flash('Invalid input values', 'error')
        return redirect(url_for('launcher'))
    
    thread = threading.Thread(
        target=run_parallel_sessions,
        args=(total_accounts, max_parallel, user_id),
        daemon=True
    )
    thread.start()
    
    return redirect(url_for('launcher'))

if __name__ == "__main__":
    print("Starting Flask app on http://127.0.0.1:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)












