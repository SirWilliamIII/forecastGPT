# Railway + Vercel + Cloudflare Deployment Checklist

## Pre-Deployment
- [ ] Commit all changes: `git add . && git commit -m "prepare for deployment"`
- [ ] Push to GitHub: `git push origin main`
- [ ] Have Cloudflare domain ready (or buy one)

## Part 1: Railway Backend (15 min)

### Railway Setup
- [ ] Sign up at railway.app with GitHub
- [ ] Create new project → Deploy from GitHub → Select bloombergGPT repo
- [ ] Add PostgreSQL: Click "New" → "Database" → "PostgreSQL"
- [ ] Wait for PostgreSQL to be ready (green checkmark)

### Configure Backend
- [ ] Click backend service → "Variables" tab
- [ ] Add environment variables:
  - [ ] `OPENAI_API_KEY=sk-proj-...`
  - [ ] `ANTHROPIC_API_KEY=sk-ant-...`
  - [ ] `GEMINI_API_KEY=AIzaSy...`
  - [ ] `DISABLE_STARTUP_INGESTION=true`
  - [ ] `DISABLE_NFL_ELO_INGEST=true`
  - [ ] `CRYPTO_SYMBOLS=BTC-USD:BTC-USD,ETH-USD:ETH-USD,XMR-USD:XMR-USD`
  - [ ] `EQUITY_SYMBOLS=NVDA:NVDA`
- [ ] Verify `DATABASE_URL` is auto-set (should see it in variables)
- [ ] Trigger deployment: Settings → Redeploy

### Database Setup
- [ ] PostgreSQL service → "Connect" → Copy connection URL
- [ ] Run locally: `./railway-db-setup.sh`
- [ ] Or use Railway Query tab to run:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  -- Then paste db/init.sql contents
  ```

### Verify Backend
- [ ] Deployment shows "Success" (green checkmark)
- [ ] Get Railway URL from Settings → Domains
- [ ] Test: `curl https://your-app-production.up.railway.app/health`
- [ ] Should return: `{"status":"healthy","database":"ok","pgvector":"ok"}`

## Part 2: Vercel Frontend (5 min)

### Vercel Setup
- [ ] Sign up at vercel.com with GitHub
- [ ] Click "Add New..." → "Project"
- [ ] Select bloombergGPT repository
- [ ] Configure:
  - [ ] Root Directory: `frontend`
  - [ ] Framework: Next.js (auto-detected)

### Environment Variable
- [ ] Before deploying, add variable:
  - [ ] Key: `NEXT_PUBLIC_API_URL`
  - [ ] Value: `https://your-app-production.up.railway.app` (from Railway)
- [ ] Click "Deploy"

### Verify Frontend
- [ ] Wait for deployment (2-3 minutes)
- [ ] Visit Vercel URL (e.g., bloomberg-gpt.vercel.app)
- [ ] Check browser console - should connect to Railway backend
- [ ] Test clicking BTC/ETH/Cowboys - should work!

## Part 3: Custom Domain (10 min)

### Railway Custom Domain (Backend)
- [ ] Railway → Backend service → Settings → Domains
- [ ] Click "Custom Domain"
- [ ] Enter: `api.yourdomain.com`
- [ ] Copy the CNAME target shown by Railway

### Cloudflare DNS for Backend
- [ ] Cloudflare Dashboard → Select domain → DNS → Records
- [ ] Add CNAME record:
  - [ ] Type: CNAME
  - [ ] Name: `api`
  - [ ] Target: `your-app-production.up.railway.app`
  - [ ] Proxy: DNS only (gray cloud)
  - [ ] TTL: Auto
- [ ] Wait for Railway to verify domain (1-5 minutes)
- [ ] Optional: Switch to Proxied (orange cloud) after verification

### Vercel Custom Domain (Frontend)
- [ ] Vercel Dashboard → Project → Settings → Domains
- [ ] Add domain: `yourdomain.com`
- [ ] Copy the A record or CNAME shown by Vercel

