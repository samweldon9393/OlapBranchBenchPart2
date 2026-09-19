{{ config(tags=['de_fixture']) }}

-- Baseline feed: tidy names, a real DATE, price before discount, and no tax at all
SELECT order_key, cust_key, order_date, gross_price, discount_amount
FROM {{ ref('order_facts') }} WHERE feed = 'americas'
