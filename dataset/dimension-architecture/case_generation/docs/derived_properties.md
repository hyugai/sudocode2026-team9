# Derived Properties Before Compatibility Validation

The dimension files store primitive facts only. Before applying compatibility rules, the case generator should derive convenience properties.

```text
dimension files
↓
derive properties
↓
compatibility rules
↓
case specification
↓
transcript generation
```

| Derived property | Source |
|---|---|
| `session_count` | `len(journey.sessions)` |
| `cross_channel` | More than one distinct channel/platform in journey sessions |
| `handoff` | Handler changes within or across sessions |
| `requires_prior_state` | Inferred from `difficult_scenario.required_setup` |
| `customer_goal` | Assigned in the concrete case specification |
| `customer_state` | Assigned in the concrete case specification |

The derived values are used for validation and generation logic, but should not be duplicated in the source dimension files.
