-- Folds tax into revenue, double counting what the tax column already reports separately
CREATE OR REPLACE TABLE stg_europe AS
SELECT order_key, cust_key, CAST(order_date AS DATE) AS order_date,
       CAST(net_price + tax_amount AS DECIMAL(18, 2)) AS net_price,
       CAST(tax_amount AS DECIMAL(18, 2)) AS tax_amount,
       'europe' AS source
FROM feed_europe
