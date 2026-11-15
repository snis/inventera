"""
Settings model for the inventory application.
"""

from app.extensions import db


class Settings(db.Model):
    """
    Model representing application settings.
    """

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), nullable=False, unique=True)
    value = db.Column(db.Text, nullable=True)

    def __repr__(self) -> str:
        """String representation of the setting"""
        return f"<Setting: {self.key}>"

    @classmethod
    def get(cls, key: str, default=None) -> str:
        """Get a setting value by key with optional default"""
        setting = cls.query.filter_by(key=key).first()
        if setting and setting.value is not None:
            return setting.value
        return default

    @classmethod
    def set(cls, key: str, value: str | None) -> None:
        """Stage a setting value change in the current session (caller owns commit)."""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = cls(key=key, value=value)
            db.session.add(setting)
        db.session.flush()
