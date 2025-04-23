# Google Tasks Integration for Inventera

This feature adds integration with Google Tasks to automatically create task reminders for items that are low in inventory.

## Features

- **Automatic Task Creation**: Creates tasks in Google Tasks for items below their alert threshold
- **Category Mapping**: Map inventory categories to specific Google Task lists
- **Admin Configuration**: Hidden settings page for Google Tasks setup
- **Automatic Daily Checks**: Cron job for daily synchronization and 7-day check alerts
- **Manual Sync Button**: "Klar" button on the main page to manually trigger sync

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Migrate the Database

Run the database migration script to update the schema:

```bash
python migrate_db.py
```

This will add the necessary tables and columns for Google Tasks integration.

### 3. Enable Google Tasks API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the Google Tasks API for your project
4. Create OAuth 2.0 credentials
5. Configure the consent screen

### 4. Access the Settings Page

The settings page is hidden by default to prevent unauthorized access. To access it:

- Add `?admin=true` to the URL of any page (e.g., `http://localhost:5000/?admin=true`)
- A new "Inställningar" link will appear in the navigation bar

### 5. Configure Google Tasks Integration

1. Open the settings page
2. Paste your OAuth token in JSON format in the text area
3. Click "Anslut till Google Tasks" to authenticate
4. Set up a default task list for uncategorized items
5. Create mappings between inventory categories and specific task lists

### 6. Set Up Cron Job (Optional)

For automatic daily synchronization:

```bash
# Edit crontab
crontab -e

# Add this line to run the script daily at midnight
0 0 * * * cd /path/to/inventera && python3 cron_task.py >> /path/to/inventera/cron.log 2>&1
```

## Using the Integration

### Syncing Tasks Manually

Click the "Klar" button at the bottom of the main inventory page to sync low-inventory items to Google Tasks.

### Daily Automatic Sync

If you've set up the cron job, the system will automatically:

1. Sync low-inventory items to Google Tasks daily
2. Alert about items not checked in over 7 days

### How It Works

1. An item is considered "low inventory" when its quantity is ≤ alert_quantity
2. When synced, a task is created in the appropriate task list based on the item's category
3. If no mapping exists for the category, the default task list is used
4. Tasks include information about the item's quantity, alert threshold, and last checked date
5. Items are only re-added to tasks if they've been checked after their last sync

## Security Notes

- The OAuth token is stored in `instance/google_token.json` and is excluded from git
- The token is also stored in the database for backup purposes
- Access to the settings page requires knowledge of the URL parameter

## Troubleshooting

- If integration fails, check the logs for error messages
- Ensure Google Tasks API is enabled for your project
- Verify your OAuth token has the correct scopes (`https://www.googleapis.com/auth/tasks`)
- Check that the token has not expired (refresh tokens should handle this automatically)