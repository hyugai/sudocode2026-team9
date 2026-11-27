# Stage 1 M2 blueprint report

## Directory structure

The tree shows the files used by the M2 run. Bold filenames mark project-created files and outputs.

- stage-1/
  - **`generate.ipynb`**
  - **`stage1-m2-input.zip`**
  - input/
    - catalog/
      - crm_seed.json
      - inventory_timeline.json
      - products.json
      - promotions.json
      - **`public-delivery-addresses.json`**
    - eval/
      - mock_tools.py
    - simulator/
      - personas.json
  - output/
    - **`blueprints.jsonl`** (M1 reference)
  - runs/run-M2-20261126-1622/
    - **`blueprints.jsonl`**
    - **`customers.json`**
  - src/
    - **`common.py`**
    - **`generate.py`**

### BTC files

| File | Purpose |
| --- | --- |
| [crm_seed.json](../stage-1/input/catalog/crm_seed.json) | Supplies the 50 customer IDs, contact fields, and regions used by both tiers. |
| [inventory_timeline.json](../stage-1/input/catalog/inventory_timeline.json) | Supplies dated stock changes and restocks. |
| [products.json](../stage-1/input/catalog/products.json) | Supplies SKUs, variants, and base prices. |
| [promotions.json](../stage-1/input/catalog/promotions.json) | Supplies promotion dates and eligibility. |
| [mock_tools.py](../stage-1/input/eval/mock_tools.py) | Applies BTC tool rules for quotes, inventory, orders, and callbacks. |
| [personas.json](../stage-1/input/simulator/personas.json) | Defines the persona prompts and patience by session. |

### Project files and outputs

| File | Purpose |
| --- | --- |
| [generate.ipynb](../stage-1/generate.ipynb) | Runs Stage 1 on Kaggle with `TIER = "M2"`. |
| [stage1-m2-input.zip](../stage-1/stage1-m2-input.zip) | Bundles the inputs, helpers, and M1 reference as `stage-1/input/m1-blueprints.jsonl`. |
| [public-delivery-addresses.json](../stage-1/input/catalog/public-delivery-addresses.json) | Supplies one primary and one alternate public venue per customer, matched by region. |
| [M1 blueprints.jsonl](../stage-1/output/blueprints.jsonl) | Supplies the 140 blueprints used for the cross-tier duplicate check. |
| [src/common.py](../stage-1/src/common.py) | Defines shared filenames and run-path helpers. |
| [src/generate.py](../stage-1/src/generate.py) | Assigns customers to cases, builds session facts, and checks the output. |
| [M2 blueprints.jsonl](../stage-1/runs/run-M2-20261126-1622/blueprints.jsonl) | Stores the 150 planned journeys, including one simulator profile per journey. |
| [M2 customers.json](../stage-1/runs/run-M2-20261126-1622/customers.json) | Stores the 50 BTC profiles with their assigned venues. |

## M2 output

The default run assigns **three journeys to each of the 50 BTC customers**. It produces **150 blueprints and 330 planned sessions**, with 120 two-session journeys and 30 three-session journeys. The roster covers 15 northern, 18 central, and 17 southern customers. The 330 sessions comprise 286 hotline, 23 Zalo, and 21 Facebook sessions.

The generator compared every accepted candidate with the 140 M1 blueprints by target SKU, ordered channels and actions, basket contents, and selected state changes. No accepted blueprint matched M1 under that rule. M2 IDs run from `SC-141` through `SC-290`.

| Coverage measure | Stage 1 result |
| --- | ---: |
| Customers with at least two hotline calls in one journey | 50 |
| Distinct customers with a three-session journey | 30 |
| Distinct customers with a hotline and chat journey | 33 |
| Hard cases | 59 |

The accepted roster leaves a **10-customer gap** against the M2 minimum of 60 distinct multi-session customers. Stage 3 still enforces that minimum. Counts in this report describe Stage 1 blueprints before transcript validation. [M2 thresholds](../AGENTS.md)

