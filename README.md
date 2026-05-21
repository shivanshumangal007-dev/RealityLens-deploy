# RealityLens

AI-powered fact verification tool using screenshot analysis. Analyzes visual claims and provides verdicts based on web search and AI analysis.

## Features

- **Screenshot Capture**: Global hotkey-triggered screenshot tool
- **Claim Extraction**: AI extracts verifiable claims from screenshots
- **Web Search**: Searches for supporting/contradicting evidence
- **Verdict Generation**: Returns reality score, confidence, and detailed analysis
- **Multi-Platform**: Windows, macOS, and Linux support

## Architecture

- **Frontend**: PyQt6 desktop app with tray integration
- **Backend**: FastAPI server with async job processing
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Search**: Tavily API for web search, Parallel API for image search
- **AI Models**: Groq, Google Gemini, Cloudflare Kimi

## Getting Started

### Prerequisites

- Python 3.13+
- PostgreSQL 12+ (for production)
- API keys: Groq, Google Gemini, Tavily, Cloudflare (optional)

### Installation

```bash
# Clone and install dependencies
git clone <repo>
cd RealityLens
pip install -e .

# Or use uv
uv sync
```

### Configuration

Create `.env` file:

```env
# AI/Search APIs
GROQ_API_KEY=your_key
GEMINI_API_KEYS=key1,key2,key3
TAVILY_API_KEY=your_key
CLOUDFLARE_AUTH_TOKEN=your_token
ACCOUNT_ID=your_account_id

# Database
DATABASE_URL=postgresql://user:password@localhost/realitylens

# Server
DEPLOYED_SERVER_URL=http://localhost:8000
```

### Running

**Desktop App:**

```bash
python app/main.py
# Or: uv run app/main.py
```

**Backend Server:**

```bash
uvicorn backend.server.main:app --reload
# Or: uv run uvicorn backend.server.main:app --reload
```

Hotkey: **Ctrl+Shift+L** (Win/Linux) or **Cmd+Shift+L** (Mac)

## Building

```bash
python build_all.py
```

Distributable will be in `dist/` folder.

## API Endpoints

### HTTP Endpoints

- `POST /submit` - Submit image for analysis (returns job_id)
- `GET /status/{job_id}` - Poll job status
- `GET /result/{job_id}` - Get analysis result (returns 202 if pending)
- `GET /health_check` - Health check

### WebSocket

- `WS /ws/job/{job_id}` - Subscribe to real-time job updates

### Job ID Details

- **`job_id`**: Returned by `POST /submit` when a new analysis job is created. The server generates this as a UUID (using `uuid.uuid4()`), so each job receives a unique identifier. This is a per-job identifier — it is not a server-wide constant. If you need a server-wide ID shared across jobs, add a separate field in the job model.

## Development

### Project Structure

```
RealityLens/
├── app/              # PyQt6 desktop app
│  ├── main.py       # Entry point
│  └── ui/           # UI components
├── backend/         # FastAPI server
│  ├── server/       # Server and DB
│  ├── ai_calls/     # AI model wrappers
│  └── prompts/      # Prompt templates
├── pyproject.toml   # Dependencies
└── build_all.py     # Build script
```

### Database Setup

```bash
# Create database
createdb realitylens

# Run migrations via SQLAlchemy (automatic on startup)
```

## Deployment

1. Set environment variables
2. Configure PostgreSQL
3. Run backend: `uvicorn backend.server.main:app --host 0.0.0.0 --port 8000`
4. Desktop app connects to `DEPLOYED_SERVER_URL`

## License

Proprietary - All rights reserved
