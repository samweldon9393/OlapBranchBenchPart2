{{ config(tags=['de_fixture']) }}

-- Price already net of discount, an extra tax column, and the date as a string
SELECT order_key, cust_key, order_date_str AS order_date, net_price, tax_amount
FROM {{ ref('order_facts') }} WHERE feed = 'europe'
