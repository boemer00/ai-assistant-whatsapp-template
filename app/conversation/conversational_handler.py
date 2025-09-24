"""
Natural Conversational Handler

Replaces the travel-obsessed smart_handler with a natural conversation engine
that can chat about anything and naturally offer travel assistance when appropriate.
"""

import re
from typing import Dict, List, Optional, Any
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from app.session.redis_store import RedisSessionStore
from app.amadeus.client import AmadeusClient
from app.user.preferences import UserPreferenceManager


class ConversationalHandler:
    """Natural conversation handler that replicates Claude/ChatGPT conversation quality"""

    def __init__(
        self,
        session_store: RedisSessionStore,
        llm: ChatOpenAI,
        amadeus_client: AmadeusClient = None,
        user_preferences: UserPreferenceManager = None,
        iata_db=None
    ):
        self.session_store = session_store
        self.amadeus_client = amadeus_client
        self.user_preferences = user_preferences
        self.iata_db = iata_db

        # Create conversational LLM with natural temperature
        self.llm_conversational = ChatOpenAI(
            model=llm.model_name,
            temperature=0.7,  # Natural conversation, not robotic
            api_key=llm.openai_api_key
        )

    def handle_message(self, user_id: str, message: str) -> str:
        """Main conversation handler - natural and context-aware"""
        print(f"[DEBUG] ConversationalHandler.handle_message() called with user_id={user_id}, message='{message}'")

        # Get or create session with conversation history
        session = self.session_store.get(user_id) or {
            "history": [],
            "preferences": {},
            "user_context": {}
        }

        # Extract user context for personalization
        user_context = self._extract_user_context(session)

        # Format conversation history for context
        conversation_history = self._format_conversation_history(session["history"])

        # Create natural conversation prompt
        prompt = self._build_conversation_prompt(conversation_history, user_context)

        try:
            # Get natural response from LLM
            response = self.llm_conversational.invoke(
                prompt.format_messages(message=message)
            )

            response_text = response.content.strip()

            # Check if we should invoke travel assistance
            if self._should_invoke_travel_assistant(message, response_text, session):
                # Integrate travel assistance naturally
                response_text = self._integrate_travel_assistance(
                    user_id, message, session, response_text
                )

            # Save conversation turn
            self._save_conversation_turn(user_id, session, message, response_text)

            print(f"[DEBUG] Returning natural response: {response_text}")
            return response_text

        except Exception as e:
            print(f"[ERROR] Conversation error: {type(e).__name__}: {str(e)}")
            # Graceful fallback
            return "I'm having a moment of confusion! Could you try saying that again?"

    def _build_conversation_prompt(self, conversation_history: str, user_context: Dict) -> ChatPromptTemplate:
        """Build the conversational system prompt"""

        system_prompt = """You are Alex, a helpful and friendly WhatsApp assistant. You excel at natural conversation and can also help with travel planning when needed.

CORE PERSONALITY:
- Warm, conversational, and genuinely interested in helping
- Remember conversation context and build meaningful connections
- Ask thoughtful follow-up questions that show you're listening
- Natural and authentic - never robotic or overly formal
- Appropriately curious about the user's life and interests
- Use a conversational tone that feels like chatting with a friend

CONVERSATION PRINCIPLES:
- Respond contextually based on our conversation history
- Show genuine interest in what the user shares
- Ask natural follow-up questions when appropriate
- Remember personal details they've shared (name, interests, etc.)
- Build on previous conversations naturally
- Only mention travel capabilities when relevant to the conversation
- Keep responses concise but warm (1-3 sentences usually)

TRAVEL ASSISTANCE (when appropriate):
- If users express interest in travel, naturally offer help
- Ask clarifying questions conversationally: "Oh, where are you thinking of going?"
- Remember their travel preferences for future conversations
- Help search for flights when they're ready to plan
- Make travel planning feel like a helpful conversation, not a transaction

CURRENT CONTEXT:
- User's name: {user_name}
- Key preferences: {user_preferences}
- Recent topics: {recent_topics}
- Today's date: {current_date}

CONVERSATION HISTORY:
{conversation_history}

Respond naturally and helpfully to the user's message. Show that you remember our conversation and care about what they're sharing."""

        formatted_system = system_prompt.format(
            user_name=user_context.get("user_name", "friend"),
            user_preferences=user_context.get("user_preferences", "None yet"),
            recent_topics=user_context.get("recent_topics", "Just getting to know each other"),
            current_date=user_context.get("current_date", ""),
            conversation_history=conversation_history
        )

        return ChatPromptTemplate.from_messages([
            ("system", formatted_system),
            ("user", "{message}")
        ])

    def _format_conversation_history(self, history: List[Dict], max_turns: int = 8) -> str:
        """Format recent conversation history for context injection"""
        if not history:
            return "This is the start of your conversation with this user."

        # Keep recent turns within token budget
        recent_history = history[-max_turns*2:]  # User + Assistant pairs

        if not recent_history:
            return "This is the start of your conversation with this user."

        formatted = []
        for entry in recent_history:
            role = "User" if entry["role"] == "user" else "You (Alex)"
            content = entry["content"]
            formatted.append(f"{role}: {content}")

        return "\n".join(formatted)

    def _extract_user_context(self, session: Dict) -> Dict:
        """Extract key user information for context personalization"""
        preferences = session.get("preferences", {})
        user_context = session.get("user_context", {})

        return {
            "user_name": user_context.get("name") or preferences.get("name", "friend"),
            "user_preferences": self._summarize_preferences(preferences),
            "recent_topics": self._extract_recent_topics(session.get("history", [])),
            "current_date": datetime.now().strftime("%B %d, %Y")
        }

    def _summarize_preferences(self, preferences: Dict) -> str:
        """Summarize user preferences concisely"""
        if not preferences:
            return "Getting to know them"

        prefs = []
        if preferences.get("frequent_routes"):
            routes = list(preferences["frequent_routes"].keys())[:2]
            prefs.append(f"travels {', '.join(routes)}")

        if preferences.get("budget_conscious"):
            prefs.append("budget-conscious")
        elif preferences.get("budget_conscious") == False:
            prefs.append("values convenience over cost")

        return "; ".join(prefs) if prefs else "Getting to know their preferences"

    def _extract_recent_topics(self, history: List[Dict]) -> str:
        """Extract recent conversation topics"""
        if not history:
            return "Just starting to chat"

        # Look at recent messages for context
        recent_messages = [h["content"] for h in history[-4:] if h["role"] == "user"]

        if not recent_messages:
            return "Just starting to chat"

        # Simple topic extraction
        topics = []
        for msg in recent_messages:
            msg_lower = msg.lower()
            if any(word in msg_lower for word in ["travel", "trip", "flight", "vacation"]):
                topics.append("travel")
            elif any(word in msg_lower for word in ["work", "job", "office"]):
                topics.append("work")
            elif any(word in msg_lower for word in ["weather", "day", "weekend"]):
                topics.append("daily life")

        return ", ".join(set(topics)) if topics else "general conversation"

    def _should_invoke_travel_assistant(self, user_message: str, ai_response: str, session: Dict) -> bool:
        """Detect when user wants travel assistance"""
        # Check for explicit travel requests
        travel_keywords = [
            "flight", "flights", "fly", "book flight", "search flights",
            "travel", "trip", "vacation", "holiday", "airport", "airline"
        ]

        user_msg_lower = user_message.lower()
        has_travel_intent = any(keyword in user_msg_lower for keyword in travel_keywords)

        # Check if AI response suggests offering travel help
        ai_response_lower = ai_response.lower()
        ai_offered_travel = any(phrase in ai_response_lower for phrase in [
            "search for flights", "help with travel", "help you find flights",
            "plan your trip", "book flights"
        ])

        print(f"[DEBUG] Travel detection - user_intent: {has_travel_intent}, ai_offered: {ai_offered_travel}")

        return has_travel_intent or ai_offered_travel

    def _integrate_travel_assistance(self, user_id: str, message: str, session: Dict, ai_response: str) -> str:
        """Integrate travel assistance naturally into conversation"""
        print(f"[DEBUG] Integrating travel assistance for message: '{message}'")

        # For now, return the natural response and let future iterations handle travel
        # This keeps the conversation natural while we build out travel integration
        travel_note = "\n\n(Travel assistance coming soon - I can chat naturally for now! 🛫)"

        return ai_response + travel_note

    def _save_conversation_turn(self, user_id: str, session: Dict, user_message: str, ai_response: str):
        """Save conversation turn to session history"""
        # Add user message
        session["history"].append({
            "role": "user",
            "content": user_message,
            "timestamp": datetime.now().isoformat()
        })

        # Add AI response
        session["history"].append({
            "role": "assistant",
            "content": ai_response,
            "timestamp": datetime.now().isoformat()
        })

        # Trim history to manage token usage (keep last 20 turns = 10 exchanges)
        if len(session["history"]) > 20:
            session["history"] = session["history"][-20:]

        # Extract user name if mentioned
        self._extract_user_name(user_message, session)

        # Save session
        self.session_store.set(user_id, session)
        print(f"[DEBUG] Saved conversation turn to session")

    def _extract_user_name(self, message: str, session: Dict):
        """Extract user name from conversation"""
        # Simple name extraction from patterns like "I'm John" or "My name is Mary"
        name_patterns = [
            r"i'?m ([A-Z][a-z]+)",
            r"my name is ([A-Z][a-z]+)",
            r"call me ([A-Z][a-z]+)"
        ]

        for pattern in name_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                name = match.group(1).capitalize()
                session.setdefault("user_context", {})["name"] = name
                print(f"[DEBUG] Extracted user name: {name}")
                break