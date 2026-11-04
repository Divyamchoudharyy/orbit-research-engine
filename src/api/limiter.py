from slowapi import Limiter
from slowapi.util import get_remote_address

# Single shared limiter instance.
# Imported by both main.py (to attach to app.state) and research.py (for @limiter.limit decorators).
# Creating two separate Limiter() instances breaks rate limiting — they don't share state.
limiter = Limiter(key_func=get_remote_address)
