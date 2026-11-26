# Organizer inputs ranked by persona and journey pattern

The current Stage 1 M1 batch contains **140 journeys, 12 personas, six primary journey patterns, and 19 persona–pattern pairings**. Stage 2 uses the blueprint persona and session purpose to render customer turns. The rankings below reflect how directly each file helps design blueprints or dialogue. [Stage 1 journey report](./m1-stage1-report.md) · [Stage 2 renderer](../stage-2/src/generate.py)

## 🎭 Axis 1 · Persona

| Rank | File | Why it matters |
| ---: | --- | --- |
| **1** | `simulator/personas.json` | The main source for customer behavior. Each of the 12 personas has a style, a system prompt, and patience settings for three sessions. Stage 2 can use these to give different customers distinct reactions to the same situation. [Persona catalog](../btc/BTC-Data-Vong1-TEAMS/simulator/personas.json) |
| **2** | `simulator/customer_simulator_spec.md` | Explains how behavior changes during a conversation. A customer can lose patience after a repeated question, challenge a changed price, or end the call. [Simulator spec](../btc/BTC-Data-Vong1-TEAMS/simulator/customer_simulator_spec.md) |
| **3** | Project brief, section C.1 | Sets the M1 persona coverage target. It lists the hesitant shopper, price comparer, and post-purchase exchange or complaint customer. The current batch assigns them 24, 30, and 32 journeys respectively. [Project brief](<../btc/SUDO CODE 2026 - Đề Bài Dự Án Cuối Kì.pdf>) |
| **4** | `policy/playbook-telesale.md` | Gives examples of realistic objections, such as a customer comparing competitor prices, consulting family, or losing patience after a conflicting quote. It also describes the expected agent response. [Telesales playbook](../btc/BTC-Data-Vong1-TEAMS/policy/playbook-telesale.md) |

## 🧭 Axis 2 · Journey pattern

| Rank | Files | Why they matter |
| ---: | --- | --- |
| **1** | `DIEU-CHINH-DE.md`, section 11 | The best source of new patterns. It describes conflicting quotes across channels, two people sharing a phone, a customer returning after eight months, multi-item purchases, and exchanges under an older policy. [Organizer adjustments](../btc/BTC-Data-Vong1-TEAMS/DIEU-CHINH-DE.md#11-bộ-test-ẩn-41-kịch-bản-19-ca-khó) |
| **2** | `schemas/scenario_format.md` and the seven public samples | Show how to turn each pattern into a testable blueprint with session order, prior history, facts to remember, and success checks. `SAMPLE-03` shows a post-purchase size exchange. `SAMPLE-04` shows a Facebook-to-hotline journey. [Scenario format](../btc/BTC-Data-Vong1-TEAMS/schemas/scenario_format.md) · [Public samples](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/) |
| **3** | `policy/*.md`, especially `changelog.md` and both return-policy versions | Supply rules that can change a customer’s options between sessions. For example, the date of the original order determines which exchange fee applies. Shipping, payment, and holiday rules support other patterns. [Policy files](../btc/BTC-Data-Vong1-TEAMS/policy/) |
| **4** | `catalog/crm_seed.json` | Supplies the starting customer state. Two customers have orders, three have prior sessions, and two distinct people share a phone. Stage 1 uses the identities today. Prior orders and sessions can support returning-customer journeys. [CRM seed report](./crm_seed_report.md) |
| **5** | `products.json`, `promotions.json`, `inventory_timeline.json`, and the November `mock_tools.py` | Supply the facts used to validate each pattern. They determine price, stock, promotion eligibility, and the expected tool result on each session date. [Catalog files](../btc/BTC-Data-Vong1-TEAMS/catalog/) · [November mock tools](../btc/BTC-cap-nhat-11-2026/eval/mock_tools.py) |

## Supporting validation files

The tool and brief schemas, reference evaluator, and judge rubric help check scenario outputs and agent behavior. The ASR and RAG fixtures support separate evaluation tasks. [Base schemas](../btc/BTC-Data-Vong1-TEAMS/schemas/) · [Reference evaluator](../btc/BTC-cap-nhat-11-2026/eval/reference_eval.py) · [Judge rubric](../btc/BTC-Data-Vong1-TEAMS/eval/llm_judge_rubric.json)

## Example of the two axes together

**`khach_da_mua_doi_size` × post-purchase support.** The current batch includes 24 journeys in this pairing. A size-exchange version sets up the purchase, then checks that the agent updates the existing order with the requested variant. Some journeys reuse the same persona under a different primary pattern, such as an exchange that tests cross-channel continuity. [Stage 1 journey report](./m1-stage1-report.md) · [Size-exchange sample](../btc/BTC-Data-Vong1-TEAMS/test_set/public_sample/SAMPLE-03.json)
