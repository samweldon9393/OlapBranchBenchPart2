-- Takes the reported price as net, forgetting it is quoted before discount
CREATE OR REPLACE TABLE stg_americas AS
SELECT order_key, cust_key, order_date,
       CAST(gross_price AS DECIMAL(18, 2)) AS net_price,
       CAST(NULL AS DECIMAL(18, 2)) AS tax_amount,
       'americas' AS source
FROM feed_americas
