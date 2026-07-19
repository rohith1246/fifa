# ⚽ FIFA World Cup 2026 - Smart Stadium & Tournament Operations Command Dashboard

A real-time **Generative AI-powered** solution designed to optimize crowd operations, gate flow congestion, staff allocations, and emergency incident dispatch at FIFA World Cup 2026 stadiums across the USA, Canada, and Mexico.

---

## 🤖 Generative AI Integration

This project uses **Google Gemini API** as the primary GenAI engine with **Groq (LLaMA 3.3)** as an automatic fallback:

| AI Feature | Description | Model |
|---|---|---|
| **Fan Chat Assistant** | Real-time multilingual guest assistant with stadium gate telemetry context | Gemini 2.5 Flash / Pro |
| **Incident Classification** | Auto-classifies incident severity (Low/Medium/High) and generates tactical dispatch notes | Gemini → Groq fallback |
| **Flow Optimization** | Analyzes gate congestion profiles and recommends staff re-allocations | Gemini → Groq fallback |
| **PA Announcements** | Generates multilingual stadium-wide public address announcements | Gemini → Groq fallback |
| **Matchday Briefing** | AI-generated operations briefing covering crowd management, transport, and fan morale | Gemini → Groq fallback |

All AI calls use a **triple-tier resilience pattern**: Gemini multi-model cascade → Groq REST fallback → Offline mock response.

---

## 📖 Key Features & Capabilities

### 1. Operations Command Center (Operations View)
- **Live Gate Telemetry**: Real-time display of queue wait times and staff count with WebSocket push updates every 10 seconds. Wait times are categorized using color-coded statuses (Optimal, Moderate, Delay).
- **KPI Analytics Dashboard**: Aggregate operational metrics including average wait time, total staff deployed, pending incidents, and fan interaction counts.
- **Interactive SVG Arena Heatmap**: A dynamic stadium heatmap displaying gate delay quadrants. Gate colors update in real time based on active queue delays.
- **AI Gate Flow Optimizer**: Automatically evaluates all gate queue wait times and staff distribution to generate optimization re-allocation scripts.
- **Incident Logger & Dispatcher**: Log emergency incidents. GenAI analyzes the details, classifies the severity (Low/Medium/High), and drafts tactical dispatch notes.
- **Crowd Simulator**: Instantly fluctuates crowd density distributions across gates to test AI re-allocation recommendations.
- **Staff Reallocation Handler**: Execute coordinator re-allocations from one gate to another, dynamically recalculating estimated delay times.
- **AI PA Announcement Generator**: Generate multilingual public address announcements for 80,000+ fan broadcast.

### 2. Fan Assistant Center (Fan View)
- **Real-Time AI Assistant**: Memory-enabled guest assistant answering questions about transit routes, gate queue delays, seat coordinates, concessions, and accessibility features. Supports multilingual responses.
- **Interactive Arena Navigation Map**: Real-time gate indicators guiding fans to the fastest entrance.
- **Matchday Briefing**: AI-generated FIFA 2026 tournament context and fan preparation tips.

---

## 🏗️ Architecture

```
smart_stadium/
├── app.py                    # Flask app entrypoint, SocketIO WebSocket server
├── config.py                 # Environment-driven configuration with session security
├── database.py               # SQLAlchemy engine, connection pooling, session factory
├── models.py                 # ORM models: User, StadiumGate, StaffAllocation, Incident, ChatLog
├── gunicorn.conf.py          # Production WSGI server configuration
├── routes/
│   ├── auth.py               # Registration, login, logout with PBKDF2 hashing
│   ├── api.py                # All API endpoints: chat, incidents, staff, optimize, analytics
│   └── dashboard.py          # Dashboard and landing page views
├── services/
│   ├── ai_service.py         # Gemini/Groq AI orchestration with 30s TTL gate cache
│   └── security.py           # CSRF protection, XSS escaping, rate limiting, security headers
├── templates/                # Jinja2 HTML templates with ARIA accessibility
├── static/style.css          # Glassmorphic sage green theme with responsive design
└── test_app.py               # 24 automated unit tests
```

---

## 🛠️ Technology Stack
- **Backend & Server**: Python `3.11` on Flask with Gunicorn (gthread workers, 120s timeout for LLM requests).
- **Real-Time Communication**: Flask-SocketIO WebSockets for live gate telemetry push (10-second interval).
- **Database Layer**: SQLAlchemy ORM with SQLite (local) / PostgreSQL (production). Features eager relationship loading (`joinedload`) and 30-second in-memory gate cache.
- **Generative AI Orchestration**: Primary **Google Gemini API** (2.5-flash / 2.5-pro / 1.5-flash) with **Groq REST API** (LLaMA 3.3-70b) fallback.
- **Production Security**: CSRF token validation, input HTML-escaping (stored XSS prevention), PBKDF2 credential hashing, rate limiting, and security response headers (CSP, X-Frame-Options, nosniff).
- **Accessibility (WCAG AA)**: Skip navigation links, ARIA landmarks, `aria-live` regions, `aria-required` attributes, keyboard focus-visible rings, and semantic HTML structure.
- **Test Suite**: 24 comprehensive automated tests covering authentication, RBAC, CSRF, XSS, staff math, AI classification, fallback, WebSocket telemetry, and API endpoint access control.

---

## 🚀 Local Installation & Running

1. **Clone & Setup Environment**:
   ```env
   FLASK_SECRET_KEY=your_secret_key_here
   GEMINI_API_KEY=your_gemini_api_key_here
   GROQ_API_KEY=your_groq_api_key_here
   DATABASE_URL=sqlite:///smart_stadium.db
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Application**:
   ```bash
   python app.py
   ```
   Open your browser to `http://127.0.0.1:5000/`.

4. **Execute Automated Tests**:
   ```bash
   python -m unittest test_app.py -v
   ```
