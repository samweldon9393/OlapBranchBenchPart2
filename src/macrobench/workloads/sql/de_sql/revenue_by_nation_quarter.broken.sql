-- Buckets by year, collapsing four quarters into a single row
CREATE OR REPLACE TABLE revenue_by_nation_quarter AS
SELECT n.n_name AS nation_name,
       DATE_TRUNC('year', u.order_date) AS order_quarter,
       CAST(SUM(u.net_price) AS DECIMAL(38, 2)) AS net_revenue,
       CAST(SUM(u.tax_amount) AS DECIMAL(38, 2)) AS tax_amount,
       COUNT(*) AS order_count
FROM orders_unified u
JOIN customer c ON c.c_custkey = u.cust_key
JOIN nation n ON n.n_nationkey = c.c_nationkey
GROUP BY 1, 2
