# Proposed M1 Blueprint Regeneration Plan

Generate **175 candidate blueprints** for **thời trang** using the 35 BTC CRM profiles from **miền Trung and miền Nam**. Target **150 retained transcripts** after validation and deduplication. The previous M1 judge accepted 124 of 140 drafts (88.6%). At that rate, about 155 of 175 new drafts would pass the judge before final checks. [Previous M1 validation report](m1-stage2-report.md)

## M1 requirements and proposed targets

Apply the organizer’s M1 requirements to the final release. Check both the audio count and duration minima. Measure the proposed targets after text validation, deduplication, and audio generation. [Organizer brief, page 3, section C.1](<../btc/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf#page=3>)

| Hạng mục dataset | M1 | Proposed release target |
| --- | --- | --- |
| Số cuộc hội thoại (dạng transcript) | ≥ 120 | **150 transcripts**, 77 miền Trung and 73 miền Nam |
| Trong đó có audio (thu thật hoặc sinh bằng TTS) | ≥ 40 cuộc / ≥ 1 giờ | **120 transcripts with audio**, 60 per region, totaling **70 minutes** |
| Khách hàng đa phiên (≥ 2 cuộc gọi cùng 1 khách) | ≥ 30 khách | **33 distinct customers** with at least two hotline calls in a retained transcript |
| Khách có cả cuộc gọi + chat (đa kênh) | ≥ 10 khách | **18 distinct customers** with hotline and chat in a retained transcript |
| Ngành hàng · giọng vùng miền | 1 ngành · 2 miền | **Thời trang** with **Central and Southern accents** verified by listening |
| Audio có nhiễu (đường phố, sóng yếu) | — | **0 transcripts with added noise** |
| Catalog sản phẩm + chính sách (giá, KM, đổi trả, ship) | ≥ 30 SKU | **45 official fashion variant SKUs** in scope, with **40** targeted in retained transcripts and the applicable BTC policies |

The BTC fashion catalog contains 8 parent products and 96 individually tracked size and color variants. Of those variants, 70 are under active products and have positive stock in the catalog snapshot. Choose the 45 variant SKUs using BTC stock and price checks on the planned session dates. Use the applicable pricing, promotion, exchange, and shipping policies, and report parent products and variant SKUs separately. [BTC catalog](../btc/BTC-Data-Vong1-TEAMS/catalog/products.json) · [BTC policies](../btc/BTC-Data-Vong1-TEAMS/policy/) · [BTC reference tools](../btc/BTC-cap-nhat-11-2026/eval/mock_tools.py)

## CRM coverage and regional allocation

| Region | Voice label | BTC profiles | Has Facebook or Zalo | Planned blueprints |
| --- | --- | ---: | ---: | ---: |
| Miền Trung | `Central` | 18 | 9 | 90 |
| Miền Nam | `South` | 17 | 12 | 85 |
| **Total** | | **35** | **21** | **175** |

The 35 customers and 21 chat-eligible customers are counts from the BTC CRM. The 33 multi-call customers and 18 omnichannel customers are proposed targets for the retained dataset. Count distinct `customer_id` values after validation and deduplication. [BTC CRM](../btc/BTC-Data-Vong1-TEAMS/catalog/crm_seed.json) · [Regional voice label mapping](../stage-1/src/generate.py#L24)

Assign five blueprints to each profile. Reserve two hotline-only blueprints per profile (**70 total**) and two hotline + chat blueprints per eligible profile (**42 total**). Allocate the remaining **63** to other planned cases. Reserve one shared-phone case for each of the two linked profiles and assign the six conflicting-quote cases to the six profiles with both Facebook and Zalo.

## Persona and conversation pattern matrix

The 175 blueprints cover all 12 BTC personas and 35 persona × pattern pairings. Each populated cell has at least two blueprints, which allows both regions to appear in that pairing. [BTC personas](../btc/BTC-Data-Vong1-TEAMS/simulator/personas.json)

| Persona | Cân nhắc | Đa kênh | Giá / tồn kho | Sau mua | Danh tính / lịch sử | Chuyển máy | Tổng |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Hỏi ý kiến người nhà | 12 | 5 | 6 | 2 | 0 | 0 | 25 |
| So sánh giá | 10 | 5 | 9 | 2 | 0 | 2 | 28 |
| Quay lại đổi size hoặc khiếu nại | 3 | 5 | 5 | 19 | 4 | 2 | 38 |
| Hỏi nhiều, chưa mua | 3 | 4 | 2 | 2 | 0 | 0 | 11 |
| Mất kiên nhẫn ở cuộc gọi thứ ba | 0 | 0 | 2 | 10 | 2 | 2 | 16 |
| Chuyển giữa chat và hotline | 0 | 12 | 0 | 0 | 0 | 0 | 12 |
| Hỏi ngoài phạm vi và chấp nhận chuyển máy | 0 | 0 | 0 | 0 | 0 | 7 | 7 |
| Hỏi ngoài tài liệu | 2 | 5 | 0 | 0 | 0 | 2 | 9 |
| Chất vấn báo giá mâu thuẫn | 0 | 6 | 0 | 0 | 0 | 0 | 6 |
| Dùng chung số điện thoại | 0 | 0 | 0 | 0 | 2 | 0 | 2 |
| Quay lại sau tám tháng | 0 | 0 | 2 | 3 | 10 | 0 | 15 |
| Mua nhiều món | 0 | 0 | 4 | 2 | 0 | 0 | 6 |
| **Tổng** | **30** | **42** | **30** | **40** | **18** | **15** | **175** |

Plan **147 two-session and 28 three-session blueprints** for **378 total sessions**. The three-session group includes the 16 third-call cases, six conflicting-quote cases using Facebook, Zalo, and hotline, and six other cases.

## Generation and publication

1. **Stage 1.** Build a fresh CRM-backed M1 run using the matrix and regional allocation. Adapt restock and handoff cases to fashion. Use dated BTC prices, promotions, inventory, policies, and tool assertions for the planned sessions. [Stage 1 generator](../stage-1/src/generate.py)
2. **Stage 2.** Generate `customer_turns` with `Qwen3-30B-A3B Q4_K_M`. Apply the Python format check, then use DeepEval with `Gemma 4 12B IT QAT Q4_0` to validate the saved drafts. [Generation notebook](../stage-2/phase-1/generate.ipynb) · [Validation notebook](../stage-2/phase-2/validate.ipynb)
3. **Stage 3.** Assemble the accepted transcripts, scan for privacy issues, and deduplicate with TF-IDF. Calculate the retained transcript count, multi-call and omnichannel customer coverage, and SKU coverage. Fill any required text coverage gap with targeted additional blueprints and run them through the same checks. [Stage 3 workflow](../stage-3.md)
4. **Audio and release.** Synthesize hotline customer turns for 120 retained transcripts, 60 per region. The 22 comparable transcripts from the previous release averaged about 112 whitespace-delimited tokens of hotline customer dialogue. Budgeting 35 seconds per transcript gives a 70-minute target. Sum valid WAV durations by `scenario_id`, confirm both regional accents by listening, and render additional retained transcripts if needed. Publish when all M1 requirements pass. [Previous transcripts](../stage-3/output/) · [Existing TTS notebook](../../text-to-speech/pipeline-generate-audio/customer_turns_to_f5_tts_vimd_40_scenarios_kaggle.ipynb)
