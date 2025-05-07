# Instagram DM Automation Bot

This bot automates Instagram direct messages using ChatGPT to respond to incoming messages.

## Features

- Automatically responds to incoming Instagram direct messages
- Handles pending message requests from new users (approves and responds)
- Combines multiple consecutive user messages for better context
- Uses MongoDB (or in-memory storage) to track conversation history
- Uses ChatGPT to generate human-like responses
- Configurable check intervals and response prefixes
- Session persistence to avoid frequent logins
- Implements exponential backoff to reduce API calls when inactive
- Stores conversation data in a separate dashboard database for monitoring
- External system prompt file for easy customization without code changes
- Preserves conversation context for more coherent exchanges

## Prerequisites

- Python 3.7+
- Instagram account
- OpenAI API key
- MongoDB (optional)

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/instagram-dm-bot.git
   cd instagram-dm-bot
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Set up your environment variables by copying the example file:
   ```
   cp .env.example .env
   ```

4. Edit the `.env` file with your credentials:
   ```
   # Instagram credentials
   IG_USERNAME=your_instagram_username
   IG_PASSWORD=your_instagram_password

   # OpenAI API key
   OPENAI_API_KEY=your_openai_api_key
   
   # MongoDB settings (optional, leave empty to use in-memory storage)
   MONGODB_URI=mongodb://localhost:27017/
   
   # Dashboard database settings (for admin monitoring)
   DASHBOARD_DB_URI=mongodb://localhost:27017/
   DASHBOARD_DB_NAME=instagram_dashboard
   
   # Bot settings
   CHECK_INTERVAL=60
   RESPONSE_PREFIX="[Bot] "
   COMBINE_MESSAGES=1
   COMBINE_LIMIT=5
   DEBUG_MODE=0
   
   # Conversation context settings
   PRESERVE_CONTEXT=1
   CONTEXT_MESSAGE_LIMIT=10
   ```

5. Customize the system prompt in `system_prompt.txt`:
   ```
   You are an AI assistant managing Instagram direct messages.
   Be helpful, friendly, and concise in your responses.
   ...
   ```

## Usage

Run the bot with:

```
python bot.py
```

The bot will:
1. Log in to your Instagram account
2. Check for new message requests and approve them
3. Check for unread direct messages using exponential backoff
4. Combine multiple consecutive messages from users
5. Process all messages and respond using ChatGPT
6. Store conversation history for better message tracking
7. Store all messages and statistics in the dashboard database
8. Log all activity to both console and `bot.log`

To stop the bot, press `Ctrl+C` in the terminal.

## Customization

### System Prompt

The bot uses a separate `system_prompt.txt` file for the ChatGPT system instructions. You can edit this file at any time to customize how the bot responds, without needing to modify any code.

To reload the system prompt after making changes (without restarting the bot), you can use:
```
python reload_prompt.py
```

This utility will:
- Verify the prompt file exists and can be read
- Display the current prompt content
- Test loading the prompt with the ChatGPT client
- Optionally test the prompt with a sample message

### Conversation Context

The bot can preserve conversation context by sending previous messages from the thread to ChatGPT. This allows for more coherent exchanges and enables ChatGPT to remember previous messages in the conversation.

Configure the conversation context feature in the `.env` file:
```
# Whether to preserve conversation context (1=enabled, 0=disabled)
PRESERVE_CONTEXT=1
# Maximum number of messages to include in conversation history
CONTEXT_MESSAGE_LIMIT=10
```

Using conversation history increases token usage but provides more natural and contextually relevant responses.

### Message Combination

The bot can combine multiple consecutive messages from a user into a single prompt for ChatGPT. This allows for better context when a user sends several messages in sequence.

You can configure this with the following settings in the `.env` file:
```
# Whether to combine multiple user messages (1=yes, 0=no)
COMBINE_MESSAGES=1
# Maximum number of messages to combine
COMBINE_LIMIT=5
```

### Database Configuration

The bot can use MongoDB to store message history or fall back to in-memory storage if no MongoDB connection is provided.

To use MongoDB, set the connection string in the `.env` file:
```
MONGODB_URI=mongodb://localhost:27017/
```

Leave it empty to use in-memory storage:
```
MONGODB_URI=
```

### Dashboard Database

The bot stores all messages and activity in a separate dashboard database for monitoring and analytics purposes. This data can be used to build an admin panel or dashboard to monitor conversations in real-time.

Configure the dashboard database with:
```
# Dashboard database settings (for admin monitoring)
DASHBOARD_DB_URI=mongodb://localhost:27017/
DASHBOARD_DB_NAME=instagram_dashboard
```

The dashboard database stores:
- All messages (user and bot)
- Thread metadata (status, last activity)
- API call statistics (success rates, volumes)
- Daily and global usage metrics

### Exponential Backoff

The bot implements exponential backoff to reduce API calls when there are no new messages. This helps avoid rate limiting and reduces resource usage during inactive periods.

The bot will:
- Start with the default check interval (60 seconds by default)
- Increase the wait time exponentially when no messages are found
- Reset the wait time when new messages are detected
- Check pending requests and inbox messages on independent schedules

### Debug Mode

You can enable debug mode to get more detailed logs:
```
DEBUG_MODE=1
```

## Security Notes

- Your Instagram credentials and OpenAI API key are stored in the `.env` file. Keep this file secure.
- The bot creates a session file (`instagram_session.json`) to avoid frequent logins. This file contains sensitive information.
- Consider using a dedicated Instagram account for the bot to minimize risk.

## Limitations

- The bot only processes text messages, not images, videos, or other media types.
- Instagram may temporarily block automated activities if they detect unusual behavior.
- OpenAI API usage will incur costs based on your usage.

## Dashboard Development

The bot already stores the necessary data for building an admin dashboard. To create a dashboard:

1. Use the data in the dashboard database collections:
   - `messages`: All messages with timestamps and user information
   - `threads`: Thread metadata with status and activity information
   - `stats`: Usage statistics and API call metrics

2. Build a web application that connects to the dashboard database and displays:
   - Active conversations
   - Message history
   - User statistics
   - Bot performance metrics

## Disclaimer

This tool is provided for educational purposes only. Use of bots on Instagram may violate their Terms of Service. Use at your own risk.

## License

MIT 