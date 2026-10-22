-- Confirm a billing batch was created: distinct contract count per batch name.
--
-- Template variables (substituted by batch_id_name.py):
--   database -> pge_stage | pge_uat | pge   (pge == prod)
--   batch_id -> batch number or name fragment (e.g. 252721)

SELECT
  COUNT(DISTINCT contract_id) AS contract_id_count,
  batch
FROM {{database}}.accountbillinglog
WHERE batch LIKE '%{{batch_id}}%'
GROUP BY batch
ORDER BY batch
