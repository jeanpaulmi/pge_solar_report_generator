-- SEASONAL QUERY: County-level statistics using MEDIAN (APPROX_PERCENTILE 0.5).
-- All outputs are rounded to whole numbers (no decimals):
--   AVG_SOLARCHRG_RANGE -> nearest whole dollar   ($32 - $79)
--   AVG_SAVINGS_RANGE   -> whole percentages      (64% - 88%)
--
-- Template variables (substituted by generate_seasonal_report.py):
--   database   -> pge_stage | pge_uat | pge   (pge == prod)
--   season     -> Spring | Summer | Fall | Winter | All
--   bill_years -> report year, i.e. current calendar year - 1 (e.g. 2025)
--   batch_ids  -> one or more quoted azkaban batch ids, comma separated

WITH
season_input AS (
  SELECT '{{season}}' AS selected_season
),
customer_totals AS (
  SELECT
    contractid AS SA_ID,
    servicepointid AS SP_ID,
    MAX(TRIM(
      CONCAT(
        CASE WHEN SPLIT_PART(normalized_county, ' ', 1) != '' THEN CONCAT(UPPER(SUBSTR(SPLIT_PART(normalized_county, ' ', 1), 1, 1)), SUBSTR(SPLIT_PART(normalized_county, ' ', 1), 2)) ELSE '' END,
        CASE WHEN SPLIT_PART(normalized_county, ' ', 2) != '' THEN CONCAT(' ', UPPER(SUBSTR(SPLIT_PART(normalized_county, ' ', 2), 1, 1)), SUBSTR(SPLIT_PART(normalized_county, ' ', 2), 2)) ELSE '' END,
        CASE WHEN SPLIT_PART(normalized_county, ' ', 3) != '' THEN CONCAT(' ', UPPER(SUBSTR(SPLIT_PART(normalized_county, ' ', 3), 1, 1)), SUBSTR(SPLIT_PART(normalized_county, ' ', 3), 2)) ELSE '' END,
        CASE WHEN SPLIT_PART(normalized_county, ' ', 4) != '' THEN CONCAT(' ', UPPER(SUBSTR(SPLIT_PART(normalized_county, ' ', 4), 1, 1)), SUBSTR(SPLIT_PART(normalized_county, ' ', 4), 2)) ELSE '' END
      )
    )) AS premise_county,
    SUM(COALESCE(charge_value, 0)) AS total_solar_charges,
    SUM(TRY_CAST(bill_amount_alt3 AS DOUBLE) - TRY_CAST(bill_amount_alt2 AS DOUBLE)) AS total_solar_savings,
    SUM(TRY_CAST(bill_amount_alt3 AS DOUBLE)) AS total_without_solar_bill
  FROM (
    SELECT
      contractid,
      servicepointid,
      bill_attribute_list_alt2,
      bill_amount_alt2,
      bill_amount_alt3,
      TRIM(REGEXP_REPLACE(REGEXP_REPLACE(
        LOWER(REPLACE(
          COALESCE(REGEXP_EXTRACT(bill_attribute_list_alt2, '373=([^;]+)', 1), ''),
          '_', ' '
        )),
        ' +', ' '
      ), ' +', ' ')) AS normalized_county,
      TRY_CAST(REGEXP_EXTRACT(charge_item, '=([0-9.-]+)', 1) AS DOUBLE) AS charge_value
    FROM {{database}}.accountbillimpact
    CROSS JOIN UNNEST(SPLIT(bill_metrics_alt2, ';')) AS t(charge_item)
    CROSS JOIN season_input
    WHERE batchid IN (
      {{batch_ids}}
    )
      AND (
        (selected_season = 'Spring' AND billmonth IN (3, 4, 5))
        OR (selected_season = 'Summer' AND billmonth IN (6, 7, 8))
        OR (selected_season = 'Fall' AND billmonth IN (9, 10, 11))
        OR (selected_season = 'Winter' AND billmonth IN (12, 1, 2))
        OR (selected_season = 'All')
      )
      AND billyear IN ({{bill_years}})
      AND premise IS NOT NULL
      AND bill_metrics_alt2 IS NOT NULL
      AND bill_amount_alt2 IS NOT NULL
      AND bill_amount_alt3 IS NOT NULL
      AND charge_item LIKE '%Generation_Charge%'
      AND charge_item LIKE '%=%'
  ) charge_data
  GROUP BY contractid, servicepointid
  HAVING COUNT(*) >= 2
)

