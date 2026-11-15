"""
Item model for the inventory application.
"""

from sqlalchemy.orm import validates

from app.config import utc_now
from app.extensions import BaseModel, db


class Unit(BaseModel):
    """Model representing a measurement unit with a stable database ID."""

    __tablename__ = "units"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), nullable=False, unique=True)


class Location(BaseModel):
    """Model representing a storage location with a stable database ID."""

    __tablename__ = "locations"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, unique=True)


class Store(BaseModel):
    """Model representing a store/supplier with a stable database ID."""

    __tablename__ = "stores"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, unique=True)


class Item(BaseModel):
    """
    Model representing an inventory item.
    """

    __table_args__ = {"sqlite_autoincrement": True}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), nullable=False, unique=True)
    name_key = db.Column(db.String(128), nullable=False, unique=True)
    category = db.Column(db.String(32), nullable=True, default="")
    quantity = db.Column(db.Integer)
    unit = db.Column(db.String(16), nullable=False, default="")
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id"), nullable=True)
    alert_quantity = db.Column(db.Integer)
    last_checked = db.Column(db.DateTime, default=utc_now)
    location = db.Column(db.String(32), nullable=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"), nullable=True)
    store = db.Column(db.String(32), nullable=True)
    store_id = db.Column(db.Integer, db.ForeignKey("stores.id"), nullable=True)
    # New fields for Google Tasks / Home Assistant integration
    task_id = db.Column(db.String(64), nullable=True)  # Tasks task ID if added
    added_to_task = db.Column(db.DateTime, nullable=True)  # When item was added to tasks
    is_visible = db.Column(db.Boolean, nullable=False, default=True)
    version = db.Column(db.Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}

    @validates("name")
    def normalize_name(self, _key: str, value: str) -> str:
        """Keep database uniqueness consistent with Unicode name comparisons."""
        self.name_key = value.strip().casefold()
        return value

    unit_rel = db.relationship("Unit", foreign_keys=[unit_id])
    location_rel = db.relationship("Location", foreign_keys=[location_id])
    store_rel = db.relationship("Store", foreign_keys=[store_id])

    def __repr__(self) -> str:
        """String representation of the item"""
        return f"<Item: {self.name}>"

    def to_dict(self) -> dict:
        """Convert item to dictionary for JSON responses"""
        return {
            "id": self.id,
            "name": self.name,
            "quantity": self.quantity,
            "unit": self.unit_rel.name if self.unit_rel else self.unit,
            "unit_id": self.unit_id,
            "alert_quantity": self.alert_quantity,
            "last_checked": self.last_checked.strftime("%d/%m") if self.last_checked else None,
            "location": self.location_rel.name if self.location_rel else self.location,
            "location_id": self.location_id,
            "store": self.store_rel.name if self.store_rel else self.store,
            "store_id": self.store_id,
            "task_id": self.task_id,
            "added_to_task": self.added_to_task.strftime("%d/%m") if self.added_to_task else None,
            "is_visible": bool(self.is_visible),
            "version": self.version,
        }
