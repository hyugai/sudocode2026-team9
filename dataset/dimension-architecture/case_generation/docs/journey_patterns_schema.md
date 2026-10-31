# `journey_patterns.jsonl` — Key Explanation

## Purpose

`journey_patterns.jsonl` defines the **structure of the customer journey** used to generate synthetic cases. It stores the ordered sessions, communication channels/platforms, handler sequence, and relative timing.

Only primitive journey structure is stored. Summary properties such as session count, cross-channel status, and handoff status are intentionally derived in code before compatibility validation.

## General format

```json
{
  "journey_pattern_id": "",
  "name": "",
  "description": "",
  "sessions": [
    {
      "session_number": 0,
      "channel": "",
      "platform": "",
      "handler_sequence": [],
      "time_offset_from_previous": ""
    }
  ]
}
```

## Keys

| Key | Why it is needed |
|---|---|
| `journey_pattern_id` | Lets generated cases and compatibility rules reference the journey structure reliably. |
| `name` | Provides a stable machine-readable name for sampling, filtering, and generation. |
| `description` | Gives a concise explanation of the interaction flow. |
| `sessions` | Defines the complete ordered structure of the customer journey. |
| `sessions[].session_number` | Determines the exact order of sessions. |
| `sessions[].channel` | Defines the general interaction mode, such as voice or chat. |
| `sessions[].platform` | Defines the specific communication platform, such as phone, Facebook, or Zalo. |
| `sessions[].handler_sequence` | Defines who handles the session and allows handler transitions such as AI → human. |
| `sessions[].time_offset_from_previous` | Indicates when the session occurs relative to the previous one. |

### Derived before compatibility checking

```text
session_count
= number of items in sessions

cross_channel
= more than one distinct channel or platform appears in sessions

handoff
= handler changes within a session or between consecutive sessions
```

These values should be calculated by the generator rather than duplicated in the JSONL source.
