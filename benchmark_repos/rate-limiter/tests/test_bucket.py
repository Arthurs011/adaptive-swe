from ratelimit.bucket import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _limiter(max_requests=3, window=10.0):
    clock = Clock()
    return RateLimiter(max_requests, window, now=clock), clock


def test_within_window():
    limiter, _ = _limiter()
    assert limiter.is_allowed("u") is True
    assert limiter.is_allowed("u") is True
    assert limiter.is_allowed("u") is True


def test_limit_reached():
    limiter, _ = _limiter()
    for _ in range(3):
        limiter.is_allowed("u")
    assert limiter.is_allowed("u") is False


def test_per_key_independent():
    limiter, _ = _limiter()
    for _ in range(3):
        limiter.is_allowed("a")
    assert limiter.is_allowed("b") is True


def test_new_window_is_bounded():
    limiter, clock = _limiter()
    for _ in range(3):
        limiter.is_allowed("u")
    assert limiter.is_allowed("u") is False

    clock.advance(10.0)
    for _ in range(3):
        limiter.is_allowed("u")
    assert limiter.is_allowed("u") is False