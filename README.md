# WhatsApp Travel Assistant

A LangGraph-powered WhatsApp bot that helps users search and book flights through natural conversation.

## Prerequisites

- Python 3.12+
- Redis server
- Twilio account with WhatsApp sandbox
- Amadeus API credentials
- OpenAI API key
- ngrok (for local development)

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file in the project root:

```env
# OpenAI
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini

# Amadeus
AMADEUS_CLIENT_ID=your_amadeus_client_id
AMADEUS_CLIENT_SECRET=your_amadeus_client_secret
AMADEUS_BASE_URL=https://test.api.amadeus.com

# Twilio
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

# Redis
REDIS_URL=redis://localhost:6379
```

### 3. Start Redis

```bash
redis-server
```

### 4. Run the Application

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

The server will start at `http://localhost:8001`

## Local Development with WhatsApp

### 1. Set up ngrok

Install ngrok and expose your local server:

```bash
ngrok http 8001
```

Copy the HTTPS forwarding URL (e.g., `https://abc123.ngrok.io`)

### 2. Configure Twilio WhatsApp Sandbox

1. Go to [Twilio Console](https://console.twilio.com) → Messaging → Try it out → Send a WhatsApp message
2. Follow instructions to join your sandbox (send join message to the sandbox number)
3. In sandbox settings, set the webhook URL:
   - **When a message comes in**: `https://your-ngrok-url.ngrok.io/whatsapp/webhook`
   - **Method**: HTTP POST

### 3. Test the Bot

Send a WhatsApp message to your Twilio sandbox number:
- "Hi" - Start a conversation
- "I need a flight from NYC to London on December 15th for 2 people"
- "Show me one-way flights"

## API Endpoints

- `GET /` - Service info and status
- `GET /health` - Health check
- `POST /whatsapp/webhook` - WhatsApp webhook endpoint
- `GET /admin/user/{user_id}/conversation` - View user conversation state
- `POST /admin/user/{user_id}/reset` - Reset user conversation
- `GET /metrics` - Service metrics

## Architecture

The bot uses LangGraph for conversation management with:
- **Systematic information collection** - Guided conversation flow
- **Validation gates** - Ensures all required info before API calls
- **Redis session persistence** - Maintains conversation state
- **Natural language understanding** - Powered by OpenAI GPT-4
- **Real-time flight search** - Via Amadeus API

## Testing

Run tests:

```bash
pytest tests/
```

Run integration tests only:

```bash
pytest tests/test_basic_integration.py tests/test_conversation_scenarios.py -v
```

## Troubleshooting

- **Redis connection error**: Ensure Redis is running (`redis-cli ping`)
- **Ngrok timeout**: Restart ngrok and update Twilio webhook URL
- **API rate limits**: Check Amadeus API quota and upgrade if needed
- **WhatsApp not responding**: Verify Twilio sandbox is active and webhook URL is correct

## License

MIT
