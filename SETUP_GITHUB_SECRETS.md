# Quick Setup: GitHub Secrets for Auto-Deployment

Follow these steps to enable automated deployment:

## Step 1: Copy SSH Private Key

```bash
cat ~/.ssh/ssh-key-2025-11-10.key
```

**Copy the entire output** (including `-----BEGIN` and `-----END` lines)

## Step 2: Add to GitHub

1. Go to: https://github.com/SirWilliamIII/forecastGPT/settings/secrets/actions
2. Click **"New repository secret"**
3. Name: `ORACLE_SSH_KEY`
4. Value: **Paste the SSH private key**
5. Click **"Add secret"**

## Step 3: Add Known Hosts

Copy this text (already generated for you):

```
84.8.155.16 ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBD7M40Awt8ItRPveiCPr+a588eNkvtzrYana78H0Uofy6UNSOupHNKY4HjBRU69uB/2Z9FVOkr2ldrJHtHOdfus=
84.8.155.16 ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCm+oJtWr3QcSxNVqzSvojIsUDwApeqcH0kwN/jZEeI1s3ZJUmyun8cUXiGYo2tDE/Op3WAN/rBNPsRYxbsDZWl2+iEwTB7chM+VsZrOJ6k55zXWhEeiho3nniMUNkUzzcTZDGyqetjxkiJHIYrwkM1M/cnBE16DTiXElvJmxs4hAEgaLED9MqKSeAdbMY8GjLwRpPfDe4AeiWHlNGWuE+EiKwWgw//GGE8wcHAMIUMLDQNZBlFFy2upovY67zfqS0sIQqG46NTaqY+65LCR2nO2zfZ8GwX4kntsJ/7Lj9Lou+eA7pNnZjG9Ms37U+MIuYbLxzNMotA0bx3uhlDg7gwCfkB3rp9k1O/AIDaF/p8/SB4AehVhRGSRWWt6NMKmYQo6/kPcO5IEaKeRzq010LuUPg82xi1OGmsOeMtIi3ye/XLn2gxEpew7/DP47uPOb3rAt1SSnUIp8uxJ4e+pvTjeQa5X1sXLaQKXe9i6QNWL4rSuYCwkx7RlIMGl9mI6uc=
84.8.155.16 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBeD77Kl8Ag09gqshCAuTxPYIxWSSd8/4844QtkMQuaO
```

Then:
1. Go to: https://github.com/SirWilliamIII/forecastGPT/settings/secrets/actions
2. Click **"New repository secret"**
3. Name: `ORACLE_KNOWN_HOSTS`
4. Value: **Paste the known_hosts text above**
5. Click **"Add secret"**

## Step 4: Push This Commit

```bash
git push origin main
```

This will trigger the first automated deployment!

## Step 5: Monitor Deployment

Watch the deployment in real-time:
https://github.com/SirWilliamIII/forecastGPT/actions

## Done! 🎉

From now on, every push to `main` will automatically deploy to your Oracle server:
- Backend: http://maybe.probablyfine.lol
- Frontend: http://maybe.probablyfine.lol

---

**Need help?** See `DEPLOYMENT.md` for detailed documentation.
