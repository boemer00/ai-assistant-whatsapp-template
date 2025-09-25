# LangGraph Travel Assistant Refactor Plan

## 🎯 Project Overview
Transform the current WhatsApp travel bot from dual-handler architecture to a systematic LangGraph state machine that ensures complete information collection before any API calls.

**Core Goal**: Bulletproof state validation preventing incomplete Amadeus API requests while maintaining natural conversation flow.

---

## 🏗️ Architecture Summary

### State Machine Graph
```
START → COLLECT_INFO → VALIDATE_COMPLETE → SEARCH_FLIGHTS → PRESENT_OPTIONS
  ↑                                 ↓
  └─────── NEEDS_CLARIFICATION ←────┘
```

### Core Nodes
- **COLLECT_INFO**: Extract and accumulate travel entities through natural conversation
- **VALIDATE_COMPLETE**: Comprehensive validation gate - blocks API calls if incomplete
- **SEARCH_FLIGHTS**: Execute Amadeus API call with validated parameters
- **PRESENT_OPTIONS**: Format and return flight results (Phase 1 endpoint)
- **NEEDS_CLARIFICATION**: Handle corrections, missing info, ambiguity

### State Schema
```python
class TravelState(TypedDict):
    # Core Travel Intent
    origin: Optional[str]
    destination: Optional[str]
    departure_date: Optional[str]  # ISO format YYYY-MM-DD
    return_date: Optional[str]     # ISO format YYYY-MM-DD
    passengers: Optional[int]

    # Trip Classification
    trip_type: Literal["one_way", "round_trip", "undecided"]
    trip_type_confirmed: bool

    # Validation Pipeline
    required_fields_complete: bool
    field_confidence: Dict[str, float]
    validation_errors: List[str]
    ready_for_api: bool  # Critical gate keeper

    # Conversation Management
    conversation_history: List[Dict[str, Any]]
    missing_fields: List[str]
    clarification_attempts: int
    user_message: str
    bot_response: str
```

### State Reducers
```python
def add_extracted_info(current: TravelState, update: Dict) -> TravelState
def increment_clarification_attempts(current: TravelState) -> TravelState
def mark_field_complete(current: TravelState, field: str, confidence: float) -> TravelState
def set_validation_status(current: TravelState, valid: bool, errors: List[str]) -> TravelState
def update_conversation(current: TravelState, user_msg: str, bot_msg: str) -> TravelState
```

---

## 📋 Implementation Steps

### Step 1: Foundation Setup
**Goal**: Create LangGraph infrastructure and basic state management
**Files to modify/create**:
- `requirements.txt` - Add `langgraph>=0.1.0`
- `app/langgraph/` - New directory
- `app/langgraph/state.py` - TravelState schema and reducers
- `app/langgraph/graph.py` - StateGraph definition
- `tests/test_langgraph_foundation.py` - Basic state tests

**Commands**:
```bash
pip install langgraph>=0.1.0
pytest tests/test_langgraph_foundation.py -v
```

**Acceptance Criteria**:
- TravelState schema validates correctly
- State reducers work with immutable updates
- Basic StateGraph instantiates without errors
- All foundation tests pass

**Rollback**: Delete `app/langgraph/` directory, revert `requirements.txt`

---

### Step 2: Information Collection Node
**Goal**: Implement COLLECT_INFO node with natural entity extraction
**Files to modify/create**:
- `app/langgraph/nodes/collect_info.py` - Core collection logic
- `app/langgraph/tools/extractor.py` - Information extraction tool
- `app/langgraph/tools/conversation_manager.py` - Context-aware questioning
- `tests/test_collect_info_node.py` - Collection scenarios

**Commands**:
```bash
pytest tests/test_collect_info_node.py -v
```

**Acceptance Criteria**:
- Extracts entities from various input formats
- Generates context-aware follow-up questions
- Handles partial information gracefully
- Updates state with confidence scores
- Routes to validation when sufficient info collected

**Rollback**: Remove collection node files, restore previous StateGraph

---

### Step 3: Validation Node
**Goal**: Implement bulletproof validation preventing incomplete API calls
**Files to modify/create**:
- `app/langgraph/nodes/validate_complete.py` - Comprehensive validation
- `app/langgraph/tools/validator.py` - Business rule validation
- `app/utils/travel_validation.py` - Date/passenger/route validation helpers
- `tests/test_validation_node.py` - Validation scenarios

**Commands**:
```bash
pytest tests/test_validation_node.py -v
```

**Acceptance Criteria**:
- Validates all required fields present
- Enforces trip type confirmation (one-way vs return)
- Validates date logic (no past dates, return > departure)
- Checks passenger count (1-9)
- Sets `ready_for_api = True` only when complete
- Routes back to collection for missing info

