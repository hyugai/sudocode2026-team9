# Stage 2: Generate Multi-Turn Text Transcripts

## 1. Objective
Read blueprints via the relative input symlink (`input_blueprints/stage1_blueprints.jsonl` and `input_blueprints/stage1_customers.json`), generate realistic Vietnamese customer utterances (`customer_turns: list[str]`) per session into `runs/run_<tier>_YYYYMMDD_HHMM/raw_scenarios.jsonl`, and atomically promote `latest -> runs/run_<tier>_YYYYMMDD_HHMM/`.

## 2. Schema Alignment Note (CRITICAL)
Per the organizer schema and seven public samples, one complete journey produces one transcript, with each session storing customer utterances as `customer_turns: list[str]`. The harness can replay those turns or use them as an outline for an M2 live customer simulator. Preserve the Stage 1 `simulator_profile`. The BTC reference evaluator scores traces supplied by the harness.

## 3. Inputs
- `input_blueprints/stage1_blueprints.jsonl` (symlinked to `../stage_1_blueprints/latest/stage1_blueprints.jsonl`)
- `input_blueprints/stage1_customers.json` (symlinked to `../stage_1_blueprints/latest/stage1_customers.json`)
- Organizer product and promotion catalogs and [`btc_data/BTC-Data-Vong1-TEAMS/simulator/personas.json`](./btc_data/BTC-Data-Vong1-TEAMS/simulator/personas.json). The renderer reads the organizer bundle from [`btc_data/`](./btc_data/).

## 4. Step-by-Step Implementation Instructions

### Step 4.1: Generate Customer Turns
1. Verify `input_blueprints -> ../stage_1_blueprints/latest` and read the tier from its manifest. An explicit `--tier` must match the input tier.
2. Run a full batch or use `--scenario-ids ID [ID ...]` with an optional `--seed` for alternate wording. Targeted runs write under `runs/targeted/` and leave the full-batch `latest` link in place.
3. Use the deterministic Vietnamese renderer to generate 2–5 customer turns per session in each blueprint.
4. Ensure `call_2` and `call_3` utterances naturally reference prior context without explicitly stating internal JSON keys (e.g., *"Alo em ơi, hôm kia chị có nhắn trên Fanpage hỏi máy lọc không khí cho phòng bé nhà chị ấy"*).

### Step 4.2: Inject Channel-Specific Linguistic Realism
Apply formatting rules based on `session.channel`:
1. **Chat Sessions (`channel` in `["facebook", "zalo"]`):**
   - Use natural Vietnamese chat shorthand/teencode (`m`, `k`, `ko`, `tr`, `sz`, `ib`, `shop`, `ad`), missing diacritics on ~30–40% of turns, and Vietnamese-English code-switching (e.g., *"check giúp m sz M còn hàng ko"*).
2. **Voice Call Sessions (`channel == "hotline"`):**
   - Write spoken Vietnamese dialogue with natural fillers (*"Alo em ơi"*, *"Ừm để chị xem"*, *"Dạ vâng"*).
   - Convert numeric prices, dimensions, and quantities into **spoken Vietnamese words** (e.g., `4890000` $\rightarrow$ *"bốn triệu tám trăm chín mươi nghìn"*, `25` $\rightarrow$ *"hai lăm mét vuông"*) to test Inverse Text Normalization (ITN) while keeping normalized integers in `facts_established` and `ground_truth_facts`.
   - Inject light ASR-style phonetic variations on ~15–20% of hotline turns (and ~25–30% when `--tier M2` is active to mirror M2's noisy voice stress-testing).

### Step 4.3: Enforce Strict Constraints & Atomic Promotion
1. **Fact Alignment:** Every slot listed in `call_1.facts_established` MUST be stated or clearly implied by the customer in `call_1.customer_turns`.
2. **Addresses and PII.** Use fictional delivery addresses in structured fields. In customer turns, render the same fictional destination such as “căn bốn mươi hai, lô A, khu giao nhận mô phỏng Sao Mai.” Use lô B for the revised destination in `call_3`. Keep real addresses, phone numbers, and citizen IDs out of customer turns.
3. **Validation.** Check tier, identity, session counts, turn shape, fictional address rendering, and raw PII patterns before publication.
4. Write `generation_log.json` with the input run, tier, seed, transcript and session counts, and style counts. The deterministic renderer makes no model calls, so model, temperature, and token counts are null and retry count is zero. Atomically promote `latest` after a full batch passes validation.

## 5. Output Schema Example (`raw_scenarios.jsonl`)
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
    "customer_turns": [
      "shop oi tu van giup m may loc kk cho phong ngu 25m2 nha co be nho, ngan sach tam 5tr quay dau a",
      "mau AirPure X 4tr890 nghe hop ly do shop, de toi nay m hoi y kien chong roi co gi m goi hotline chot nha"
    ],
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
    "customer_turns": [
      "Alo em ơi, hôm kia chị có nhắn trên Fanpage hỏi máy lọc không khí cho phòng bé nhà chị ấy.",
      "Đúng rồi em, ông xã chị đồng ý rồi. Em lên đơn mẫu AirPure X giá bốn triệu tám trăm chín mươi nghìn giúp chị nhé, giao về căn bốn mươi hai, lô A, khu giao nhận mô phỏng Sao Mai."
    ],
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
- `latest/raw_scenarios.jsonl` contains all blueprints populated with non-empty `customer_turns: list[str]` in every session (`call_1`, `call_2`, and `call_3` where present).
- Total session count is $\ge 120$ for `M1` or $\ge 250$ for `M2`.
- Chat sessions contain realistic teencode/shorthand; hotline sessions contain spoken-form numbers.
