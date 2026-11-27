---
{"do": "state only the confirmed discount details and express uncertainty regarding the exact end date without confirming or inventing a specific date", "id": "ebdb88d3ac6bba59ce51eccbeb427106df41d30d0a6154c8cf2ace2f55abf52b", "mechanism": "knowledge_gap", "otherwise": "confirming an unverified expiration date risks stating unsupported claims", "scope": "general", "source_refs": [{"job_id": "29560d2f478952272ead255c0b7034dd33448bb3b87365820ec5b90fb54b4126", "message_id": 4, "origin": "turn_detector", "turn_id": 3}], "status": "approved", "title": "Verify promotion expiration dates before confirming", "triggers": ["uu dai nay het ngay", "han su dung ma gia gia", "promotion expiry date", "promo expiration date"], "version": 2, "when": "a customer asks to confirm a promotion's specific expiration date and retrieved records do not contain the exact end date"}
---

# Verify promotion expiration dates before confirming

## When
a customer asks to confirm a promotion's specific expiration date and retrieved records do not contain the exact end date

## Do
state only the confirmed discount details and express uncertainty regarding the exact end date without confirming or inventing a specific date

## Otherwise
confirming an unverified expiration date risks stating unsupported claims
