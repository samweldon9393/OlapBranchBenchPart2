-- Price is already net of discount and carries straight through; the date arrives as a string and
-- has to be parsed before the union can line up
CREATE OR REPLACE TABLE stg_europe AS
SELECT order_key, cust_key, CAST(order_date AS DATE) AS order_date,
       CAST(net_price AS DECIMAL(18, 2)) AS net_price,
       CAST(tax_amount AS DECIMAL(18, 2)) AS tax_amount,
       'europe' AS source
FROM feed_europe
