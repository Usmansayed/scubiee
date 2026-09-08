"""Record lookup. Method name is resolve, not get_user."""

from app.config.database import connect
from app.models.user import User
from app.utils.logger import log


class UserRepository:
    def resolve(self, key: str) -> dict:
        log("lookup")
        db = connect()
        return User.lookup(db, key)
