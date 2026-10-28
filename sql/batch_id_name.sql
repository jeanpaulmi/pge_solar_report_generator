-- Confirm billing batches were created: distinct contract count per batch name.
--
-- Template variables (substituted by batch_lookup.py):
--   database     -> pge_stage | pge_uat | pge   (pge == prod)
--   batch_filter -> one OR'd LIKE clause per batch number or name fragment,
--                   e.g.  batch LIKE '%252882%' OR batch LIKE '%252883%'

SELECT
  COUNT(DISTINCT contract_id) AS contract_id_count,
  batch
FROM {{database}}.accountbillinglog
WHERE {{batch_filter}}
GROUP BY batch
ORDER BY batch
