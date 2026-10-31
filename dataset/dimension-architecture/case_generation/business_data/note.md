## Business context

``` mermaid
flowchart LR
    A[Customer Contacts]
    --> B[Agent Collects<br/>Customer Information]
    --> C[Consult / Support]
    --> D{Resolved?}

    D -->|Yes| E[Purchase / Resolution]
    D -->|No| F[Session Ends]

    F --> G[Customer Returns]
    G --> H["⚠ PREVIOUS CONTEXT<br/>NOT AVAILABLE"]
    H --> B

    style H fill:#ffdddd,stroke:#cc0000,stroke-width:4px,color:#990000
```

## Catalog

| Requirement | M1 | M2 |
| --- | --- | --- |
| **Catalog size** | **≥ 30 SKUs** | **≥ 100 SKUs** |
| **Industries** | 1 industry | 3 industries |
| Product information | Required | Required, larger/more diverse |
| Price information | Required | Required |
| Promotion information | Required | Required, including expiration/validity handling |
| Inventory / availability | Required | Required, including out-of-stock cases |

> catalogs.jsonl

```jsonl
{
  "sku": "",
  "industry": "",
  "category": "",
  "name": "",
  "brand": "",
  "description": "",
  "price": {
    "amount": 0,
    "currency": "VND"
  },
  "specifications": {},
  "inventory": {
    "quantity": 0,
    "status": "",
    "updated_at": ""
  },
  "promotion_ids": [],
  "active": true
}
```

> promotions.jsonl

```jsonl
{
  "promotion_id": "",
  "name": "",
  "description": "",
  "discount_type": "",
  "discount_value": 0,
  "valid_from": "",
  "valid_until": "",
  "active": true
}
```

## Policy

| Requirement | M1 | M2 |
| --- | --- | --- |
| Shipping information | Required | Required |
| Return / exchange policy | Required | Required |
| Product / business policy | Required | Required |
| Policy document count | **Not specified** | **Not specified** |

> policies.jsonl

```jsonl
{
  "policy_id": "",
  "type": "",
  "title": "",
  "description": "",
  "rules": [
    {
      "condition": "",
      "rule": ""
    }
  ],
  "valid_from": "",
  "valid_until": "",
  "active": true
}
```
