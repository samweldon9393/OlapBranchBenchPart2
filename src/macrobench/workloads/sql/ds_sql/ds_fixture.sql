-- The data science fixture: the catalogue of candidate features every branch draws from, with what
-- each is built from.
CREATE OR REPLACE TABLE ds_candidates AS
SELECT column1 AS feature, column2 AS source FROM VALUES
    ('ship_delay', 'days from o_orderdate to l_shipdate'),
    ('quantity', 'l_quantity'),
    ('discount', 'l_discount'),
    ('priority', 'leading digit of o_orderpriority')
