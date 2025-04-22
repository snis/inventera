# Test Data Directory

This directory contains test databases for the Inventera application.

## Contents

- `empty_db.sqlite3` - Empty database with only the schema
- `test_db.sqlite3` - Database with sample test data

## Usage

You can copy these database files to the instance directory to quickly set up a testing environment:

```bash
# Use empty database:
cp tests/data/empty_db.sqlite3 instance/db.sqlite3

# Use test database with sample data:
cp tests/data/test_db.sqlite3 instance/db.sqlite3
```

Alternatively, you can use the database creation utility:

```bash
# Create a new test database directly in the instance directory:
python create_test_db.py

# Create an empty database in the instance directory:
python create_test_db.py --empty

# Update the test database files:
python create_test_db.py --path tests/data/test_db.sqlite3
python create_test_db.py --empty --path tests/data/empty_db.sqlite3
```

These files provide consistent test data for development and testing.