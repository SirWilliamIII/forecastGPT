# Automated Deployment Setup

This document explains the automated deployment system for BloombergGPT to the Oracle production server.

## How It Works

When you push to the `main` branch, GitHub Actions automatically:
1. Syncs backend files to `/opt/bloomberggpt/`
2. Syncs frontend files to `/opt/bloomberggpt/frontend/`
3. Installs frontend dependencies
4. Builds the frontend production bundle
5. Restarts both systemd services
6. Runs health checks
7. Reports deployment status

## Setup GitHub Secrets (One-Time)

You need to add two secrets to your GitHub repository:

### 1. Add SSH Private Key

```bash
# Copy your SSH private key
cat ~/.ssh/ssh-key-2025-11-10.key
```

Then:
1. Go to: https://github.com/SirWilliamIII/forecastGPT/settings/secrets/actions
2. Click **New repository secret**
3. Name: `ORACLE_SSH_KEY`
4. Value: Paste the entire private key (including BEGIN/END lines)
5. Click **Add secret**

### 2. Add SSH Known Hosts

```bash
# Get the known_hosts entry
ssh-keyscan 84.8.155.16
```

Copy the output, then:
1. Go to: https://github.com/SirWilliamIII/forecastGPT/settings/secrets/actions
2. Click **New repository secret**
3. Name: `ORACLE_KNOWN_HOSTS`
4. Value: Paste the ssh-keyscan output
5. Click **Add secret**

## Usage

### Automatic Deployment

Just push to main:
```bash
git add .
git commit -m "feat: your changes"
git push origin main
```

GitHub Actions will automatically deploy to production.

### Manual Deployment

You can also trigger deployment manually:
1. Go to: https://github.com/SirWilliamIII/forecastGPT/actions
2. Click "Deploy to Oracle Production Server"
3. Click "Run workflow"
4. Select branch: `main`
5. Click "Run workflow"

## Monitoring Deployments

### View Deployment Status

1. Go to: https://github.com/SirWilliamIII/forecastGPT/actions
2. Click on the most recent workflow run
3. Watch real-time logs

### Check Production Services

```bash
# SSH to server
ssh -i ~/.ssh/ssh-key-2025-11-10.key ubuntu@84.8.155.16

# Check service status
sudo systemctl status bloomberggpt.service
sudo systemctl status bloomberggpt-frontend.service

# View logs
sudo journalctl -u bloomberggpt.service -f
sudo journalctl -u bloomberggpt-frontend.service -f
```

## What Gets Deployed

**Backend:**
- All Python files (`.py`)
- Configuration files (`config.py`)
- Ingestion modules (`ingest/`)
- ML models (`models/`)
- Database migrations
- Excludes: `.env`, `.venv`, `__pycache__`, `.cache`

**Frontend:**
- All React/Next.js code
- Public assets
- Configuration files
- Excludes: `node_modules`, `.next`, `.env.local`

## Rollback

If a deployment fails, you can rollback:

```bash
# Revert your local commit
git revert HEAD
git push origin main

# Or manually SSH and restore from backup
ssh -i ~/.ssh/ssh-key-2025-11-10.key ubuntu@84.8.155.16
# ... manual restore steps ...
```

## Safety Features

- ✅ **Health checks** after deployment
- ✅ **Automatic service restart**
- ✅ **Preserve `.env` files** (not overwritten)
- ✅ **Exclude development files** (venv, cache, etc.)
- ✅ **Manual trigger option** for controlled deploys

## Troubleshooting

### Deployment Failed

1. Check GitHub Actions logs: https://github.com/SirWilliamIII/forecastGPT/actions
2. Common issues:
   - SSH key not added to secrets
   - Service restart failed (check logs)
   - Health check timeout (server overloaded)

### Service Won't Start

```bash
# SSH to server
ssh -i ~/.ssh/ssh-key-2025-11-10.key ubuntu@84.8.155.16

# Check logs
sudo journalctl -u bloomberggpt.service -n 50 --no-pager

# Restart manually
sudo systemctl restart bloomberggpt.service
```

## Cost

GitHub Actions is free for public repositories with 2,000 minutes/month. This deployment takes ~2-3 minutes per run.

## Local Development

Your local environment is separate and not affected by production deployments:
- **Local**: `localhost:9000` (backend), `localhost:3000` (frontend)
- **Production**: `maybe.probablyfine.lol` (both via Nginx)

Changes run locally via LaunchAgent until you push to GitHub.
