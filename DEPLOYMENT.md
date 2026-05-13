# RealityLens Deployment Guide

## Pre-Deployment Checklist

### 1. Code Quality

- [x] No debug print statements
- [x] All files pass syntax validation
- [x] Dependencies listed in pyproject.toml
- [x] .gitignore configured for secrets

### 2. Configuration

- [ ] `.env` file created with all required keys
- [ ] DATABASE_URL set to production PostgreSQL
- [ ] DEPLOYED_SERVER_URL set to production domain
- [ ] All API keys validated

### 3. Database

- [ ] PostgreSQL instance running and accessible
- [ ] Database user created
- [ ] Database created (tables auto-created on first startup)

### 4. Security

- [ ] `.env` is NOT committed to git
- [ ] All secrets in environment variables only
- [ ] TLS/HTTPS enabled for production API

## Building

### Desktop Application

```bash
# Install dependencies
pip install -e .
# Or: uv sync

# Build standalone executable
python build_all.py
```

**Outputs:**

- Windows: `dist/RealityLens.exe`
- macOS: `dist/RealityLens.app`
- Linux: `dist/RealityLens`

### Backend Server

```bash
# Using Docker (recommended for production)
docker build -t realitylens-backend .
docker run -p 8000:8000 --env-file .env realitylens-backend

# Or run directly
uvicorn backend.server.main:app --host 0.0.0.0 --port 8000
```

## Deployment Steps

### 1. Prepare Repository

```bash
# Verify no uncommitted changes
git status

# Ensure all files are clean
git clean -fd

# Tag release
git tag -a v0.1.0 -m "Production release"
git push origin v0.1.0
```

### 2. Deploy Backend

```bash
# Option A: Docker
docker build -t realitylens-backend:0.1.0 .
docker push your-registry/realitylens-backend:0.1.0

# Option B: Direct deployment
pip install -r requirements.txt
export $(cat .env | xargs)
uvicorn backend.server.main:app --host 0.0.0.0 --port 8000
```

### 3. Build & Distribute Desktop App

```bash
python build_all.py
```

Then distribute:

- Windows: `dist/RealityLens.exe` to users
- macOS: Sign with `codesign` (see build output)
- Linux: Publish `dist/RealityLens` binary

### 4. Verify Deployment

```bash
# Check backend health
curl https://your-api-domain/health_check

# Verify database connection
# (Logs should show no errors on startup)
```

## Environment Variables

**Required for Production:**

```bash
GROQ_API_KEY=<your-key>
GEMINI_API_KEYS=<key1>,<key2>
TAVILY_API_KEY=<your-key>
DATABASE_URL=postgresql://user:pass@host/db
DEPLOYED_SERVER_URL=https://api.yourdomain.com
```

**Optional:**

```bash
CLOUDFLARE_AUTH_TOKEN=<if using Kimi>
ACCOUNT_ID=<if using Kimi>
```

## Rollback

If issues occur:

```bash
# Stop current version
docker stop realitylens-backend

# Revert to previous tag
git checkout v0.0.1

# Rebuild and redeploy
python build_all.py
```

## Monitoring

- Monitor backend logs for errors
- Track API response times and error rates
- Set up alerts for database connectivity issues
- Monitor rate limit hits from users

## Security Notes

- Never commit `.env` to git
- Rotate API keys regularly
- Use HTTPS for all production endpoints
- Enable database backups
- Restrict database access by IP
- Use environment-specific credentials
