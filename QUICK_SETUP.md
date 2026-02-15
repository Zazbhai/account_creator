# Quick Reference - Cloudflare Tunnel Setup

## TL;DR - Commands to Run

```powershell
# 1. Install Cloudflare Tunnel
winget install Cloudflare.cloudflared

# 2. Login
cloudflared tunnel login

# 3. Create tunnel
cloudflared tunnel create account-creator

# 4. Add DNS routes
cloudflared tunnel route dns account-creator creater.husan.shop
cloudflared tunnel route dns account-creator api.creater.husan.shop

# 5. Create config file at C:\Users\zgarm\.cloudflared\config.yml
# See template below

# 6. Run tunnel
cloudflared tunnel run account-creator
```

---

## Config File Template

Save as: `C:\Users\zgarm\.cloudflared\config.yml`

```yaml
tunnel: YOUR_TUNNEL_ID_FROM_STEP_3
credentials-file: C:\Users\zgarm\.cloudflared\YOUR_TUNNEL_ID_FROM_STEP_3.json

ingress:
  - hostname: creater.husan.shop
    service: http://localhost:7333
  - hostname: api.creater.husan.shop
    service: http://localhost:6333
  - service: http_status:404
```

---

## Final Running Terminals

**Terminal 1:**
```powershell
python .\app_backend.py
```

**Terminal 2:**
```powershell
npm run dev
```

**Terminal 3:**
```powershell
cloudflared tunnel run account-creator
```

Then visit: **https://creater.husan.shop** 🎉

---

## Already Have ngrok Running?

You can stop these after Cloudflare is set up:
- Press Ctrl+C in ngrok terminal
- Press Ctrl+C in localtunnel terminal

Cloudflare Tunnel will handle both domains!
