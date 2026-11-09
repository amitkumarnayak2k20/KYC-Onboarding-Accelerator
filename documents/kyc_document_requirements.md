# KYC document review guidance (training example)

## Passport
A passport review should capture the document holder's full name, date of birth, passport number and expiry date. Compare extracted values with the visible source document. Do not infer a missing digit or silently correct an ambiguous date. If any mandatory field is absent, illegible or inconsistent, route the case for manual review or request a clearer document through the approved workflow.

## Proof of address
Proof of address should be checked against the address supplied in the application. Differences in abbreviations, punctuation or formatting may be benign, but an exact-string match alone is not proof of identity or residency. Material differences, expired documents, or unreadable address lines require human review.

## Human review and decisioning
Automated extraction is an assistance tool. It must not make a final account-opening decision. A trained reviewer must resolve conflicting or low-confidence fields, confirm document validity using approved sources, and record the rationale for the outcome. Do not use the agent's preliminary risk band as the sole basis for approval or rejection.

## Data minimisation
Use only the minimum information needed for the review. The training knowledge base must contain policy guidance and synthetic examples only. Never index real customer identity documents, passport numbers, dates of birth, addresses, or other production personal data in this demo vector store.
