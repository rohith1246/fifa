import os

# Port binding
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Timeout configuration (LLM requests can take up to 40 seconds)
timeout = 120

# Worker configuration for WebSockets threading compatibility
worker_class = "gthread"
workers = 1
threads = 4


