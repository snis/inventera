"""
Item model for the inventory application.
"""
from app import db
from datetime import datetime
from typing import Dict, Optional


class Item(db.Model):
    """
    Model representing an inventory item.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), nullable=False, unique=True)
    category = db.Column(db.String(32), nullable=False)
    quantity = db.Column(db.Integer)
    unit = db.Column(db.String(16), nullable=False)
    alert_quantity = db.Column(db.Integer)
    last_checked = db.Column(db.DateTime, default=datetime.utcnow)
    # New fields for Google Tasks integration
    task_id = db.Column(db.String(64), nullable=True)  # Google Tasks task ID if added
    added_to_task = db.Column(db.DateTime, nullable=True)  # When item was added to tasks

    def __repr__(self) -> str:
        """String representation of the item"""
        return f'<Item: {self.name}>'
    
    def to_dict(self) -> Dict:
        """Convert item to dictionary for JSON responses"""
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'quantity': self.quantity,
            'unit': self.unit,
            'alert_quantity': self.alert_quantity,
            'last_checked': self.last_checked.strftime('%d/%m') if self.last_checked else None,
            'task_id': self.task_id,
            'added_to_task': self.added_to_task.strftime('%d/%m') if self.added_to_task else None
        }