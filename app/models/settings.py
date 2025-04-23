"""
Settings model for the inventory application.
"""
from app import db
from typing import Dict, Optional, List
import json


class Settings(db.Model):
    """
    Model representing application settings.
    """
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), nullable=False, unique=True)
    value = db.Column(db.Text, nullable=True)
    
    def __repr__(self) -> str:
        """String representation of the setting"""
        return f'<Setting: {self.key}>'
    
    @classmethod
    def get(cls, key: str, default=None) -> str:
        """Get a setting value by key with optional default"""
        setting = cls.query.filter_by(key=key).first()
        if setting and setting.value is not None:
            return setting.value
        return default
    
    @classmethod
    def set(cls, key: str, value: str) -> None:
        """Set a setting value by key"""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = cls(key=key, value=value)
            db.session.add(setting)
        db.session.commit()


class CategoryTaskMapping(db.Model):
    """
    Model representing mapping between inventory categories and Google Tasks lists.
    """
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(32), nullable=False, unique=True)
    tasklist_id = db.Column(db.String(64), nullable=False)
    tasklist_name = db.Column(db.String(64), nullable=False)
    
    def __repr__(self) -> str:
        """String representation of the mapping"""
        return f'<CategoryTaskMapping: {self.category} -> {self.tasklist_name}>'
    
    def to_dict(self) -> Dict:
        """Convert mapping to dictionary for JSON responses"""
        return {
            'id': self.id,
            'category': self.category,
            'tasklist_id': self.tasklist_id,
            'tasklist_name': self.tasklist_name
        }
    
    @classmethod
    def get_mapping_for_category(cls, category: str) -> Optional['CategoryTaskMapping']:
        """Get task list mapping for a specific category"""
        return cls.query.filter_by(category=category).first()
    
    @classmethod
    def get_default_tasklist(cls) -> Optional[Dict]:
        """Get default task list from settings"""
        default_id = Settings.get('default_tasklist_id')
        default_name = Settings.get('default_tasklist_name')
        
        if default_id and default_name:
            return {
                'tasklist_id': default_id,
                'tasklist_name': default_name
            }
        return None
    
    @classmethod
    def set_default_tasklist(cls, tasklist_id: str, tasklist_name: str) -> None:
        """Set default task list in settings"""
        Settings.set('default_tasklist_id', tasklist_id)
        Settings.set('default_tasklist_name', tasklist_name)