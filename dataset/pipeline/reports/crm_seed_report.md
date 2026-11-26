# Organizer CRM seed report

The organizer seed contains 50 customer records. All have a customer ID, name, honorific, phone number, and region. The records contain 49 distinct phone numbers and 49 distinct names. The [organizer seed](../btc/BTC-Data-Vong1-TEAMS/catalog/crm_seed.json) and the [Stage 1 input copy](../stage-1/input/catalog/crm_seed.json) are byte-for-byte identical.

## Schema and coverage

The top-level JSON object contains a `customers` array and a `notes` string. Coverage below counts values that are present and non-empty.

| Customer field | Records with a value | Type and contents |
| --- | ---: | --- |
| `customer_id`, `name`, `honorific`, `phone`, `region` | 50 each | Strings |
| `fb_id` | 17 | Facebook handle or `null` |
| `zalo_id` | 25 | Zalo handle or `null` |
| `orders` | 2 | Array present on all 50 records, empty on 48 |
| `sessions` | 3 | Array present on 3 records, omitted on 47 |
| `shared_phone_with` | 2 | Customer ID of the other account, omitted on 48 |

The regional breakdown is 15 `bac`, 18 `trung`, and 17 `nam`. The seed contains no delivery-address or citizen-ID (`cccd`) fields.

Order records contain `order_id`, `date`, `sku`, `price_vnd`, `status`, and `tracking`. Session records contain `session_id`, `channel`, `date`, `outcome`, and `summary`.

## Records with history or shared-phone metadata

| Customer ID | Orders | Prior sessions | Social handles | Shares phone with |
| --- | ---: | ---: | --- | --- |
| `C031` | 1 | 1 | Facebook and Zalo | — |
| `C032` | 1 | 0 | — | — |
| `C033` | 0 | 1 | Zalo | — |
| `C034` | 0 | 1 | Facebook | `C035` |
| `C035` | 0 | 0 | Zalo | `C034` |

`C031` has the most populated optional fields. `C032` has an order and no social handles.

## Social handle coverage

| Available handles | Count | Customer IDs |
| --- | ---: | --- |
| Facebook and Zalo | 9 | `C001`, `C007`, `C013`, `C019`, `C025`, `C031`, `C037`, `C043`, `C049` |
| Facebook only | 8 | `C004`, `C010`, `C016`, `C022`, `C028`, `C034`, `C040`, `C046` |
| Zalo only | 16 | `C003`, `C005`, `C009`, `C011`, `C015`, `C017`, `C021`, `C023`, `C027`, `C029`, `C033`, `C035`, `C039`, `C041`, `C045`, `C047` |
| Neither | 17 | `C002`, `C006`, `C008`, `C012`, `C014`, `C018`, `C020`, `C024`, `C026`, `C030`, `C032`, `C036`, `C038`, `C042`, `C044`, `C048`, `C050` |

## Identity cases relevant to Stage 1

- `C033` and `C034` have the same name and different phone numbers. They represent distinct customers with separate addresses.
- `C034` and `C035` have different names and share a phone number. Their `shared_phone_with` fields point to each other. Each customer keeps a separate ID and address.
- The standalone Stage 1 registry assigns addresses by `customer_id`. It represents missing `shared_phone_with` values as `null`.
