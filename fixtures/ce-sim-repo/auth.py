"""Tiny Python fixture for install-and-forget lifecycle sim."""


def authenticate(user: str, password: str) -> bool:
    """Validate credentials for the demo auth flow."""
    if not user or not password:
        return False
    return password_strength(password) >= 8


def password_strength(password: str) -> int:
    """Return a simple strength score."""
    score = len(password)
    if any(c.isdigit() for c in password):
        score += 2
    if any(c.isupper() for c in password):
        score += 2
    return score


def resource_manager_pressure(cpu: float, ram_free_mb: float) -> str:
    """Classify host pressure for indexing throttle demos."""
    if ram_free_mb < 512 or cpu >= 90:
        return "critical"
    if cpu >= 70:
        return "busy"
    if cpu < 25:
        return "idle"
    return "normal"
