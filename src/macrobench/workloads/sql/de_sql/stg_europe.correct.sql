-- Price is already net of discount and carries straight through; the date arrives as a string and
-- has to be parsed before the union can line up
CREATE OR REPLACE TABLE stg_europe AS
SELECT order_key, cust_key, TO_DATE(order_date, 'YYYY-MM-DD') AS order_date,
       CAST(net_price AS NUMBER(18, 2)) AS net_price,
       CAST(tax_amount AS NUMBER(18, 2)) AS tax_amount,
       'europe' AS source
FROM feed_europe
