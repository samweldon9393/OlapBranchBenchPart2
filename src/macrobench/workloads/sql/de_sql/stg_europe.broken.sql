-- Folds tax into revenue, double counting what the tax column already reports separately
CREATE OR REPLACE TABLE stg_europe AS
SELECT order_key, cust_key, TO_DATE(order_date, 'YYYY-MM-DD') AS order_date,
       CAST(net_price + tax_amount AS NUMBER(18, 2)) AS net_price,
       CAST(tax_amount AS NUMBER(18, 2)) AS tax_amount,
       'europe' AS source
FROM feed_europe
