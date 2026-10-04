# Memory Architecture (3-Layer Design)

This document describes the 3-layer memory architecture implemented in the Telesales Agent to persist customer facts and interaction histories across multiple sessions, allowing the agent to remember long-term context without requiring the user to repeat information.

## 1. Architecture Overview

The system divides memory into three distinct layers, inspired by human cognitive processes:

1. **Working Memory (M1 - Short-term RAM)**
   - **Scope:** Current conversation turn and active state.
   - **Data:** Recent chat messages, retrieved catalog data, active intents, and dynamically extracted `memory_deltas`.
   - **Storage:** In-memory `ConversationState`.

2. **Episodic Memory (M1 - Long-term Experiences)**
   - **Scope:** Summaries of past conversations and interactions.
   - **Data:** High-level summaries of what happened, products discussed, and outcomes (e.g., "Customer asked about AirPure Y, pending spouse approval").
   - **Storage:** `customer_sessions` table in Supabase PostgreSQL database.

3. **Profile Memory (M1 - Long-term Facts)**
   - **Scope:** Enduring facts about the customer.
   - **Data:** Demographics, preferences, constraints, budget, room size, family status.
   - **Storage:** `attributes` (JSONB) column in the `customers` table in Supabase PostgreSQL database.

## 2. Implementation Flow (LangGraph Pipeline)

Instead of relying on the LLM to manually invoke a `memory.write` tool, the system seamlessly extracts and persists memory through the LangGraph node execution flow.

### A. Initialization & Loading (Start of Session)
- **`node_crm_profile`**: Retrieves the customer's M1 Profile (from the `attributes` JSONB column) via the `CRMRetriever`.
- **`node_precompute_brief`**: Retrieves the customer's M1 Episodic memory (past `customer_sessions`) and aggregates them into the `past_history` state.
- **Result:** The `TurnContext` is hydrated with long-term memory before the agent generates any responses.

### B. Extraction (Turn-by-Turn)
- **`node_perceive`**: The `LLMPerceiver` uses structured output (Pydantic `IntentSchema`) to analyze the customer's utterance. Along with intents and entities, it actively extracts **`memory_deltas`** (new long-term facts, e.g., `{'room_size': 25, 'budget': 5.5}`).
- **Accumulation:** These `memory_deltas` are aggregated in the `ConversationState` throughout the call.

### C. Application (Planning)
- **`node_plan`**: The `LLMPlanner` receives a prompt injected with:
  - The static CRM Profile
  - The Past Episodic History
  - The newly extracted `memory_deltas` (Working Profile)
- **Result:** The LLM makes decisions taking both past history and newly revealed facts into account.

### D. Persistence (End of Session)
- **`node_persist`**: Executed at the end of the graph loop or when the call concludes. The `LLMPersister`:
  1. Compiles the conversation history into a structured summary (Facts, Product Advised, Blocker) via an LLM call.
  2. Saves the summary string as a new row in the `customer_sessions` table (Updating Episodic Memory).
  3. Merges the accumulated `memory_deltas` into the customer's `attributes` JSONB column in the database (Updating Profile Memory).

## 3. Database Schema Updates

To support this architecture, the following database updates were applied:
- Added `attributes` column (`JSONB DEFAULT '{}'`) to the `customers` table to store arbitrary key-value facts (Profile Memory).
- Created `customer_sessions` table (Episodic Memory) linked to `customers.customer_id` with a `summary` text field.

## 4. Key Advantages

1. **Implicit Extraction:** The LLM does not need to choose to write to memory via explicit tool calls. The perceiver guarantees continuous extraction of profile facts implicitly.
2. **Reduced Token Usage:** Instead of injecting full chat histories of previous sessions into the prompt, the planner only sees compressed high-level summaries and synthesized facts.
3. **No Hallucination in Schema:** By isolating the update logic to a JSONB dictionary update in Python (Supabase client), we avoid the risk of the LLM hallucinating SQL or messing up DB schema constraints.
