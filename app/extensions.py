"""Flask extension instances."""

from typing import TYPE_CHECKING

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

if TYPE_CHECKING:
    from typing import Any

    from flask_sqlalchemy.model import Model

    class BaseModel(Model):
        """Typed SQLAlchemy base model for static type checking."""

        def __init__(self, **kwargs: Any) -> None: ...
else:
    BaseModel = db.Model