### Cloudflare DNS for Frontend
- [ ] Add A record (apex domain):
  - [ ] Type: A
  - [ ] Name: `@`
  - [ ] IPv4: (from Vercel, usually `76.76.21.21`)
  - [ ] Proxy: Proxied (orange cloud)
  - [ ] TTL: Auto
- [ ] Add CNAME (www):
  - [ ] Type: CNAME
  - [ ] Name: `www`
  - [ ] Target: `cname.vercel-dns.com`
  - [ ] Proxy: Proxied (orange cloud)
  - [ ] TTL: Auto

### Update Frontend API URL
- [ ] Vercel → Settings → Environment Variables
- [ ] Edit `NEXT_PUBLIC_API_URL`:
  - [ ] New value: `https://api.yourdomain.com`
- [ ] Save and redeploy

### Cloudflare SSL
- [ ] SSL/TLS → Overview → Set to "Full (strict)"
- [ ] SSL/TLS → Edge Certificates → Enable "Always Use HTTPS"
- [ ] Optional: Enable HSTS

## Part 4: Final Verification

### Test Backend
- [ ] `curl https://api.yourdomain.com/health`
- [ ] `curl https://api.yourdomain.com/symbols/available`
- [ ] Should return JSON responses

### Test Frontend
- [ ] Visit `https://yourdomain.com`
- [ ] Open browser console (F12) → Network tab
- [ ] Click BTC/ETH symbols
- [ ] Verify API calls go to `api.yourdomain.com`
- [ ] Verify data updates dynamically

### Test Full Flow
- [ ] Click different symbols (BTC, ETH, XMR)
- [ ] Click different horizons (if available)
- [ ] Click NFL teams (if data available)
- [ ] Check events section updates
- [ ] Verify no console errors

## Post-Deployment

### Enable Ingestion
- [ ] Railway → Backend → Variables
- [ ] Change `DISABLE_STARTUP_INGESTION` to `false`
- [ ] Redeploy or wait for next auto-deploy
- [ ] Check logs to verify RSS ingestion runs

### Monitor
- [ ] Railway Dashboard → View logs for errors
- [ ] Vercel Dashboard → Analytics
- [ ] Cloudflare Dashboard → Analytics

### Optional Improvements
- [ ] Add more RSS feeds in Railway env vars
- [ ] Add more symbols (CRYPTO_SYMBOLS, EQUITY_SYMBOLS)
- [ ] Set up backups (Railway has daily auto-backups)
- [ ] Configure monitoring/alerts

## Troubleshooting

### Backend won't deploy
- [ ] Check Railway logs for errors
- [ ] Verify nixpacks.toml is in repo root
- [ ] Verify all environment variables are set
- [ ] Try manual redeploy

### Frontend can't connect to backend
- [ ] Verify NEXT_PUBLIC_API_URL is correct
- [ ] Check CORS settings in backend
- [ ] Test backend URL directly with curl
- [ ] Check browser console for errors

### Domain not working
- [ ] Wait 5-10 minutes for DNS propagation
- [ ] Verify DNS records in Cloudflare
- [ ] Check Railway/Vercel shows domain as verified
- [ ] Try incognito mode (clear DNS cache)

### Database connection issues
- [ ] Verify pgvector extension is enabled
- [ ] Check DATABASE_URL is set in Railway
- [ ] Test connection with psql locally
- [ ] Check Railway PostgreSQL logs

## Success Criteria

You're done when:
- [ ] `https://api.yourdomain.com/health` returns healthy
- [ ] `https://yourdomain.com` loads the dashboard
- [ ] Clicking symbols updates forecasts
- [ ] No errors in browser console
- [ ] Railway logs show scheduled jobs running

**Estimated Total Time:** 30-40 minutes
**Monthly Cost:** ~$5-10
