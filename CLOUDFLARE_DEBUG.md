# Cloudflare Tunnel Debugging Guide

## ✅ Changes Made

I've updated `vite.config.js` to properly support Cloudflare Tunnel:

```javascript
host: '0.0.0.0', // Listen on all interfaces for tunnel access
allowedHosts: 'all', // Allow all hosts for Cloudflare Tunnel
```

## 🔧 Steps to Fix Cloudflare Tunnel

### 1. Restart Vite Dev Server

The updated config needs to take effect:

```powershell
# Stop the current npm run dev processes (press Ctrl+C in those terminals)
# Then restart:
npm run dev
```

You should see:
```
VITE v5.x.x  ready in xxx ms
➜  Local:   http://localhost:7333/
➜  Network: http://192.168.x.x:7333/   <-- This means it's listening on all interfaces
```

### 2. Restart Backend (to load new CORS domains)

```powershell
# Stop the current python process (press Ctrl+C)
# Then restart:
python .\app_backend.py
```

### 3. Test Cloudflare Tunnel Configuration

**Check your Cloudflare Tunnel config file:**
Location: `C:\Users\zgarm\.cloudflared\config.yml`

It should look like this:

```yaml
tunnel: YOUR_TUNNEL_ID
credentials-file: C:\Users\zgarm\.cloudflared\YOUR_TUNNEL_ID.json

ingress:
  - hostname: creater.husan.shop
    service: http://localhost:7333
  - hostname: api.creater.husan.shop
    service: http://localhost:6333
  - service: http_status:404
```

### 4. Run Cloudflare Tunnel

```powershell
cloudflared tunnel run account-creator
```

You should see output like:
```
INFO Connection registered
INFO Registered tunnel connection
```

### 5. Test the Domains

**Test frontend:**
```powershell
curl https://creater.husan.shop
```
Should return HTML from your React app.

**Test backend:**
```powershell
curl https://api.creater.husan.shop/api/auth/check
```
Should return JSON: `{"authenticated": false}`

---

## 🐛 Common Issues and Fixes

### Issue 1: "Invalid Host Header" or 403 Error

**Cause:** Vite is rejecting requests from the Cloudflare domain.

**Fix:** ✅ Already fixed in vite.config.js with `allowedHosts: 'all'`

### Issue 2: CORS Errors

**Symptom:** Browser console shows CORS errors when accessing through Cloudflare domain.

**Fix:**
1. Make sure your `.env` has the correct domains:
```bash
CORS_ORIGINS=https://creater.husan.shop,https://api.creater.husan.shop,http://localhost:7333,http://localhost:6333
```

2. Restart the backend to load new CORS settings:
```powershell
# Stop current python process
python .\app_backend.py
```

### Issue 3: Backend API Not Accessible

**Symptom:** Frontend loads but can't connect to API.

**Check:**
1. Is backend running on port 6333?
```powershell
# Windows PowerShell:
Get-NetTCPConnection -LocalPort 6333
```

2. Is Cloudflare Tunnel routing api.creater.husan.shop to port 6333?
Check your config.yml file.

3. Test direct connection:
```powershell
curl http://localhost:6333/api/auth/check
```
Should work locally first.

### Issue 4: DNS Not Resolving

**Symptom:** Domain doesn't load at all.

**Check DNS:**
```powershell
nslookup creater.husan.shop
nslookup api.creater.husan.shop
```

Should return Cloudflare IPs (starting with 172.x or similar).

**Fix:**
- Make sure you ran: `cloudflared tunnel route dns account-creator creater.husan.shop`
- Wait 2-3 minutes for DNS propagation
- Clear browser DNS cache: chrome://net-internals/#dns → "Clear host cache"

### Issue 5: SSL/Certificate Errors

**Symptom:** Browser shows "Your connection is not private" or NET::ERR_CERT_AUTHORITY_INVALID

**Fix:**
Cloudflare automatically provides SSL. If you see this error:
1. Make sure you're using `https://` not `http://`
2. Check that your domain's SSL/TLS setting in Cloudflare dashboard is set to "Full" or "Flexible"

### Issue 6: Tunnel Keeps Disconnecting

**Check:**
1. Cloudflared is running and not showing errors
2. Your internet connection is stable
3. Check cloudflared logs for errors

**Restart tunnel:**
```powershell
# Stop cloudflared (Ctrl+C)
cloudflared tunnel run account-creator
```

---

## 🔍 Debugging Steps

### 1. Check if Services are Running

```powershell
# Check backend port
Get-NetTCPConnection -LocalPort 6333 -ErrorAction SilentlyContinue

# Check frontend port
Get-NetTCPConnection -LocalPort 7333 -ErrorAction SilentlyContinue
```

### 2. Check Cloudflare Tunnel Status

Visit Cloudflare Dashboard:
- Go to https://one.dash.cloudflare.com/
- Navigate to "Zero Trust" → "Networks" → "Tunnels"
- Your tunnel should show as "HEALTHY"

### 3. Test Each Layer

**Layer 1: Local services work?**
```powershell
curl http://localhost:7333  # Should return HTML
curl http://localhost:6333/api/auth/check  # Should return JSON
```

**Layer 2: Tunnel is routing?**
Check cloudflared terminal output - should show "Connection registered"

**Layer 3: DNS is resolving?**
```powershell
nslookup creater.husan.shop
```

**Layer 4: HTTPS working?**
Open browser: `https://creater.husan.shop`

### 4. Browser Console Errors

Open browser DevTools (F12) → Console tab

**Look for:**
- CORS errors → Backend needs restart with new .env
- Network errors → Cloudflare tunnel not routing properly
- Invalid Host → Vite config issue (already fixed)

---

## ✅ Success Checklist

- [ ] Vite dev server restarted with new config
- [ ] Backend restarted with correct CORS origins in .env
- [ ] Cloudflare Tunnel running (`cloudflared tunnel run account-creator`)
- [ ] DNS resolving to Cloudflare IPs
- [ ] `https://creater.husan.shop` loads the frontend
- [ ] `https://api.creater.husan.shop/api/auth/check` returns JSON
- [ ] Can login through the custom domain
- [ ] No CORS errors in browser console

---

## 🆚 Why ngrok Works but Cloudflare Doesn't

**ngrok:**
- Handles host headers automatically
- No strict host validation
- Works with default Vite config

**Cloudflare Tunnel:**
- Sends actual domain in Host header (creater.husan.shop)
- Vite by default only allows localhost
- Requires `host: '0.0.0.0'` and `allowedHosts` config

**This is now fixed!** ✅

---

## 📞 Still Not Working?

1. **Share the error you're seeing:**
   - Browser console errors?
   - Cloudflared terminal errors?
   - Backend terminal errors?

2. **Check these outputs:**
```powershell
# What does Vite show when starting?
npm run dev

# What does cloudflared show?
cloudflared tunnel run account-creator

# Test DNS:
nslookup creater.husan.shop

# Test local backend:
curl http://localhost:6333/api/auth/check
```

Send me the outputs and I'll help debug further!
