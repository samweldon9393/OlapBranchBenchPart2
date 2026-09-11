-- Price is quoted before discount, so the discount comes off to reach canonical net revenue.
-- americas reports no tax, so the column is carried but never filled.
CREATE OR REPLACE TABLE stg_americas AS
SELECT order_key, cust_key, order_date,
       CAST(gross_price - discount_amount AS DECIMAL(18, 2)) AS net_price,
       CAST(NULL AS DECIMAL(18, 2)) AS tax_amount,
       'americas' AS source
FROM feed_americas
