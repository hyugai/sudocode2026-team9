# Stage 1 M1 blueprint report

## Directory structure

Bold filenames mark project-created files and generated outputs. The remaining files are copies from the BTC bundles.

- stage-1/
  - **`generate.ipynb`**
  - **`stage-1-kaggle-input.zip`**
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
    - **`blueprints.jsonl`**
    - **`customers.json`**
  - src/
    - **`common.py`**
    - **`generate.py`**

### BTC files

| File | Source | Purpose |
| --- | --- | --- |
| [input/catalog/crm_seed.json](../stage-1/input/catalog/crm_seed.json) | BTC base | Supplies the 50 customer identities, contact fields, and regions. |
| [input/catalog/inventory_timeline.json](../stage-1/input/catalog/inventory_timeline.json) | BTC base | Provides dated stock changes and restocks. |
| [input/catalog/products.json](../stage-1/input/catalog/products.json) | BTC base | Provides product SKUs, variants, and prices. |
| [input/catalog/promotions.json](../stage-1/input/catalog/promotions.json) | BTC base | Provides promotion dates and eligibility rules. |
| [input/eval/mock_tools.py](../stage-1/input/eval/mock_tools.py) | BTC November update | Supplies reference logic for prices, inventory, orders, and other tool results. |
| [input/simulator/personas.json](../stage-1/input/simulator/personas.json) | BTC base | Defines customer behavior, speaking style, and patience. |

### Project files and outputs

| File | Purpose |
| --- | --- |
| [generate.ipynb](../stage-1/generate.ipynb) | Main Kaggle entry point. Loads inputs, generates and validates M1, and saves both outputs. |
| [stage-1-kaggle-input.zip](../stage-1/stage-1-kaggle-input.zip) | Upload bundle containing the input files and both Python helpers. |
| [input/catalog/public-delivery-addresses.json](../stage-1/input/catalog/public-delivery-addresses.json) | Provides 50 region-matched pairs of public delivery locations and their sources. |
| [output/blueprints.jsonl](../stage-1/output/blueprints.jsonl) | Stores one journey per line with a persona, primary journey pattern, session facts, and expected actions. |
| [output/customers.json](../stage-1/output/customers.json) | Stores CRM identities and assigned delivery addresses. Blueprints join to this registry by `customer_id`. |
| [src/common.py](../stage-1/src/common.py) | Supplies shared filenames and path helpers. |
| [src/generate.py](../stage-1/src/generate.py) | Builds and validates the customer registry and blueprints. |

## M1 output

The current output contains **140 journeys and 300 planned sessions for 50 customers**. Of those journeys, 120 have two sessions and 20 have three. Forty customers appear in three separate journeys and ten appear in two. The generator reproduced the records from the current inputs and preserved the original CRM contact values.

The registry uses 100 distinct public venue addresses, one primary and one alternate per customer. North has 15 customers across Hà Nội and Hải Phòng. Central has 18 across Đà Nẵng, Huế, and Đắk Lắk. South has 17 across TP. Hồ Chí Minh and Cần Thơ. Six journeys change the delivery address to the assigned alternate.

## Persona and journey pattern

**Persona** describes how the customer behaves, such as consulting family or comparing prices. The output uses all 12 BTC personas. The three M1 personas highlighted below cover 86 journeys.

**Journey pattern** describes what the interaction must test across sessions. The six patterns cover a purchase decision after deliberation, continuity across channels, a price or stock change, post-purchase support, uncertain identity or history, and handoff with context.

Each blueprint contributes to one cell. The 140 journeys cover 19 persona–pattern pairings.

| Persona | Consider and decide | Cross-channel | Price or stock | Post-purchase | Identity or history | Handoff | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Consults family** | 14 | 4 | 6 | 0 | 0 | 0 | **24** |
| **Compares prices** | 14 | 5 | 11 | 0 | 0 | 0 | **30** |
| **Returns for exchange or complaint** | 0 | 3 | 3 | 24 | 2 | 0 | **32** |
| Asks many questions | 4 | 0 | 0 | 0 | 0 | 0 | 4 |
| Loses patience on the third call | 0 | 0 | 0 | 6 | 0 | 0 | 6 |
| Moves between chat and hotline | 0 | 9 | 0 | 0 | 0 | 0 | 9 |
| Accepts an out-of-scope transfer | 0 | 0 | 0 | 0 | 0 | 11 | 11 |
| Asks outside the shop’s documentation | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| Challenges conflicting quotes | 0 | 6 | 0 | 0 | 0 | 0 | 6 |
| Shares a phone number | 0 | 0 | 0 | 0 | 4 | 0 | 4 |
| Returns after eight months | 0 | 0 | 0 | 0 | 6 | 0 | 6 |
| Shops for several items | 0 | 0 | 6 | 0 | 0 | 0 | 6 |
| **Total** | **34** | **27** | **26** | **30** | **12** | **11** | **140** |

## Output samples

These excerpts show how `customer_id` links blueprint `SC-109` to customer `C002`. The first session places an order for the primary address. The second checks that `order.update` changes delivery to the alternate address.

### `customers.json`

```json
[
  {
    "customer_id": "C002",
    "region": "nam",
    "dialect": "South",
    "address": "58B Nguyễn Đình Chiểu, phường Tân Định, TP. Hồ Chí Minh",
    "alternate_address": "45–47 Lê Duẩn, phường Sài Gòn, TP. Hồ Chí Minh",
    "address_reference_id": "VENUE-034"
  }
]
```

### `blueprints.jsonl`

The file stores one journey per line. This excerpt is formatted across multiple lines for readability.

```json
{
  "scenario_id": "SC-109",
  "tier": "M1",
  "customer_id": "C002",
  "persona": "khach_da_mua_doi_size",
  "journey_pattern": "return_for_post_purchase_support",
  "call_1": {
    "channel": "hotline",
    "date": "2026-10-18",
    "session_purpose": "purchase",
    "expected_outcome": "chot_don",
    "facts_established": {
      "delivery_address": "58B Nguyễn Đình Chiểu, phường Tân Định, TP. Hồ Chí Minh"
    }
  },
  "call_2": {
    "channel": "hotline",
    "date": "2026-10-19",
    "session_purpose": "address_update",
    "expected_outcome": "chot_don",
    "facts_established": {
      "delivery_address": "45–47 Lê Duẩn, phường Sài Gòn, TP. Hồ Chí Minh"
    },
    "success_if": {
      "tool_called": "order.update",
      "args_match": {
        "action": "update_address"
      }
    }
  }
}
```
