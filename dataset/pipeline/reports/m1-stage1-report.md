# Stage 1 M1 blueprint report

## Directory structure

Bold filenames mark project-created files and generated outputs. The remaining files are copies from the BTC bundles.

- stage-1/
  - **`generate.ipynb`**
  - **`stage1-m1-input.zip`**
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
    - m1/
      - **`blueprints.jsonl`**
      - **`customers.json`**
  - src/
    - **`blueprint_duplicates.py`**
    - **`common.py`**
    - **`generate.py`**

### BTC files

| File | Source | Purpose |
| --- | --- | --- |
| [input/catalog/crm_seed.json](../stage-1/input/catalog/crm_seed.json) | BTC base | Supplies the 35 Central and Southern profiles used in M1. |
| [input/catalog/inventory_timeline.json](../stage-1/input/catalog/inventory_timeline.json) | BTC base | Provides dated stock changes and restocks. |
| [input/catalog/products.json](../stage-1/input/catalog/products.json) | BTC base | Provides product SKUs, variants, and prices. |
| [input/catalog/promotions.json](../stage-1/input/catalog/promotions.json) | BTC base | Provides promotion dates and eligibility rules. |
| [input/eval/mock_tools.py](../stage-1/input/eval/mock_tools.py) | BTC November update | Supplies reference logic for prices, inventory, orders, and other tool results. |
| [input/simulator/personas.json](../stage-1/input/simulator/personas.json) | BTC base | Defines customer behavior, speaking style, and patience. |

### Project files and outputs

| File | Purpose |
| --- | --- |
| [generate.ipynb](../stage-1/generate.ipynb) | Main Kaggle entry point. Loads inputs, generates and validates M1, and saves both outputs. |
| [stage1-m1-input.zip](../stage-1/stage1-m1-input.zip) | Contains the input files, Python helpers, and two pinned blueprint batches used for duplicate checks. |
| [input/catalog/public-delivery-addresses.json](../stage-1/input/catalog/public-delivery-addresses.json) | Provides 50 region-matched pairs of public delivery locations and their sources. |
| [output/m1/blueprints.jsonl](../stage-1/output/m1/blueprints.jsonl) | Stores one blueprint per line with a persona, primary conversation pattern, session facts, and expected actions. |
| [output/m1/customers.json](../stage-1/output/m1/customers.json) | Stores CRM identities and assigned delivery addresses. Blueprints join to this registry by `customer_id`. |
| [src/blueprint_duplicates.py](../stage-1/src/blueprint_duplicates.py) | Compares structural signatures across both M1 and M2. |
| [src/common.py](../stage-1/src/common.py) | Supplies shared filenames and path helpers. |
| [src/generate.py](../stage-1/src/generate.py) | Builds and validates the customer registry and blueprints. |

## M1 output

The run contains **180 blueprints and 388 planned sessions for 35 customers**. Of those blueprints, 152 have two sessions and 28 have three. It assigns 90 blueprints to each region using 18 Central and 17 Southern BTC profiles. The sole industry is fashion, with 45 variant SKUs from six parent products. The run includes 82 flagged edge cases. [Blueprints](../stage-1/output/m1/blueprints.jsonl) · [Catalog](../stage-1/input/catalog/products.json)

The registry uses 70 distinct public venue addresses, one primary and one alternate per customer. Five blueprints change the delivery address to the assigned alternate. [Customer registry](../stage-1/output/m1/customers.json) · [Public venues](../stage-1/input/catalog/public-delivery-addresses.json)

