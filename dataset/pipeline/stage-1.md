# Stage 1: Populate World-State & Journey Blueprints

## 1. Objective
Generate multi-session customer journey blueprints (`blueprints.jsonl`) and their linked customer registry (`customers.json`). The blueprints contain facts, session goals, and expected actions for transcript generation.

## Run on Kaggle

1. Upload [the Stage 1 input ZIP](./stage-1/input/stage-1-kaggle-input.zip) as a private Kaggle dataset. Kaggle extracts the files and preserves their folders. [Kaggle datasets](https://www.kaggle.com/docs/datasets)
2. Import [generate.ipynb](./stage-1/generate.ipynb) as a private Kaggle notebook. Attach the input dataset with **Add Input**. The three cells run on CPU with Internet disabled. The default `TIER = "M1"` uses the organizer CRM. Set `TIER = "M2"` for synthetic M2. [Kaggle notebooks](https://www.kaggle.com/docs/notebooks)
3. Choose **Save & Run All**. Download `blueprints.jsonl` and `customers.json` from the notebook’s `output/` folder. The M1 run generates 140 journeys and 300 planned sessions for 50 customers and preserves the organizer’s original contact values.

## 2. Inputs (Read-Only Organizer Ground Truth)
The organizer bundles are stored in [`btc/`](./btc/). Treat them as read-only. Stage 1 reads the local copies under `stage-1/input/`. The `catalog/` directory holds `products.json`, `promotions.json`, `inventory_timeline.json`, `crm_seed.json`, and `public-delivery-addresses.json`. The `simulator/` directory holds `personas.json`, and `eval/` holds the updated `mock_tools.py`. The Kaggle input ZIP contains these seven files and puts `generate.py` and `common.py` together in `stage-1/src/`.
- [`btc/BTC-Data-Vong1-TEAMS/catalog/products.json`](./btc/BTC-Data-Vong1-TEAMS/catalog/products.json) (valid SKUs, specs, base prices)
- [`btc/BTC-Data-Vong1-TEAMS/catalog/promotions.json`](./btc/BTC-Data-Vong1-TEAMS/catalog/promotions.json) (promo codes, expiry dates, eligibility rules)
- [`btc/BTC-Data-Vong1-TEAMS/catalog/inventory_timeline.json`](./btc/BTC-Data-Vong1-TEAMS/catalog/inventory_timeline.json) (stock availability by date)
- [`btc/BTC-Data-Vong1-TEAMS/catalog/crm_seed.json`](./btc/BTC-Data-Vong1-TEAMS/catalog/crm_seed.json) supplies customer identities for the standalone CRM seed registry. Use the [CRM seed report](./reports/crm_seed_report.md) to check field coverage, existing order and session history, and shared-phone and same-name cases before assigning customer identities or channels.
- [`btc/BTC-Data-Vong1-TEAMS/policy/`](./btc/BTC-Data-Vong1-TEAMS/policy/) (valid policies vs. trap files `*-HET-HIEU-LUC.md` and `*-NOI-BO.md`)
- [`btc/BTC-Data-Vong1-TEAMS/simulator/personas.json`](./btc/BTC-Data-Vong1-TEAMS/simulator/personas.json) (official customer persona definitions)
- [`btc/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md`](./btc/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md) & [public samples SAMPLE-01 through SAMPLE-07](./btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/)
- [`btc/BTC-cap-nhat-11-2026/eval/mock_tools.py`](./btc/BTC-cap-nhat-11-2026/eval/mock_tools.py) supplies the updated tool logic. The current update bundle has no catalog, so its tools read the base bundle’s catalog. Synthetic customers start with empty CRM history.

## 3. Dataset Volume & Distribution Targets (`--tier M1` vs. `--tier M2`)

| Journey Archetype | `--tier M1` Blueprints ($\rightarrow$ Sessions) | `--tier M2` Blueprints ($\rightarrow$ Sessions) |
| :--- | :--- | :--- |
| **Standard 2-Session Journeys** (`call_1` $\rightarrow$ `call_2`) | `78` ($\rightarrow$ `156`) | `57` ($\rightarrow$ `114`) |
| **Omnichannel Journeys** (`facebook`/`zalo` $\leftrightarrow$ `hotline`) | `32` ($\rightarrow$ `64`) | `35` ($\rightarrow$ `70`) |
| **Hard Edge-Case 2-Session Journeys** (expired promo, OOS, policy trap, `chuyen_may`) | `14` ($\rightarrow$ `28`) | `18` ($\rightarrow$ `36`) |
| **Extended 3-Session Journeys** (`call_1` $\rightarrow$ `call_2` $\rightarrow$ `call_3`) | `16` ($\rightarrow$ `48`) | `20` ($\rightarrow$ `60`) |
| **TOTAL** | **`140` blueprints ($\rightarrow$ `296` sessions)** | **`130` blueprints ($\rightarrow$ `280` sessions)** |

## 4. Step-by-Step Implementation Instructions

### Step 4.1: Build the Customer Registry (`customers.json`)

For synthetic tier runs:

1. Generate `140` unique customer profiles (`CUST-001` to `CUST-140`) for a fresh `M1` batch, or `130` profiles (`CUST-001` to `CUST-130`) for `M2`.
2. Assign each profile a fictional phone using the non-dialable `000-000-0042` pattern and a fictional delivery address such as “căn 42, lô A, khu giao nhận mô phỏng Sao Mai.” Also assign omnichannel handles (`fb_id`, `zalo_id`), a regional dialect tag (`North`, `Central`, `South`), and a persona from `personas.json`. The organizer CRM seed provides regions for its own customers and has no structured per-customer address field.

#### Standalone organizer CRM registry

From the pipeline directory, run:

```bash
python stage-1/src/generate.py --tier M1 --identity-source crm-seed
```

Stage 1 reads the organizer seed and writes `customers.json` under `stage-1/runs/crm_seed/run-<tier>-YYYYMMDD-HHMM/`. Each row retains its source identity, available contact fields, and shared-phone metadata. Missing contact fields keep their source values. This standalone registry stays outside the Stage 2 input path.

The [public delivery address catalog](./stage-1/input/catalog/public-delivery-addresses.json) contains 50 distinct primary addresses and 50 distinct alternatives from official directories of public offices and service centers. Stage 1 assigns each customer a pair from their CRM region and records the catalog reference ID. Customers who share a phone receive distinct addresses. The six address-change journeys use the assigned alternate and mark the original as superseded.

#### CRM-backed M1 blueprint run

```bash
python stage-1/src/generate.py --tier M1 --identity-source crm-seed --publish
```

This run creates 140 journeys and 300 planned sessions for all 50 organizer customers. Each customer has two or three independent variants that reuse their source contact details and assigned delivery address. Each journey uses isolated mock order state and receives a consecutive `SC-XXX` ID.

| Primary journey pattern | Journeys |
| --- | ---: |
| Consider and decide | 34 |
| Continue across channels | 27 |
| Return after a price or stock change | 26 |
| Return for post-purchase support | 30 |
| Resume with uncertain identity or history | 12 |
| Transfer with context | 11 |

Each blueprint records one organizer `persona` and one primary `journey_pattern`. Channel changes and hard cases are recorded separately, so a shared-phone case can also exercise channel continuity. The three required M1 personas have 24 consults-family, 30 price-comparer, and 32 exchange-or-complaint journeys. [Stage 1 coverage report](./reports/m1-stage1-report.md)

The archived run and its copy under `output/` contain these files:

| File | CRM-backed schema |
| --- | --- |
| `customers.json` | JSON array with `customer_id`, `name`, `honorific`, `phone`, `fb_id`, `zalo_id`, `region`, `shared_phone_with`, `address`, `alternate_address`, `address_reference_id`, and `dialect`. `fb_id`, `zalo_id`, and `shared_phone_with` may be `null`. The journey carries its own persona. |
| `blueprints.jsonl` | One journey per line, with `scenario_id`, `customer_id`, `persona`, `journey_pattern`, and two or three sessions. Each session includes a `session_purpose`, channel, customer goal, dated facts, memory rules where applicable, and a tool or behavior assertion. |

The current Stage 2 address formatter expects the fictional address format from the preceding publication. The Kaggle Stage 1 output with public addresses requires a Stage 2 handoff update. Stage 3’s custom journey privacy check flags organizer contact numbers in generated records. Any evaluation split of this run must keep all variants of a customer together and keep customers who share a phone number in the same split.

### Step 4.2: Construct Journey Blueprints (`blueprints.jsonl`)
For each journey:
1. **Verify Ground Truth via `mock_tools.py` / Catalog:** Query actual SKUs, prices, and promo expiration dates for `call_1.date`, `call_2.date`, and `call_3.date`. Never invent SKUs or prices outside `products.json`.
2. **Track Multi-Value Entities (`entities_multi`):** Whenever multiple SKUs or prices are compared in a session, store both in chronological order as a list (`"product_advised": ["SKU-AP-Y", "SKU-AP-X"]`) and list the field name in `"entities_multi"`.
3. **Define Cross-Session Evaluation Rules (`call_2` & `call_3`):**
   - `must_carry_over`: Keys from prior sessions' `facts_established` that the agent must remember.
   - `must_not_ask`: Slots already answered in prior sessions (penalizes Repeat-Question Rate if asked again).
   - `success_if`: Exact tool assertion (`tool_called`: `"order.create"`, `"order.update"`, `"schedule.callback"`, `"handoff.transfer"`, or `null`) and `args_match`.
   - `expected_outcome`: One of `"chot_don"`, `"hen_goi_lai"`, `"tu_choi"`, or `"chuyen_may"`.
4. **M2 3-Session State Mutations (`call_3`):** In the published three-session journeys, `call_2` creates the order and `call_3` calls `order.update` with `action: update_address`. The revised destination uses lô B at the same fictional delivery site. The follow-up uses the official `khach_goi_lan_3_het_kien_nhan` persona.
5. **M2 Simulator Profile (`simulator_profile`):** When `--tier M2` is active, attach a `simulator_profile` object (`persona_system_prompt`, `hidden_goal`, `patience_level`, `patience_max_turns`, `patience_by_session`) to each blueprint so the M2 LLM Customer Simulator can dynamically roleplay the customer during evaluation.

### Step 4.3: Preventive Structural Deduplication & Publication
1. Maintain a seen-set of `(customer_id, target_sku, edge_case_type, channel_transition)`. If a collision occurs, deterministically swap the SKU, channel transition, or persona before writing.
2. Validate the generated data and print the journey and session counts. The tier is stored in each blueprint.
3. To publish the selected full run, pass `--publish` to the generator. Stage 1 copies the finished run into `output/` after validation. Runs without `--publish` are archived under `runs/`.

## 5. Synthetic Blueprint Schema Example (`blueprints.jsonl`)
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
- **Synthetic M2:** $\ge 130$ blueprints totaling $\ge 250$ sessions ($\ge 60$ multi-session with $\ge 20$ three-session journeys, $\ge 30$ omnichannel, $\ge 15$ hard edge cases, and `simulator_profile` populated).
- **CRM-backed M1:** 140 blueprints totaling 300 sessions, including 20 three-session journeys. All 50 organizer customer IDs are represented, all six patterns and 12 personas meet their planned allocations, and each journey exercises its primary pattern.
- All SKUs, prices, and promo dates match [`btc/BTC-Data-Vong1-TEAMS/catalog/`](./btc/BTC-Data-Vong1-TEAMS/catalog/).
