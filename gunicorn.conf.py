import os

# Port binding
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Timeout configuration (LLM requests can take up to 40 seconds)
timeout = 120

# Workers count (2 workers is recommended for Render's free tier)
workers = 2
