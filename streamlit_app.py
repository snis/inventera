import streamlit as st
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# Databasinställningar
DATABASE_URI = 'sqlite:///db.sqlite3'
engine = create_engine(DATABASE_URI)
Session = sessionmaker(bind=engine)
session = Session()
Base = declarative_base()

class Item(Base):
    __tablename__ = 'item'
    id = Column(Integer, primary_key=True)
    name = Column(String(32), nullable=False, unique=True)
    category = Column(String(32), nullable=False)
    quantity = Column(Integer)
    unit = Column(String(16), nullable=False)
    alert_quantity = Column(Integer)
    last_checked = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Item: {self.name}>'

Base.metadata.create_all(engine)

def get_row_color(last_checked):
    if last_checked:
        days_difference = (datetime.now() - last_checked).days
        if days_difference < 1:
            return '#00ff00aa'
        elif 1 <= days_difference <= 5:
            return '#adff2faa'
        elif 4 <= days_difference <= 8:
            return '#ff8c00aa'
        else:
            return '#ff0000aa'
    else:
        return 'grey'

def get_warning_color(quantity, alert_quantity):
    if quantity is not None and alert_quantity is not None:
        quantity_difference = quantity - alert_quantity
        if quantity_difference == 0:
            return '#adff2faa'
        elif quantity_difference < 0:
            return '#ff0000aa'
        else:
            return '#00ff00aa'
    else:
        return 'grey'

st.title('Inventory Management')

menu = ['Home', 'Inventory']
choice = st.sidebar.selectbox('Menu', menu)

if choice == 'Home':
    st.subheader('Home')
    categories = session.query(Item.category).distinct()
    for category in categories:
        st.write(f"## {category[0]}")
        items = session.query(Item).filter_by(category=category[0]).order_by(Item.name).all()
        for item in items:
            st.write(f"**{item.name}**: {item.quantity} {item.unit}")
            st.write(f"Last checked: {item.last_checked}")

elif choice == 'Inventory':
    st.subheader('Inventory')
    categories = session.query(Item.category).distinct()
    items_by_category = {}

    for category in categories:
        items = session.query(Item).filter_by(category=category[0]).order_by(Item.name).all()
        items_by_category[category[0]] = items

    for category, items in items_by_category.items():
        st.write(f"### {category}")
        for item in items:
            st.write(f"**{item.name}** - {item.quantity} {item.unit}")
            new_quantity = st.number_input(f"New quantity for {item.name}", min_value=0, key=f"new_quantity_{item.id}")
            if st.button(f"Update {item.name}", key=f"update_{item.id}"):
                item.quantity = new_quantity
                item.last_checked = datetime.now()
                session.commit()
                st.success(f"Updated {item.name}")

    st.write("## Add new item")
    new_name = st.text_input("Name")
    new_category = st.text_input("Category")
    new_quantity = st.number_input("Quantity", min_value=0)
    new_alert_quantity = st.number_input("Alert Quantity", min_value=0)
    new_unit = st.text_input("Unit")

    if st.button("Add Item"):
        new_item = Item(name=new_name, category=new_category, quantity=new_quantity, alert_quantity=new_alert_quantity, unit=new_unit)
        session.add(new_item)
        session.commit()
        st.success(f"Added {new_name}")

    st.write("## Remove item")
    remove_id = st.number_input("ID of item to remove", min_value=0)
    if st.button("Remove Item"):
        item_to_remove = session.query(Item).get(remove_id)
        if item_to_remove:
            session.delete(item_to_remove)
            session.commit()
            st.success(f"Removed item with ID {remove_id}")
        else:
            st.error(f"No item found with ID {remove_id}")
