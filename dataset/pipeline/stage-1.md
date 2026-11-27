# Stage 1: Populate World-State & Journey Blueprints

## 1. Objective
Generate multi-session customer journey blueprints (`blueprints.jsonl`) and their linked customer registry (`customers.json`). The blueprints contain facts, session goals, and expected actions for transcript generation.

## Run on Kaggle

1. Upload the extracted [M1 input ZIP](./stage-1/stage1-m1-input.zip) or [M2 input ZIP](./stage-1/stage1-m2-input.zip) as a private Kaggle dataset, preserving the directory structure. [Kaggle datasets](https://www.kaggle.com/docs/datasets)
2. Import [generate.ipynb](./stage-1/generate.ipynb), attach the matching dataset with **Add Input**, and set `TIER` to `"M1"` or `"M2"`. Both runs use the organizer CRM and run on CPU with Internet disabled. `BLUEPRINT_COUNT = None` generates 180 blueprints for the selected tier. Set a specific count of at least 175 for M1 or 150 for M2 to override it. [Kaggle notebooks](https://www.kaggle.com/docs/notebooks)
3. Choose **Save & Run All**. Download `blueprints.jsonl` and `customers.json` from `/kaggle/working/output/`.

## 2. Inputs (Read-Only Organizer Ground Truth)
The organizer bundles are stored in [`btc/`](./btc/). Treat them as read-only. Stage 1 reads the local copies under `stage-1/input/`. The `catalog/` directory holds `products.json`, `promotions.json`, `inventory_timeline.json`, `crm_seed.json`, and `public-delivery-addresses.json`. The `simulator/` directory holds `personas.json`, and `eval/` holds the updated `mock_tools.py`. Both input ZIPs include these files and the Python helpers.

Both ZIPs store their pinned references under `stage-1/input/duplicate-references/`. The M1 ZIP contains the two historical batches used to check for duplicates. The M2 ZIP contains `m1-blueprints.jsonl`, which supplies the duplicate references and starting scenario number. With `M1_BLUEPRINTS = None`, the M2 notebook automatically uses this file. Set `M1_BLUEPRINTS` to use a different M1 run.
- [`btc/BTC-Data-Vong1-TEAMS/catalog/products.json`](./btc/BTC-Data-Vong1-TEAMS/catalog/products.json) (valid SKUs, specs, base prices)
- [`btc/BTC-Data-Vong1-TEAMS/catalog/promotions.json`](./btc/BTC-Data-Vong1-TEAMS/catalog/promotions.json) (promo codes, expiry dates, eligibility rules)
- [`btc/BTC-Data-Vong1-TEAMS/catalog/inventory_timeline.json`](./btc/BTC-Data-Vong1-TEAMS/catalog/inventory_timeline.json) (stock availability by date)
- [`btc/BTC-Data-Vong1-TEAMS/catalog/crm_seed.json`](./btc/BTC-Data-Vong1-TEAMS/catalog/crm_seed.json) supplies customer identities for the standalone CRM seed registry. Use the [CRM seed report](./reports/crm_seed_report.md) to check field coverage, existing order and session history, and shared-phone and same-name cases before assigning customer identities or channels.
- [`btc/BTC-Data-Vong1-TEAMS/policy/`](./btc/BTC-Data-Vong1-TEAMS/policy/) (valid policies vs. trap files `*-HET-HIEU-LUC.md` and `*-NOI-BO.md`)
- [`btc/BTC-Data-Vong1-TEAMS/simulator/personas.json`](./btc/BTC-Data-Vong1-TEAMS/simulator/personas.json) (official customer persona definitions)
- [`btc/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md`](./btc/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md) & [public samples SAMPLE-01 through SAMPLE-07](./btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/)
- [`btc/BTC-cap-nhat-11-2026/eval/mock_tools.py`](./btc/BTC-cap-nhat-11-2026/eval/mock_tools.py) supplies the updated tool logic. The current update bundle has no catalog, so its tools read the base bundle’s catalog. Synthetic customers start with empty CRM history.

## 3. Dataset Volume & Distribution Targets (`--tier M1` vs. `--tier M2`)

| Default run | Customers | Two-session journeys | Three-session journeys | Blueprints | Sessions |
| --- | ---: | ---: | ---: | ---: | ---: |
| CRM-backed M1 | 35 | 152 | 28 | 180 | 388 |
| CRM-backed M2 | 50 | 150 | 30 | 180 | 390 |
| Synthetic M1 CLI mode | 140 | 124 | 16 | 140 | 296 |

## 4. Step-by-Step Implementation Instructions

### Step 4.1: Build the Customer Registry (`customers.json`)

For legacy synthetic M1 CLI runs, pass `--tier M1 --identity-source synthetic`.

1. Generate 140 unique customer profiles (`CUST-001` to `CUST-140`).
2. Assign each profile a fictional phone using the non-dialable `000-000-0042` pattern and a fictional delivery address such as “căn 42, lô A, khu giao nhận mô phỏng Sao Mai.” Also assign omnichannel handles (`fb_id`, `zalo_id`), a regional dialect tag (`North`, `Central`, `South`), and a persona from `personas.json`. The organizer CRM seed provides regions for its own customers and has no structured per-customer address field.

#### Standalone organizer CRM registry

From the pipeline directory, run:

```bash
python stage-1/src/generate.py --tier M1 --identity-source crm-seed
```

Stage 1 reads the organizer seed and writes `customers.json` under `stage-1/runs/crm_seed/run-<tier>-YYYYMMDD-HHMM/`. Each row retains its source identity, available contact fields, and shared-phone metadata. Missing contact fields keep their source values. This standalone registry stays outside the Stage 2 input path.

The [public delivery address catalog](./stage-1/input/catalog/public-delivery-addresses.json) contains 50 distinct primary addresses and 50 distinct alternatives from official directories of public offices and service centers. Stage 1 assigns each customer a pair from their CRM region and records the catalog reference ID. Customers who share a phone receive distinct addresses. Address-change blueprints use the assigned alternate and mark the original as superseded.

#### CRM-backed M1 blueprint run

```bash
python3 stage-1/src/generate.py --tier M1
```

The default run archives 180 blueprints with 388 planned sessions under `stage-1/runs/m1-YYYYMMDD-vN/`. The date uses the local timezone, and the version starts at `v1` each day. It allocates 90 blueprints to each region using 18 Central and 17 Southern BTC profiles. Fashion is the sole industry and the run uses 45 official variant SKUs. Each blueprint uses isolated mock order state and receives a consecutive `SC-XXX` ID. Use `--blueprint-count` to override the batch size. [175-blueprint base allocation](./reports/m1-regeneration-plan.md)

Of the 180 blueprints, 138 contain at least two hotline calls and 42 cover hotline and chat. The generator gives four qualifying blueprints to 33 customers and three to the other two. Dropping below 30 qualifying customers would require losing every qualifying blueprint for six customers, which takes at least 22 removals. The default therefore tolerates any 21 blueprint rejections or drops. Verify the 30-customer requirement against retained blueprints after transcript validation and deduplication.

| Primary journey pattern | Journeys |
| --- | ---: |
| Consider and decide | 31 |
| Continue across channels | 42 |
| Return after a price or stock change | 31 |
| Return for post-purchase support | 41 |
| Resume with uncertain identity or history | 19 |
| Transfer with context | 16 |

Each blueprint records one organizer `persona` and one primary `journey_pattern`. The default run covers all 12 personas and 35 pairings, with both regions represented in every populated cell. The three required M1 personas have 28 consults-family, 29 price-comparer, and 39 exchange-or-complaint blueprints. [M1 base matrix](./reports/m1-regeneration-plan.md#persona-and-conversation-pattern-matrix)

The archived run and its copy under `output/` contain these files:

| File | CRM-backed schema |
| --- | --- |
| `customers.json` | JSON array with `customer_id`, `name`, `honorific`, `phone`, `fb_id`, `zalo_id`, `region`, `shared_phone_with`, `address`, `alternate_address`, `address_reference_id`, and `dialect`. `fb_id`, `zalo_id`, and `shared_phone_with` may be `null`. The journey carries its own persona. |
| `blueprints.jsonl` | One journey per line, with `scenario_id`, `customer_id`, `persona`, `journey_pattern`, and two or three sessions. Each session includes a `session_purpose`, channel, customer goal, dated facts, memory rules where applicable, and a tool or behavior assertion. |

#### CRM-backed M2 blueprint run

```bash
python3 stage-1/src/generate.py --tier M2
```

The CLI archives both output files in `stage-1/runs/run-M2-YYYYMMDD-HHMM/`. The default run adds 180 M2 blueprints across all 50 BTC profiles, with 390 planned sessions. It adds five two-session cases to each pattern in the 150-blueprint base allocation. [M2 base allocation](./reports/m2-stage1-report.md)

Together, the M1 and M2 defaults plan 360 candidate blueprints. The cumulative M2 release target is measured in retained transcripts after validation and deduplication.

Use `--blueprint-count` to override the batch size and `--m1-blueprints` to select a specific M1 JSONL reference. Use matching `blueprints.jsonl` and `customers.json` from one run for the Stage 2 handoff.

### Step 4.2: Construct Journey Blueprints (`blueprints.jsonl`)
For each journey:
1. **Verify Ground Truth via `mock_tools.py` / Catalog:** Query actual SKUs, prices, and promo expiration dates for `call_1.date`, `call_2.date`, and `call_3.date`. Never invent SKUs or prices outside `products.json`.
2. **Track Multi-Value Entities (`entities_multi`):** Whenever multiple SKUs or prices are compared in a session, store both in chronological order as a list (`"product_advised": ["SKU-AP-Y", "SKU-AP-X"]`) and list the field name in `"entities_multi"`.
3. **Define Cross-Session Evaluation Rules (`call_2` & `call_3`):**
   - `must_carry_over`: Keys from prior sessions' `facts_established` that the agent must remember.
   - `must_not_ask`: Slots already answered in prior sessions (penalizes Repeat-Question Rate if asked again).
   - `success_if`: Exact tool assertion (`tool_called`: `"order.create"`, `"order.update"`, `"schedule.callback"`, `"handoff.transfer"`, or `null`) and `args_match`.
   - `expected_outcome`: One of `"chot_don"`, `"hen_goi_lai"`, `"tu_choi"`, or `"chuyen_may"`.
4. **M2 Three-Session Journeys.** The customer first consults the agent, then places an order, then requests a size exchange, checks order status, or updates the delivery address to the assigned alternate venue.
5. **M2 Simulator Profile (`simulator_profile`):** When `--tier M2` is active, attach a `simulator_profile` object (`persona_system_prompt`, `hidden_goal`, `patience_level`, `patience_max_turns`, `patience_by_session`) to each blueprint so the M2 LLM Customer Simulator can dynamically roleplay the customer during evaluation.

### Step 4.3: Preventive Structural Deduplication & Publication
1. Both tiers use [the structural duplicate checker](./stage-1/src/blueprint_duplicates.py). It compares the target SKU, ordered channels, expected outcomes, tool actions, basket contents, and selected state changes.
2. M1 checks candidates against the published batch, saved runs in both naming formats, and bundled reference files. It also checks candidates against earlier blueprints in the same batch. Use repeatable `--duplicate-reference PATH` options to pin an exact reference set for reproducing an archived run. A duplicate candidate is retried within its planned slot.
3. M2 checks the selected M1 reference and assigns scenario IDs after its highest ID. The notebook defaults to the M1 reference in the M2 bundle.
4. Validate the generated data and print the blueprint and session counts. The tier is stored in each blueprint.
5. To publish the selected Stage 1 run, pass `--publish` to the generator. Stage 1 copies the finished run into `output/` after validation. Retained transcripts and verified audio are checked at dataset release.

## 5. Earlier Synthetic Blueprint Schema Example (`blueprints.jsonl`)

See the [M2 Stage 1 report](./reports/m2-stage1-report.md) for an example from the current BTC-backed generator.
```json
{
  "scenario_id": "SC-014",
  "tier": "M2",
  "customer_id": "CUST-042",
  "persona": "khach_do_du_hoi_nguoi_nha",
  "edge_case_type": "omnichannel_switch_and_valid_quote",
  "customer_phone": "000-000-0042",
  "customer_identities": {
    "phone": "000-000-0042",
    "fb_id": "fb_minhhoa_92",
    "zalo_id": "zalo_8841209"
  },
  "simulator_profile": {
    "persona_system_prompt": "Bạn là chị Hoa, cẩn thận, hay hỏi ý kiến chồng trước khi chốt đơn trên 4 triệu. Trả lời ngắn gọn, tự nhiên như người Việt nói chuyện điện thoại.",
    "hidden_goal": "Chốt đơn máy lọc không khí AirPure X giá 4.890.000đ kèm quà tặng bộ lọc nếu nhân viên nhớ đúng tư vấn cũ.",
    "patience_level": 4,
    "patience_max_turns": 4,
    "patience_by_session": {"call_1": 4, "call_2": 3}
  },
  "call_1": {
    "session_index": 1,
    "channel": "facebook",
    "date": "2026-03-14",
    "customer_goal": "Hỏi máy lọc không khí cho phòng ngủ 25m2 có trẻ nhỏ, ngân sách khoảng 5 triệu",
    "facts_established": {
      "room_area_m2": 25,
      "has_children": true,
      "budget_vnd": 5000000,
      "product_advised": ["SKU-AP-Y", "SKU-AP-X"],
      "price_quoted_vnd": [5200000, 4890000],
      "promo_code": "GIFT-FILTER",
      "promo_expiry": "2026-03-16",
      "blocker": "can hoi chong"
    },
    "entities_multi": ["product_advised", "price_quoted_vnd"],
    "expected_outcome": "hen_goi_lai"
  },
  "call_2": {
    "session_index": 2,
    "channel": "hotline",
    "days_later": 2,
    "date": "2026-03-16",
    "customer_goal": "Gọi lại hotline chốt đơn mẫu AirPure X vì đã trao đổi xong với chồng",
    "must_carry_over": ["product_advised", "price_quoted_vnd", "room_area_m2", "blocker"],
    "must_not_ask": ["room_area_m2", "budget_vnd", "has_children", "product_advised"],
    "success_if": {
      "tool_called": "order.create",
      "args_match": {
        "sku": "SKU-AP-X",
        "price_vnd": 4890000
      }
    },
    "ground_truth_facts": {
      "price_vnd": 4890000,
      "promo_active": true,
      "in_stock": true,
      "delivery_days": 2
    },
    "expected_outcome": "chot_don"
  }
}
```

## 6. Exit Criteria
- **Synthetic M1:** $\ge 120$ blueprints totaling $\ge 120$ sessions ($\ge 30$ multi-session, $\ge 10$ omnichannel, $\ge 5$ hard edge cases).
- **CRM-backed M2:** At the default count, 180 additional blueprints with 390 planned sessions across all 50 BTC profiles. Every blueprint includes `simulator_profile` and passes the M1 comparison rule.
- **CRM-backed M1:** At the default count, 180 blueprints with 388 sessions, including 28 three-session blueprints. Coverage includes 35 Central and Southern customers, 21 omnichannel customers, 45 fashion variant SKUs, and all 12 personas. Structural duplicates are excluded.
- All SKUs, prices, and promo dates match [`btc/BTC-Data-Vong1-TEAMS/catalog/`](./btc/BTC-Data-Vong1-TEAMS/catalog/).
