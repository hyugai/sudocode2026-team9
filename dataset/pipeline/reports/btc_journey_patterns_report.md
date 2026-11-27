# Organizer journey patterns

This report draws on `btc/`. The public bundle contains six two-session examples and one single-session policy case. The project brief also gives a three-session M2 demo outline. The six general patterns below are a grouping for Stage 1 design. The detailed lists identify whether the organizer provides a sequence, names a case, or describes a policy workflow. [Organizer bundle README](../btc/BTC-Data-Vong1-TEAMS/README.md)

## 1. Sequences by organizer source

### Public samples

| Sample | Sequence shown | Evaluation focus |
| --- | --- | --- |
| [SAMPLE-01](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-01.json) | Ask about an air purifier and say they will consult family → call back two days later, confirm the price, and ask to order. | Recall the model, quote, room size, budget, and reason for waiting. |
| [SAMPLE-02](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-02.json) | Compare a competitor’s price and ask about warranty → call back three days later, ask about a gift, and agree to buy. | Carry forward the original quote and price objection. |
| [SAMPLE-03](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-03.json) | Buy shoes in size 39 → call back four days later to request size 40. | Recall the order and variant, then apply the size-exchange policy. The expected tool is `order.update`. |
| [SAMPLE-04](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-04.json) | Get a shoe quote on Facebook → call the hotline the next day, refer to the quote, and ask to order. | Link the Facebook and phone identities and carry forward the valid quote. |
| [SAMPLE-05](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-05.json) | Ask about a discount → call back 20 days later expecting it → agree to buy. The notes say the offer has expired and the current price applies. | Recall the original offer, explain expiry, and quote the current price. |
| [SAMPLE-06](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-06.json) | Ask about an out-of-stock air purifier in a call supplied with ASR errors → follow up on Zalo five days later after restock and ask to order. | Carry context across channels and check current stock and regional offers. |
| [SAMPLE-07](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-07.json) | In one session, ask about the old 14-day return window and 20,000₫ size-exchange fee. | The expected answer corrects the customer using the current policy. |

### Project brief

- **Case 1.** Get air-purifier advice and a quote → say they will consult family → call back two days later → a different employee repeats questions and quotes a different model.
- **Case 2.** Ask about shoes on Facebook → ask about size exchange on Zalo → watch a livestream → call the hotline and receive a different price.
- **Case 3.** Raise an out-of-scope question → get transferred → the receiving employee asks the customer to start over. The brief also describes a morning shift scheduling an afternoon callback that a different shift handles.
- **Section C.6, M1 demo.** Get advice, a quote, and a promotion → say they will consult family → return a few days later and buy.
- **Section C.6, M2 demo.** Add a third call after purchase to request a size exchange or ask about shipment tracking. [Project brief](<../btc/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>)

### Organizer adjustments

