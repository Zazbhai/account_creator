# Domain Setup Guide for creater.husan.shop

## ✅ Configuration Complete

Your `.env` file has been configured to use:
- **Frontend:** https://creater.husan.shop
- **Backend API:** https://api.creater.husan.shop

---

## 🚀 Next Steps - Choose Your Tunneling Method

You need to point your domains to your local development server. Choose ONE of the options below:

---

### **Option 1: Cloudflare Tunnel (RECOMMENDED - FREE)**

This is the best option for production-ready setup with your domain.

#### Step 1: Install Cloudflare Tunnel
```powershell
# Using winget
winget install Cloudflare.cloudflared

# Or download from: https://github.com/cloudflare/cloudflared/releases
```

#### Step 2: Login to Cloudflare
```powershell
cloudflared tunnel login
```
This will open your browser. Login and select your domain `husan.shop`.

#### Step 3: Create a Tunnel
```powershell
cloudflared tunnel create account-creator
```
**IMPORTANT:** Save the Tunnel ID that is displayed!

#### Step 4: Add DNS Routes
```powershell
# Route frontend domain
cloudflared tunnel route dns account-creator creator.husan.shop

# Route backend API domain
cloudflared tunnel route dns account-creator api.creator.husan.shop
```

#### Step 5: Create Config File
Create a file at: `C:\Users\zgarm\.cloudflared\config.yml`

```yaml
tunnel: YOUR_TUNNEL_ID_HERE
credentials-file: C:\Users\zgarm\.cloudflared\YOUR_TUNNEL_ID.json

ingress:
  # Frontend - React app on port 7333
  - hostname: creator.husan.shop
    service: http://localhost:7333
  
  # Backend API on port 6333
  - hostname: api.creator.husan.shop
    service: http://localhost:6333
  
  # Catch-all rule (required)
  - service: http_status:404
```

**Replace `YOUR_TUNNEL_ID_HERE` and `YOUR_TUNNEL_ID.json` with the actual tunnel ID from Step 3!**

#### Step 6: Run the Tunnel
```powershell
cloudflared tunnel run account-creator
```

#### Step 7: Restart Your Services
```powershell
# You can stop ngrok and localtunnel now - you don't need them anymore!

# Restart backend (already running, but to load new .env)
# Stop current python process and restart:
python .\app_backend.py

# Restart frontend (to load new .env)
# Stop current npm and restart:
npm run dev
```

---

### **Option 2: ngrok with Custom Domain (PAID - $8/month)**

If you have ngrok Pro or higher:

#### Step 1: Reserve Domains in ngrok Dashboard
1. Go to https://dashboard.ngrok.com/domains
2. Reserve `creator.husan.shop`
3. Reserve `api.creator.husan.shop`

#### Step 2: Update DNS
Add CNAME records in your `husan.shop` DNS:
- `creator` → Target provided by ngrok
- `api.creator` → Target provided by ngrok

#### Step 3: Run ngrok with Custom Domains
```powershell
# Frontend
ngrok http 7333 --domain=creator.husan.shop

# Backend (in another terminal)
ngrok http 6333 --domain=api.creator.husan.shop
```

---

### **Option 3: Manual DNS with Reverse Proxy (Advanced)**

If you have a VPS or want to deploy to production:

1. Point DNS A records to your server IP
2. Install nginx/Apache as reverse proxy
3. Configure SSL with Let's Encrypt
4. Set up reverse proxy rules

---

## 🧪 Testing Your Setup

### After Setting Up Your Tunnel:

1. **Wait 2-3 minutes** for DNS propagation (Cloudflare is usually instant)

2. **Open your browser** and go to:
   - Frontend: https://creator.husan.shop
   - Backend API health check: https://api.creator.husan.shop/api/health

3. **Try logging in** with:
   - Username: `admin`
   - Password: `admin`

4. **Check browser console** (F12) - you should see API requests going to `https://api.creator.husan.shop`

---

## 📝 What Changed in Your .env

```bash
# Before (localhost):
FRONTEND_URL=http://localhost:7333
VITE_BACKEND_URL=http://localhost:6333

# After (your domains):
FRONTEND_URL=https://creator.husan.shop
VITE_BACKEND_URL=https://api.creator.husan.shop
```

**Benefits:**
- ✅ HTTPS enabled (secure cookies)
- ✅ Professional domain names
- ✅ Can be accessed from anywhere
- ✅ Works on mobile devices
- ✅ Can share with others

---

## 🔧 Troubleshooting

### DNS Not Resolving?
```powershell
# Check DNS resolution
nslookup creator.husan.shop
nslookup api.creator.husan.shop
```

Should show the tunnel/proxy IP addresses.

### CORS Errors?
Your `.env` is already configured with proper CORS settings. If you still see CORS errors:
1. Restart the backend: `python .\app_backend.py`
2. Hard refresh browser (Ctrl + Shift + F5)

### Still seeing localhost URLs?
1. Stop all running services
2. Clear browser cache completely
3. Restart services with new .env
4. Use incognito/private mode to test

### SSL/Certificate Errors?
- Cloudflare Tunnel provides automatic SSL
- ngrok provides automatic SSL
- Make sure you're using `https://` not `http://`

---

## 🎯 Current Running Services

You currently have running:
- `python .\app_backend.py` - ✅ Keep running
- `npm run dev` - ✅ Keep running (restart to load new .env)
- `ngrok http 7333` - ❌ Can stop after setting up Cloudflare
- `lt --port 6333` - ❌ Can stop after setting up Cloudflare

---

## 📌 Important Notes

1. **SESSION_COOKIE_SECURE=True** means cookies only work over HTTPS
2. You must use **https://** when accessing your domains (not http://)
3. Keep the **localhost** entries in CORS_ORIGINS for local development
4. The **Cloudflare Tunnel must be running** for your domains to work

---

## ✅ Recommended Final Setup

**Terminal 1:** Backend
```powershell
python .\app_backend.py
```

**Terminal 2:** Frontend
```powershell
npm run dev
```

**Terminal 3:** Cloudflare Tunnel
```powershell
cloudflared tunnel run account-creator
```

---

Need help with any of these steps? Let me know! 🚀