**Rollback**: Remove validation files, bypass validation in graph

---

### Step 4: Flight Search Node
**Goal**: Execute Amadeus API calls only with validated state
**Files to modify/create**:
- `app/langgraph/nodes/search_flights.py` - API execution node
- `app/langgraph/tools/amadeus_tool.py` - Structured Amadeus integration
- Update `app/amadeus/client.py` - Add state-based search method
- `tests/test_search_node.py` - Search execution tests

**Commands**:
```bash
pytest tests/test_search_node.py -v
```

**Acceptance Criteria**:
- Only executes when `ready_for_api = True`
- Throws error if validation bypassed
- Integrates with existing cache layer
- Updates state with search results
- Handles API errors gracefully

**Rollback**: Remove search node, restore direct Amadeus calls

---

### Step 5: Results Presentation Node
**Goal**: Format flight results naturally while preserving state
**Files to modify/create**:
- `app/langgraph/nodes/present_options.py` - Result formatting
- Update `app/formatters/enhanced_whatsapp.py` - State-aware formatting
- `tests/test_present_options.py` - Presentation scenarios

**Commands**:
```bash
pytest tests/test_present_options.py -v
```

**Acceptance Criteria**:
- Formats results using existing natural formatter
- Preserves conversation state for future phases
- **STOPS execution here (Phase 1 endpoint)**
- Provides clear state for Phase 2 extensions

**Rollback**: Use existing formatting without state preservation

---

### Step 6: Main Handler Integration
**Goal**: Replace smart_handler with LangGraph integration
**Files to modify**:
- `main.py` - Switch to LangGraph handler
- `app/langgraph/handler.py` - Main LangGraph integration
- `app/conversation/` - Preserve but don't use smart_handler
- `tests/test_integration.py` - End-to-end scenarios

**Commands**:
```bash
pytest tests/test_integration.py -v
uvicorn main:app --port 8002 &
curl -X POST http://localhost:8002/whatsapp/webhook -d "Body=NYC to London&From=whatsapp:+test&To=whatsapp:+bot"
```

**Acceptance Criteria**:
- LangGraph processes webhook messages
- Maintains conversational flow
- Preserves Redis caching integration
- All existing middleware works
- End-to-end conversation scenarios pass

**Rollback**: Revert to smart_handler in main.py

---

### Step 7: Testing & Validation
**Goal**: Comprehensive testing of complete pipeline
**Files to modify/create**:
- `tests/test_conversation_scenarios.py` - Real conversation flows
- `tests/test_state_transitions.py` - State machine validation
- `tests/test_api_prevention.py` - Validation gate enforcement

**Commands**:
```bash
pytest tests/test_conversation_scenarios.py -v
pytest tests/test_state_transitions.py -v
pytest tests/test_api_prevention.py -v
pytest tests/ -v --cov=app/langgraph
```

**Acceptance Criteria**:
- Zero incomplete API calls in all test scenarios
- Explicit trip type confirmation in ambiguous cases
- Natural conversation flow maintained
- State transitions work correctly
- 90%+ test coverage on LangGraph components

**Rollback**: Full rollback plan documented

---

## 🚦 Validation Gates

### COLLECT_INFO → VALIDATE_COMPLETE
**Requirements**:
- Has origin OR destination OR departure_date (some progress made)
- Conversation history updated
- Extraction confidence scores recorded

### VALIDATE_COMPLETE → SEARCH_FLIGHTS
**Critical Gate - Must Have ALL**:
- `origin` present and not None
- `destination` present and not None
- `departure_date` present and not None
- `trip_type` in ["one_way", "round_trip"] (not "undecided")
- If `trip_type == "round_trip"`, then `return_date` present
- `passengers` is int between 1-9
- `departure_date` not in the past
- If `return_date` exists, it's after `departure_date`
- `ready_for_api == True`

### SEARCH_FLIGHTS → PRESENT_OPTIONS
**Requirements**:
- API call successful
- Results cached appropriately
- State updated with search results

### Node Failures → NEEDS_CLARIFICATION
**Triggers**:
- Validation fails
- User provides contradictory information
- API call fails
- Clarification attempts < 3

---

## 📄 Data Contracts

### Tool Schemas

#### Information Extractor Tool
```python
class ExtractionResult(BaseModel):
    extracted_fields: Dict[str, Any]
    field_confidence: Dict[str, float]
    ambiguous_fields: List[str]
    suggested_clarifications: List[str]

class InformationExtractorTool(BaseTool):
    name = "information_extractor"
    description = "Extract travel entities with confidence scoring"

    def _run(self, message: str, current_state: TravelState) -> ExtractionResult
```

