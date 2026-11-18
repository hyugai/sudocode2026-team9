# Stage 1: Populate World-State & Journey Blueprints

## 1. Objective
Generate deterministic multi-session customer journey blueprints (`stage1_blueprints.jsonl`) and a linked customer identity registry (`stage1_customers.json`) inside `runs/run_<tier>_YYYYMMDD_HHMM/` according to `--tier M1 | M2`, then atomically promote `latest -> runs/run_<tier>_YYYYMMDD_HHMM/`. Each blueprint acts as a ground-truth contract containing **zero dialogue text yet**.

## 2. Inputs (Read-Only Organizer Ground Truth)
The organizer bundles are stored in [`btc_data/`](./btc_data/). Treat them as read-only.
- [`btc_data/BTC-Data-Vong1-TEAMS/catalog/products.json`](./btc_data/BTC-Data-Vong1-TEAMS/catalog/products.json) (valid SKUs, specs, base prices)
- [`btc_data/BTC-Data-Vong1-TEAMS/catalog/promotions.json`](./btc_data/BTC-Data-Vong1-TEAMS/catalog/promotions.json) (promo codes, expiry dates, eligibility rules)
- [`btc_data/BTC-Data-Vong1-TEAMS/catalog/inventory_timeline.json`](./btc_data/BTC-Data-Vong1-TEAMS/catalog/inventory_timeline.json) (stock availability by date)
- [`btc_data/BTC-Data-Vong1-TEAMS/policy/`](./btc_data/BTC-Data-Vong1-TEAMS/policy/) (valid policies vs. trap files `*-HET-HIEU-LUC.md` and `*-NOI-BO.md`)
- [`btc_data/BTC-Data-Vong1-TEAMS/simulator/personas.json`](./btc_data/BTC-Data-Vong1-TEAMS/simulator/personas.json) (official customer persona definitions)
- [`btc_data/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md`](./btc_data/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md) & [public samples SAMPLE-01 through SAMPLE-07](./btc_data/BTC-Data-Vong1-TEAMS/test_set/public_sample/)
- [`btc_data/BTC-cap-nhat-11-2026/eval/mock_tools.py`](./btc_data/BTC-cap-nhat-11-2026/eval/mock_tools.py) supplies the updated tool logic. The current update bundle has no catalog, so its tools read the base bundle’s catalog. Synthetic customers start with empty CRM history.

## 3. Dataset Volume & Distribution Targets (`--tier M1` vs. `--tier M2`)

| Journey Archetype | `--tier M1` Blueprints ($\rightarrow$ Sessions) | `--tier M2` Blueprints ($\rightarrow$ Sessions) |
| :--- | :--- | :--- |
| **Standard 2-Session Journeys** (`call_1` $\rightarrow$ `call_2`) | `78` ($\rightarrow$ `156`) | `57` ($\rightarrow$ `114`) |
| **Omnichannel Journeys** (`facebook`/`zalo` $\leftrightarrow$ `hotline`) | `32` ($\rightarrow$ `64`) | `35` ($\rightarrow$ `70`) |
| **Hard Edge-Case 2-Session Journeys** (expired promo, OOS, policy trap, `chuyen_may`) | `14` ($\rightarrow$ `28`) | `18` ($\rightarrow$ `36`) |
| **Extended 3-Session Journeys** (`call_1` $\rightarrow$ `call_2` $\rightarrow$ `call_3`) | `16` ($\rightarrow$ `48`) | `20` ($\rightarrow$ `60`) |
| **TOTAL** | **`140` blueprints ($\rightarrow$ `296` sessions)** | **`130` blueprints ($\rightarrow$ `280` sessions)** |

## 4. Step-by-Step Implementation Instructions

### Step 4.1: Build Synthetic Customer Registry (`stage1_customers.json`)
1. Generate `140` unique customer profiles (`CUST-001` to `CUST-140`) for a fresh `M1` batch, or `130` profiles (`CUST-001` to `CUST-130`) for `M2`.
2. Assign each profile a fictional phone using the non-dialable `000-000-0042` pattern, a fictional test ID such as `TEST-ID-042`, and a fictional delivery address such as “căn 42, lô A, khu giao nhận mô phỏng Sao Mai.” Also assign omnichannel handles (`fb_id`, `zalo_id`), a regional dialect tag (`North`, `Central`, `South`), and a persona from `personas.json`. The organizer CRM seed provides regions for its own customers and has no structured per-customer address field.

### Step 4.2: Construct Journey Blueprints (`stage1_blueprints.jsonl`)
For each journey (`TEAM-SC-001` to `TEAM-SC-140` for a fresh M1 batch; up to `TEAM-SC-130` for M2):
1. **Verify Ground Truth via `mock_tools.py` / Catalog:** Query actual SKUs, prices, and promo expiration dates for `call_1.date`, `call_2.date`, and `call_3.date`. Never invent SKUs or prices outside `products.json`.
2. **Track Multi-Value Entities (`entities_multi`):** Whenever multiple SKUs or prices are compared in a session, store both in chronological order as a list (`"product_advised": ["SKU-AP-Y", "SKU-AP-X"]`) and list the field name in `"entities_multi"`.
3. **Define Cross-Session Evaluation Rules (`call_2` & `call_3`):**
   - `must_carry_over`: Keys from prior sessions' `facts_established` that the agent must remember.
   - `must_not_ask`: Slots already answered in prior sessions (penalizes Repeat-Question Rate if asked again).
   - `success_if`: Exact tool assertion (`tool_called`: `"order.create"`, `"order.update"`, `"schedule.callback"`, `"handoff.transfer"`, or `null`) and `args_match`.
   - `expected_outcome`: One of `"chot_don"`, `"hen_goi_lai"`, `"tu_choi"`, or `"chuyen_may"`.
4. **M2 3-Session State Mutations (`call_3`):** In the published three-session journeys, `call_2` creates the order and `call_3` calls `order.update` with `action: update_address`. The revised destination uses lô B at the same fictional delivery site. The follow-up uses the official `khach_goi_lan_3_het_kien_nhan` persona.
5. **M2 Simulator Profile (`simulator_profile`):** When `--tier M2` is active, attach a `simulator_profile` object (`persona_system_prompt`, `hidden_goal`, `patience_level`, `patience_max_turns`, `patience_by_session`) to each blueprint so the M2 LLM Customer Simulator can dynamically roleplay the customer during evaluation.

### Step 4.3: Preventive Structural Deduplication & Atomic Promotion
1. Maintain a seen-set of `(customer_id, target_sku, edge_case_type, channel_transition)`. If a collision occurs, deterministically swap the SKU, channel transition, or persona before writing.
2. Write `manifest.json` recording `tier`, random seed, total blueprint count, total planned session count, and timestamp.
3. Atomically update relative symlink `latest -> runs/run_<tier>_YYYYMMDD_HHMM/`.

## 5. Output Schema Example (`stage1_blueprints.jsonl`)
```json
{
  "scenario_id": "TEAM-SC-014",
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
- **M1:** $\ge 120$ blueprints totaling $\ge 120$ sessions ($\ge 30$ multi-session, $\ge 10$ omnichannel, $\ge 5$ hard edge cases).
- **M2:** $\ge 130$ blueprints totaling $\ge 250$ sessions ($\ge 60$ multi-session with $\ge 20$ three-session journeys, $\ge 30$ omnichannel, $\ge 15$ hard edge cases, and `simulator_profile` populated).
- All SKUs, prices, and promo dates match [`btc_data/BTC-Data-Vong1-TEAMS/catalog/`](./btc_data/BTC-Data-Vong1-TEAMS/catalog/).