-- NOTE: output aliases are double quoted so Athena preserves the upper case
-- column names in the result header (unquoted identifiers get lower cased).
SELECT
  premise_county AS "PREMISE_COUNTY",

  -- Dollar amounts are rounded to the nearest whole dollar, no decimals
  -- (e.g. 31.58 - 79.32 renders as $32 - $79).
  CASE
    WHEN APPROX_PERCENTILE(total_solar_charges, 0.5) IS NOT NULL THEN
      CONCAT(
        '$',
        CAST(CAST(
          ROUND(
            GREATEST(
              0,
              APPROX_PERCENTILE(total_solar_charges, 0.5)
              - (COALESCE(STDDEV(total_solar_charges), 0) * 0.2)
            )
          ) AS BIGINT
        ) AS VARCHAR),
        ' - $',
        CAST(CAST(
          ROUND(
            APPROX_PERCENTILE(total_solar_charges, 0.5)
            + (COALESCE(STDDEV(total_solar_charges), 0) * 0.2)
          )
        AS BIGINT) AS VARCHAR)
      )
    ELSE 'NO_CHARGE_DATA'
  END AS "AVG_SOLARCHRG_RANGE",

  CASE
    WHEN APPROX_PERCENTILE(total_solar_savings, 0.5) IS NOT NULL
         AND APPROX_PERCENTILE(total_without_solar_bill, 0.5) > 0 THEN

      CASE
        WHEN STDDEV(total_solar_savings) IS NOT NULL
             AND STDDEV(total_solar_savings) > 0 THEN

          CONCAT(
            CAST(CAST(
              ROUND(
                GREATEST(
                  0,
                  (
                    (
                      APPROX_PERCENTILE(total_solar_savings, 0.5)
                      - (STDDEV(total_solar_savings) * 0.2)
                    )
                    / APPROX_PERCENTILE(total_without_solar_bill, 0.5)
                  ) * 100
                )
              )
            AS BIGINT) AS VARCHAR),
            '% - ',
            CAST(CAST(
              ROUND(
                (
                  (
                    APPROX_PERCENTILE(total_solar_savings, 0.5)
                    + (STDDEV(total_solar_savings) * 0.2)
                  )
                  / APPROX_PERCENTILE(total_without_solar_bill, 0.5)
                ) * 100
              )
            AS BIGINT) AS VARCHAR),
            '%'
          )

        ELSE

          CONCAT(
            CAST(CAST(
              ROUND(
                (
                  APPROX_PERCENTILE(total_solar_savings, 0.5)
                  / APPROX_PERCENTILE(total_without_solar_bill, 0.5)
                ) * 100
              )
            AS BIGINT) AS VARCHAR),
            '% - ',
            CAST(CAST(
              ROUND(
                (
                  APPROX_PERCENTILE(total_solar_savings, 0.5)
                  / APPROX_PERCENTILE(total_without_solar_bill, 0.5)
                ) * 100
              )
            AS BIGINT) AS VARCHAR),
            '%'
          )

      END

    ELSE 'NO_SAVINGS_DATA'
  END AS "AVG_SAVINGS_RANGE",

  (SELECT selected_season FROM season_input) AS "SEASON",
  COUNT(*) AS "CUSTOMER_COUNT"

FROM customer_totals

WHERE premise_county != ''
  AND premise_county IS NOT NULL
  AND total_solar_charges > 0
  AND total_solar_savings > 0

GROUP BY premise_county

ORDER BY "CUSTOMER_COUNT" DESC