## Persona × journey pattern

Each blueprint contributes to one of **19 pairings**, covering all 12 personas and six primary patterns. The 30 three-session journeys all fall under post-purchase support. Twenty belong to the exchange-or-complaint persona and ten to the customer who loses patience on the third call.

| Persona | Consider and decide | Cross-channel | Price or stock | Post-purchase | Identity or history | Handoff | Blueprints | Sessions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Consults family | 12 | 7 | 6 | 0 | 0 | 0 | 25 | 50 |
| Compares prices | 12 | 8 | 11 | 0 | 0 | 0 | 31 | 62 |
| Returns for exchange or complaint | 0 | 5 | 4 | 22 | 2 | 0 | 33 | 86 |
| Asks many questions | 4 | 0 | 0 | 0 | 0 | 0 | 4 | 8 |
| Loses patience on the third call | 0 | 0 | 0 | 10 | 0 | 0 | 10 | 30 |
| Switches between chat and hotline | 0 | 11 | 0 | 0 | 0 | 0 | 11 | 22 |
| Accepts an out-of-scope transfer | 0 | 0 | 0 | 0 | 0 | 9 | 9 | 18 |
| Asks outside the shop's documentation | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 4 |
| Challenges conflicting quotes | 0 | 9 | 0 | 0 | 0 | 0 | 9 | 18 |
| Shares a phone number | 0 | 0 | 0 | 0 | 4 | 0 | 4 | 8 |
| Returns after eight months | 0 | 0 | 0 | 0 | 6 | 0 | 6 | 12 |
| Shops for several items | 0 | 0 | 6 | 0 | 0 | 0 | 6 | 12 |
| **Total** | **30** | **40** | **27** | **32** | **12** | **9** | **150** | **330** |

Forty journeys have cross-channel continuity as their primary pattern. Four shared-phone journeys also use multiple channels. Together they cover all 33 customers with a chat identity.

## Output samples

The excerpts show how `customer_id` links `SC-265` to `C046`. The third session updates the delivery destination to the customer's alternate venue.

### `customers.json`

```json
[
  {
    "customer_id": "C046",
    "region": "nam",
    "dialect": "South",
    "address": "Khu vực Thới Mỹ, phường Thới Long, Cần Thơ",
    "alternate_address": "Thới Thuận, phường Phước Thới, Cần Thơ",
    "address_reference_id": "VENUE-049"
  }
]
```

### `blueprints.jsonl`

This excerpt is formatted on multiple lines for readability.

```json
{
  "scenario_id": "SC-265",
  "tier": "M2",
  "customer_id": "C046",
  "persona": "khach_goi_lan_3_het_kien_nhan",
  "journey_pattern": "return_for_post_purchase_support",
  "target_sku": "SKU-WF-RO10",
  "call_1": {
    "channel": "hotline",
    "date": "2026-11-04",
    "session_purpose": "inquiry",
    "expected_outcome": "hen_goi_lai",
    "success_if": {"tool_called": "schedule.callback"}
  },
  "call_2": {
    "channel": "hotline",
    "date": "2026-11-05",
    "session_purpose": "purchase",
    "expected_outcome": "chot_don",
    "success_if": {
      "tool_called": "order.create",
      "args_match": {"sku": "SKU-WF-RO10", "price_vnd": 6890000}
    }
  },
  "call_3": {
    "channel": "hotline",
    "date": "2026-11-06",
    "session_purpose": "address_update",
    "expected_outcome": "chot_don",
    "facts_established": {"delivery_address": "Thới Thuận, phường Phước Thới, Cần Thơ"},
    "success_if": {
      "tool_called": "order.update",
      "args_match": {"action": "update_address"}
    }
  },
  "simulator_profile": {
    "patience_by_session": {"call_1": 3, "call_2": 2, "call_3": 1}
  }
}
```
