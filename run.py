"""
Run module for the inventory application.
This file is used to run the application from the command line.
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')