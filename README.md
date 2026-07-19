# ⚽ FIFA World Cup 2026 - Smart Stadium & Tournament Operations Command Dashboard

A real-time GenAI-powered solution designed to optimize crowd operations, gate flow congestion, staff allocations, and emergency incident dispatch at World Cup 2026 stadiums.

---

## 📖 Key Features & Capabilities

### 1. Operations Command Center (Operations View)
- **Live Gate Telemetry**: Real-time display of queue wait times and staff count. Wait times are categorized using color-coded statuses (Optimal, Moderate, Delay).
- **Interactive SVG Arena Map**: A dynamic stadium heatmap displaying gate delay quadrants. Gate colors update in real time based on active queue delays.
- **AI Gate Flow Optimizer**: Automatically evaluates all gate queue wait times and staff distribution to generate optimization re-allocation scripts.
- **Incident Logger & Dispatcher**: Log emergency incidents. GenAI analyzes the details, classifies the severity (Low/Medium/High), and drafts tactical dispatch notes.
- **Crowd Simulator**: Instantly fluctuates crowd density distributions across gates to test AI re-allocation recommendations.
- **Staff Reallocation Handler**: Execute coordinators re-allocations from one gate to another, dynamically recalculating estimated delay times.

### 2. Fan Assistant Center (Fan View)
- **Real-Time AI Assistant**: Memory-enabled guest assistant answering questions about transit routes, gate queue delays, seat coordinates, concessions, and accessibility features.
- **Interactive Arena Navigation Map**: Real-time gate indicators guiding fans to the fastest entrance.

---

## 🛠️ Technology Stack
- **Backend & Server**: Python `3.11.8` on Flask, with Gunicorn timeouts configured to `120s` to protect slow LLM responses from disconnects.
- **Database Layer**: SQLAlchemy ORM with SQLite (fallback to PostgreSQL/Neon connection pools). Features eager relationship loading (`joinedload`) to eliminate N+1 latency loops.
- **Generative AI Orchestration**: Primary **Google Gemini API** (2.5-flash / 2.5-pro) coupled with a direct **Groq REST API fallback** (llama-3.3-70b) if Gemini rate limits are hit.
- **Production Security**: Custom CSRF request token checks, input HTML-escaping (stored XSS block), PBKDF2 credential encryption, and response headers (`CSP`, `nosniff`, `clickjacking`).
- **Universal Accessibility (WCAG AA)**: Keyboard skip navigation links, explicit ARIA controls, landmarks, and `aria-live` status blocks.
- **Test Suite**: 19 comprehensive unit tests verifying boundaries, logical math, authentication routes, and AI fallback states.

---

## 🚀 Local Installation & Running

1. **Clone & Setup Environment**:
   Ensure you are in the project folder and configure your `.env` variables:
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
   python -m unittest test_app.py
   ```
