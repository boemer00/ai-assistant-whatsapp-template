from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import Optional
from app.utils.dates import to_iso_date

class IntentSchema(BaseModel):
    origin: Optional[str] = Field(None, description="City or airport (string)")
    destination: Optional[str] = None
    departure_date: Optional[str] = Field(None, description="YYYY-MM-DD or natural language")
    return_date: Optional[str] = None
    passengers: Optional[int] = 1

SYSTEM = """You extract structured flight intents from a single user message.
For dates:
- If given as specific dates (e.g., "19 November", "2024-11-19"), extract them
- If given as relative dates (e.g., "next Friday", "tomorrow"), convert to YYYY-MM-DD format
- Today's date for reference: {today}
Passengers default to 1 if not given.
Output concise JSON ONLY with keys: origin, destination, departure_date, return_date, passengers.
"""

USER = """Message: {text}"""

def extract_intent(llm: ChatOpenAI, text: str) -> IntentSchema:
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM), ("user", USER)]
    )
    msg = prompt.format_messages(text=text, today=today)
    res = llm.invoke(msg)
    print(f"[DEBUG] LLM response: {res.content}")
    # simple safety: parse JSON
    import json
    try:
        content = res.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        data = json.loads(content)
        print(f"[DEBUG] Parsed JSON: {data}")
    except Exception as e:
        print(f"[DEBUG] JSON parse error: {e}")
        data = {}
    # normalise dates -> iso here
    if "departure_date" in data and data["departure_date"]:
        original_date = data["departure_date"]
        data["departure_date"] = to_iso_date(data["departure_date"])
        print(f"[DEBUG] Date conversion: '{original_date}' -> '{data['departure_date']}'")
    if "return_date" in data and data["return_date"]:
        original_date = data["return_date"]
        data["return_date"] = to_iso_date(data["return_date"])
        print(f"[DEBUG] Return date conversion: '{original_date}' -> '{data['return_date']}'")
    # fill defaults
    data.setdefault("passengers", 1)
    return IntentSchema(**data)
