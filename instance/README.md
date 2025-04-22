# Instance Directory

This directory contains instance-specific data that should not be committed to version control.

## Contents

- `db.sqlite3` - The main database file for the application
  - This file is automatically created when the application starts if it doesn't exist
  - It is excluded from Git via .gitignore

## Usage

To initialize the database:

```bash
# Create an empty database:
python create_test_db.py --empty

# Create a database with test data:
python create_test_db.py
```

These commands will create the database file in this directory.