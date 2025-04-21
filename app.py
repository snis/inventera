"""
Main module for backward compatibility.
This file just imports and runs the Flask application from the app package.
"""
from app import create_app

# Create the Flask application
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')