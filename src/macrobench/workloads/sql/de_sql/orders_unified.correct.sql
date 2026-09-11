-- All three feeds belong in the union
CREATE OR REPLACE TABLE orders_unified AS
SELECT order_key, cust_key, order_date, net_price, tax_amount, source FROM stg_americas
UNION ALL
SELECT order_key, cust_key, order_date, net_price, tax_amount, source FROM stg_europe
UNION ALL
SELECT order_key, cust_key, order_date, net_price, tax_amount, source FROM stg_asia