Section 11 of `DIEU-CHINH-DE.md` reports 19 hard cases among 41 hidden scenarios. It names situations such as conflicting quotes across three channels, two people sharing a phone, a customer returning after eight months, three sessions with changing information followed by an order-status question, a callback falling on a holiday, and stock running out when the customer decides to buy. It also names size exclusions on promotions, a 16-turn call about four products, a product exchange with a refund of the difference, and an older-policy question. [Organizer adjustments, section 11](../btc/BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md#11-bộ-test-ẩn-41-kịch-bản-19-ca-khó)

### ASR fixtures and clarifications

- **`asr/ground_truth.json`.** `D01` and `D02` are calls 1 and 2 of `SC-01`. The first compares air-purifier models and defers the decision to consult family. The second returns to the prior inquiry and requests an order. `D03` shows one price-comparison call. `D04` shows a post-purchase size-exchange call. [ASR fixtures](../btc/BTC-Data-Vong1-TEAMS/asr/ground_truth.json)
- **`Q&A.pdf`.** The organizer clarifies that `D01` discusses AirPure Y and AirPure X and ends before the customer chooses. `D02` refers back to AirPure Y. [Organizer Q&A](<../btc/Q&A.pdf>)
- **`GIAI-DAP-MENTOR.md`.** The organizer explicitly includes phone → inbox under Case 2 and points to `SAMPLE-04` for Facebook → hotline. [Mentor clarification](../btc/BTC-Data-Vong1-TEAMS/GIAI-DAP-MENTOR.md)

## 2. Generalized patterns

| Pattern | Core sequence | Organizer evidence |
| --- | --- | --- |
| **1. Consider and decide** | Get advice or a quote → take time to consider → return to decide. | `SAMPLE-01`, `SAMPLE-02`, and the M1 demo. |
| **2. Continue across channels** | Start on one channel → resume on another → carry forward the earlier context. | `SAMPLE-04`, Case 2, and the mentor clarification. |
| **3. Return after a business change** | Learn the original price or stock status → return after it changes → decide using the current facts. | `SAMPLE-05` and `SAMPLE-06`. |
| **4. Return for post-purchase support** | Buy → contact the shop about the existing order → ask for a change or check its status. | `SAMPLE-03` and the M2 demo. |
| **5. Resume with uncertain identity or history** | Reconnect → verify who is speaking or whether earlier details still apply → use the relevant history. | Section 11’s shared-phone and eight-month return cases. |
| **6. Transfer with context** | Explain the need → raise an out-of-scope question → transfer with the context already gathered. | Case 3 and the organizer’s handoff scoring rule. The transfer can happen within a single call. |

Hard cases add difficulty to a pattern. Conflicting quotes make a channel switch harder, and a shared phone makes identity verification harder. The README describes two hard samples, `SAMPLE-06` for ASR errors and chat shorthand and `SAMPLE-07` for an outdated policy. The JSON fixtures also set `hard_case` on `SAMPLE-05` for an expired promotion, making three tagged samples. [Public bundle inventory](../btc/BTC-Data-Vong1-TEAMS/README.md) · [SAMPLE-05](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-05.json)

## 3. Detailed cases within each generalized pattern

### 1. Consider and decide

- **Consult family, then buy.** Ask about an air purifier → say they will consult family → return two days later and order. The project brief’s M1 demo describes the same progression over a few days. [SAMPLE-01](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-01.json) · [Project brief](<../btc/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>)
- **Compare prices, then buy.** Raise a competitor’s price and ask about warranty → return three days later → ask about a gift and agree to buy. [SAMPLE-02](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-02.json)
- **Compare two models, then call back.** Discuss AirPure Y and the cheaper AirPure X → defer the decision to consult family → refer back to AirPure Y in the next call. [ASR fixtures](../btc/BTC-Data-Vong1-TEAMS/asr/ground_truth.json) · [Organizer Q&A](<../btc/Q&A.pdf>)
- **Return and lose confidence.** Receive advice and a quote → call back two days later → face repeated questions and a quote for a different model. [Project brief, Case 1](<../btc/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>)
- **Named variants and rules.** The playbook describes three sessions without a purchase. Section 11 names a callback falling on a holiday and a single 16-turn call about four products with budget and COD constraints. The holiday notice gives a specific rescheduling example from October 26 to October 27, 2026. [Telesales playbook](../btc/BTC-Data-Vong1-TEAMS/policy/playbook-telesale.md) · [Organizer adjustments](../btc/BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md) · [Holiday notice](../btc/BTC-Data-Vong1-TEAMS/policy/thong-bao-lich-nghi.md)

### 2. Continue across channels

- **Facebook → hotline.** Get a quote on Facebook → call the hotline the next day → refer to the quote and order. [SAMPLE-04](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-04.json)
- **Phone → inbox.** The organizer names this direction in the mentor clarification. [Mentor clarification](../btc/BTC-Data-Vong1-TEAMS/GIAI-DAP-MENTOR.md)
- **Facebook → Zalo → livestream → hotline.** Ask about shoes on Facebook → ask about size exchange on Zalo → watch a livestream → receive a different quote on the hotline. [Project brief, Case 2](<../btc/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>)

### 3. Return after a business change

- **Promotion expires.** Get a promotional quote → return 20 days later expecting the discount → agree to buy at the current price. [SAMPLE-05](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-05.json)
- **Item comes back into stock.** Ask about an out-of-stock air purifier in a call with ASR errors → follow up on Zalo five days later after restock → ask to order. This also fits the cross-channel pattern. [SAMPLE-06](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-06.json)
- **Item sells out at the buying decision.** The organizer names this case and leaves the final decision open. [Organizer adjustments](../btc/BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md)

### 4. Return for post-purchase support

- **Size exchange.** Buy shoes → call back four days later to exchange size 39 for size 40. [SAMPLE-03](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-03.json)
- **Third-call exchange or shipment tracking.** Get advice → return to buy → call again to exchange the size or ask about shipment tracking. [Project brief, M2 demo](<../btc/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>)
- **Order status after changes and exchange with a refund.** Section 11 names these as separate cases. The exchange procedure specifies a refund of the difference when a replacement product costs less. [Organizer adjustments](../btc/BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md) · [Exchange procedure](../btc/BTC-Data-Vong1-TEAMS/policy/quy-trinh-cod-hoan-hang.md)
- **Other policy workflows.** A COD order is held and canceled after two unanswered confirmation calls. After three failed deliveries, the order returns to the warehouse and redelivery requires a new order. A customer who finds a defect after delivery can send evidence through Zalo for a replacement. [COD and returns procedure](../btc/BTC-Data-Vong1-TEAMS/policy/quy-trinh-cod-hoan-hang.md) · [Delivery policy](../btc/BTC-Data-Vong1-TEAMS/policy/chinh-sach-van-chuyen-thanh-toan.md)

### 5. Resume with uncertain identity or history

- **Shared phone.** Two people use the same number. The persona prompt says the caller corrects the agent if it uses the other person’s name or history. [Persona catalog](../btc/BTC-Data-Vong1-TEAMS/simulator/personas.json)
- **Return after eight months.** The organizer names stale address information, a discontinued SKU, and trade-in as elements of the case. [Organizer adjustments](../btc/BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md)
- **Return after requesting data deletion.** Ask to delete the profile → the system deletes it → a later call is handled as a new customer. [Data-deletion procedure](../btc/BTC-Data-Vong1-TEAMS/policy/quy-trinh-cod-hoan-hang.md)

### 6. Transfer with context

- **Same-call transfer.** Explain the purchase situation → ask an out-of-scope medical question → transfer to a human. Case 3 illustrates a failed transfer where the receiving employee asks the customer to start over. The scoring rule expects `handoff.transfer` with a valid brief. [Project brief, Case 3](<../btc/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>) · [Handoff scoring rule](../btc/BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md)
- **Cross-shift handoff.** The morning shift schedules an afternoon callback → a different shift handles it. The brief presents this as another situation that requires sharing context. [Project brief, Case 3](<../btc/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>)

**Standalone policy case.** `SAMPLE-07` is one session about the old return window and exchange fee. Its expected answer uses the updated policy. [SAMPLE-07](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-07.json)
