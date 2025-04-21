# Inventera

Inventera is a simple and effective inventory management web application built with Flask. It helps track inventory items, monitor stock levels, and manage inventory checks.

![Inventory Screen](screenshots/inventory.jpg)

## Features

- Track inventory items with name, category, quantity, unit, and alert thresholds
- Visual color-coding for inventory status (red for below alert level, yellow for unchecked items)
- One-click quantity updates
- Categorized inventory organization
- Mobile-responsive design
- Simple, intuitive interface
- SQLite database for easy deployment

## Installation

### Local Setup

1. Clone the repository:
   ```
   git clone <repository-url>
   cd inventera
   ```

2. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Initialize the database:
   ```
   # For an empty database:
   python create_test_db.py --empty
   
   # For a database with test data:
   python create_test_db.py
   ```

4. Run the application:
   ```
   python run.py
   ```

5. Access the application at http://localhost:5000

### Docker Setup

1. Build the Docker image:
   ```
   docker build -t inventera .
   ```

2. Run the container:
   ```
   docker run -p 5000:5000 -d inventera
   ```

3. Access the application at http://localhost:5000

## Usage

- **Main Inventory View**: View all inventory items and quickly update quantities
- **"Uppdatera" Button**: Click to mark an item as checked and update its last checked date
- **Color Coding**:
  - Red: Item quantity is below alert threshold
  - Yellow: Item hasn't been checked recently

## Development

### Database Management

The application uses SQLite databases in the following structure:

- **Production database**: `instance/db.sqlite3` - Created automatically when running the app
- **Test databases**: Located in `tests/data/` directory
  - `test_db.sqlite3` - Contains sample test data
  - `empty_db.sqlite3` - Empty database with schema only

Database utilities:

```bash
# Create a test database with sample data:
python create_test_db.py

# Create an empty database (schema only):
python create_test_db.py --empty

# Specify a custom database path:
python create_test_db.py --path /path/to/custom_db.sqlite3
```

If the production database doesn't exist, the application will create it automatically on startup.

## Technologies

- Backend: Flask, SQLAlchemy
- Database: SQLite
- Frontend: HTML, CSS, JavaScript/jQuery
- Container: Docker support

## Project Structure

```
inventera/
├── app/                    # Main application package
│   ├── controllers/        # Route handlers
│   ├── models/             # Database models
│   ├── static/             # Static assets (CSS, JS)
│   ├── templates/          # Jinja2 HTML templates
│   └── utils/              # Helper utilities
├── instance/               # Instance-specific data
│   └── db.sqlite3          # Production database
├── tests/                  # Test files
│   └── data/               # Test databases
│       ├── empty_db.sqlite3  # Empty schema
│       └── test_db.sqlite3   # Sample data
├── run.py                  # Application entry point
├── app.py                  # Backwards compatibility module
└── create_test_db.py       # Database management utility
```

## Screenshots

![Home Screen](screenshots/index.jpg)
![Inventory Screen](screenshots/inventory.jpg)

## License

[Insert appropriate license information here]