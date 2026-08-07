-- Active NEM3 residential EELEC contracts for the report year.
--
-- Template variables (substituted by get_contract_ids.py):
--   database    -> pge_stage | pge_uat | pge   (pge == prod)
--   report_year -> current calendar year - 1   (e.g. run in 2026 -> 2025)

SELECT
  contract_id
  -- meteraccount_id,
  -- servicepoint_id,
  -- person_id,
  -- entity_id_a,
  -- premise_id,
  -- meter_id,
  -- time_zone,
  -- customerpk,
  -- marketplace,
  -- contract_start_date,
  -- contract_end_date,
  -- service_status,
  -- contract_rate_code,
  -- contract_root,
  -- contract_rate_code_error_message,
  -- contract_scope,
  -- attr_260,
  -- attr_263
FROM {{database}}.customerdimension_ba
WHERE service_status = 'Active'
  AND contract_start_date >= CAST('{{report_year}}-01-01' AS TIMESTAMP)
  AND contract_rate_code = 'EELEC'
  AND contract_scope = 'res'
  AND attr_260 = 'NEM3'
ORDER BY contract_id
