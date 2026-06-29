import time

class RateLimiter:
    def __init__(self, rate_limit_per_minute,refill_rate):
        self.capacity = rate_limit_per_minute
        self.tokens = rate_limit_per_minute
        self.refill_rate = refill_rate / 60
        self.last_refill = time.time()

    def allow_request(self):
        now = time.time()

        elapsed = now - self.last_refill
        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.refill_rate
        )
        self.last_refill = now

        if self.tokens < 1:
            return False

        self.tokens -= 1
        return True