All 35 customers have a blueprint with at least two hotline calls. Of those customers, 33 have four qualifying blueprints and two have three. Losing any 21 blueprints preserves at least 30 qualifying customers. Each of the 21 chat-eligible customers also has two omnichannel blueprints. [Allocation rules](../stage-1.md#crm-backed-m1-blueprint-run)

All 180 structural signatures are unique within the batch. The comparison found zero matches against the 290 pinned M1 and M2 reference blueprints in the Stage 1 input bundle. [Input bundle](../stage-1/stage1-m1-input.zip) · [Signature code](../stage-1/src/blueprint_duplicates.py)

## Persona and journey pattern

**Persona** describes how the customer behaves, such as consulting family or comparing prices. The output uses all 12 BTC personas. The three required M1 personas highlighted below cover 96 blueprints.

**Journey pattern** describes what the interaction must test across sessions. The six patterns cover a purchase decision after deliberation, continuity across channels, a price or stock change, post-purchase support, uncertain identity or history, and handoff with context.

Each blueprint contributes to one cell. The 180 blueprints cover 35 persona × pattern pairings, with both regions represented in every populated cell.

| Persona | Consider and decide | Cross-channel | Price or stock | Post-purchase | Identity or history | Handoff | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Consults family** | 13 | 5 | 7 | 3 | 0 | 0 | **28** |
| **Compares prices** | 10 | 5 | 9 | 2 | 0 | 3 | **29** |
| **Returns for exchange or complaint** | 3 | 5 | 5 | 19 | 5 | 2 | **39** |
| Asks many questions | 3 | 4 | 2 | 2 | 0 | 0 | 11 |
| Loses patience on the third call | 0 | 0 | 2 | 10 | 2 | 2 | 16 |
| Moves between chat and hotline | 0 | 12 | 0 | 0 | 0 | 0 | 12 |
| Accepts an out-of-scope transfer | 0 | 0 | 0 | 0 | 0 | 7 | 7 |
| Asks outside the shop’s documentation | 2 | 5 | 0 | 0 | 0 | 2 | 9 |
| Challenges conflicting quotes | 0 | 6 | 0 | 0 | 0 | 0 | 6 |
| Shares a phone number | 0 | 0 | 0 | 0 | 2 | 0 | 2 |
| Returns after eight months | 0 | 0 | 2 | 3 | 10 | 0 | 15 |
| Shops for several items | 0 | 0 | 4 | 2 | 0 | 0 | 6 |
| **Total** | **31** | **42** | **31** | **41** | **19** | **16** | **180** |

## Output samples

These excerpts show how `customer_id` links blueprint `SC-136` to customer `C022`. The first session is an inquiry. The second places an order for the primary address, and the third checks that `order.update` changes delivery to the alternate address.

### `customers.json`

```json
[
  {
    "customer_id": "C022",
    "region": "nam",
    "dialect": "South",
    "address": "A8 Châu Thới, phường Hòa Hưng, TP. Hồ Chí Minh",
    "alternate_address": "210–212 Âu Dương Lân, phường Chánh Hưng, TP. Hồ Chí Minh",
    "address_reference_id": "VENUE-042"
  }
]
```

### `blueprints.jsonl`

The file stores one journey per line. This excerpt is formatted across multiple lines for readability.

```json
{
  "scenario_id": "SC-136",
  "tier": "M1",
  "customer_id": "C022",
  "persona": "khach_goi_lan_3_het_kien_nhan",
  "journey_pattern": "return_for_post_purchase_support",
  "target_sku": "SKU-JK-WND-S-DEN",
  "call_1": {
    "channel": "hotline",
    "date": "2026-10-24",
    "session_purpose": "inquiry",
    "expected_outcome": "hen_goi_lai"
  },
  "call_2": {
    "channel": "hotline",
    "date": "2026-10-25",
    "session_purpose": "purchase",
    "expected_outcome": "chot_don",
    "facts_established": {
      "delivery_address": "A8 Châu Thới, phường Hòa Hưng, TP. Hồ Chí Minh"
    }
  },
  "call_3": {
    "channel": "hotline",
    "date": "2026-10-26",
    "session_purpose": "address_update",
    "expected_outcome": "chot_don",
    "facts_established": {
      "delivery_address": "210–212 Âu Dương Lân, phường Chánh Hưng, TP. Hồ Chí Minh"
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