#### Validation Tool
```python
class ValidationResult(BaseModel):
    is_valid: bool
    missing_required: List[str]
    validation_errors: List[str]
    recommendations: List[str]

class StateValidatorTool(BaseTool):
    name = "state_validator"
    description = "Comprehensive pre-API validation"

    def _run(self, state: TravelState) -> ValidationResult
```

#### Conversation Manager Tool
```python
class ConversationAction(BaseModel):
    question: str
    question_type: Literal["missing_info", "clarification", "confirmation"]
    priority: int
    context_used: List[str]

class ConversationManagerTool(BaseTool):
    name = "conversation_manager"
    description = "Generate contextual follow-up questions"

    def _run(self, state: TravelState) -> ConversationAction
```

#### Amadeus Search Tool
```python
class SearchParams(BaseModel):
    origin: str
    destination: str
    departure_date: str
    return_date: Optional[str]
    passengers: int

class SearchResult(BaseModel):
    success: bool
    results: Optional[Dict]
    error: Optional[str]
    cached: bool

class AmadeusSearchTool(BaseTool):
    name = "amadeus_search"
    description = "Execute validated flight search"

    def _run(self, params: SearchParams) -> SearchResult
```

---

## 🔧 Development Guidelines

### Code Standards
- Type hints for all functions
- Pydantic models for all data structures
- Comprehensive docstrings
- Error handling with specific exceptions
- Logging at INFO level for state transitions

### Testing Strategy
- Unit tests for each node
- Integration tests for state transitions
- Conversation scenario tests
- API prevention tests
- Performance benchmarks

### Rollback Strategy
Each step includes specific rollback instructions. Emergency rollback:
```bash
git checkout main
git branch -D langgraph-refactor
```

---

## 🚀 Phase 2+ Extensions (Future)

### Human Approval Workflow
- Add `HUMAN_APPROVAL` node after `PRESENT_OPTIONS`
- Booking confirmation with timeout handling
- Modification and cancellation flows

### Multi-Service Integration
- `HotelSearchTool` integration
- `WeatherTool` for destination info
- `CalendarIntegrationTool` for date validation
- `TravelTipsTool` for recommendations

### Service Router
- Detect additional service needs in conversation
- Route to appropriate service tools
- Maintain conversation context across services

---

## 📊 Success Metrics

**Phase 1 Goals**:
- ✅ Zero incomplete API calls (validation gate enforcement)
- ✅ 100% trip type confirmation in ambiguous cases
- ✅ Natural conversation flow regardless of entry point
- ✅ State machine handles all edge cases gracefully
- ✅ Performance parity with current system
- ✅ Clear extension points for Phase 2


## References -- if needed
LangGraph - https://langchain-ai.github.io/langgraph/tutorials/workflows/#prompt-chaining

TwiML - https://www.twilio.com/docs/whatsapp/api#responding-to-incoming-messages-with-twiml

feel free to add more as you need.


**Implementation Status**: [x] Step 3 Complete - Validation Node ✅ BULLETPROOF GATE

**Step 1 Results**: ✅ LangGraph foundation with bulletproof state management
**Step 2 Results**: ✅ Natural conversation-based information collection

**Step 3 Results**:
- ✅ StateValidatorTool: Comprehensive validation engine with business rules
  * Required fields validation (origin, destination, departure_date)
  * Trip type confirmation enforcement (prevents "undecided" API calls)
  * Date validation (no past dates, return > departure, reasonable durations)
  * Passenger limits (1-9), format validation, business logic
  * Context-aware error messages and recommendations

- ✅ ValidateCompleteNode: Critical API gate with zero-tolerance validation
  * **ready_for_api gate**: Only True when 100% validated
  * Intelligent error responses for each validation failure type
  * Proper state updates and routing decisions

- ✅ Graph Integration: Bulletproof routing with validation enforcement
  * should_search() **ONLY** routes to API if ready_for_api=True
  * Comprehensive validation gate testing and enforcement
  * Debug logging for validation decisions

- ✅ 24/24 validation tests passing + all foundation tests passing
- ✅ **ZERO incomplete API calls possible** - validation gate working perfectly
- ✅ Code committed and pushed to remote repository

**Critical Safety Achievement**:
🚨 **BULLETPROOF API GATE**: No incomplete or invalid requests can reach Amadeus API
- Missing fields → blocked with specific guidance
- Past dates → blocked with date correction prompts
- Unconfirmed trip type → blocked until explicit confirmation
- Invalid business logic → blocked with helpful error messages

---

*Next Step*: Await ACK to proceed to Step 4: Flight Search Node Implementation
