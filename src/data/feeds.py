from pathlib import Path

import duckdb

FEEDS = ("americas", "europe", "asia")

GOLD_TABLES = (
    "gold_orders_unified",
    "gold_revenue_by_nation_quarter",
)

# Tables read from the generated TPC-H parquet; lineitem supplies the money columns,
# customer/nation/region route each order to a feed
SOURCE_TABLES = ("orders", "lineitem", "customer", "nation", "region")

# TPC-H has five regions and we want three feeds, so the split is the usual AMER/EMEA/APAC one:
# the "europe" feed is really EMEA and also carries AFRICA and MIDDLE EAST
FEED_BY_REGION = """
    CASE r.r_name
        WHEN 'AMERICA' THEN 'americas'
        WHEN 'ASIA' THEN 'asia'
        ELSE 'europe'
    END
"""

# One row per order, at the canonical semantics every feed is a distorted view of.
#
# The three money columns are each rounded to cents *before* anything is derived from them, so
# that the per-feed encodings below are exact rearrangements rather than lossy ones: americas
# stores gross and (gross - net), asia stores (net + tax) and tax. Both recover net_price to the
# cent, which is what lets the pipeline's output be compared to gold for equality instead of
# within a tolerance.
ORDER_FACTS_SQL = f"""
CREATE OR REPLACE VIEW order_facts AS
WITH line_agg AS (
    SELECT
        l_orderkey,
        CAST(round(sum(l_extendedprice), 2) AS DECIMAL(18, 2)) AS gross_price,
        CAST(round(sum(l_extendedprice * (1 - l_discount)), 2) AS DECIMAL(18, 2)) AS net_price,
        CAST(round(sum(l_extendedprice * (1 - l_discount) * l_tax), 2) AS DECIMAL(18, 2)) AS tax_amount
    FROM lineitem
    GROUP BY l_orderkey
)
SELECT
    o.o_orderkey AS order_key,
    o.o_custkey AS cust_key,
    o.o_orderdate AS order_date,
    n.n_name AS nation_name,
    {FEED_BY_REGION} AS feed,
    la.gross_price,
    la.net_price,
    la.tax_amount
FROM orders o
JOIN line_agg la ON la.l_orderkey = o.o_orderkey
JOIN customer c ON c.c_custkey = o.o_custkey
JOIN nation n ON n.n_nationkey = c.c_nationkey
JOIN region r ON r.r_regionkey = n.n_regionkey
"""

# Baseline feed: tidy names, a real DATE, price reported before discount. The discount is carried
# alongside so the staging model has to subtract it to reach the canonical net revenue.
AMERICAS_SQL = """
SELECT
    order_key,
    cust_key,
    order_date,
    gross_price,
    gross_price - net_price AS discount_amount
FROM order_facts
WHERE feed = 'americas'
ORDER BY order_key
"""

# Reports price after discount and adds a tax column the baseline does not have; the date arrives
# as a string, so staging has to parse it before the union can line up.
EUROPE_SQL = """
SELECT
    order_key,
    cust_key,
    strftime(order_date, '%Y-%m-%d') AS order_date,
    net_price,
    tax_amount
FROM order_facts
WHERE feed = 'europe'
ORDER BY order_key
"""

# Raw TPC-H column naming, and "totalprice" means the fully loaded price the way TPC-H itself
# defines it (net of discount, inclusive of tax), so staging has to strip tax back out. Roughly
# 1% of rows are emitted twice, verbatim: hash() keeps the choice deterministic across runs, so
# regenerating the feed does not move the duplicate set.
ASIA_SQL = """
SELECT * FROM (
    SELECT
        order_key AS o_orderkey,
        cust_key AS o_custkey,
        order_date AS o_orderdate,
        net_price + tax_amount AS o_totalprice,
        tax_amount AS o_tax
    FROM order_facts
    WHERE feed = 'asia'
    UNION ALL
    SELECT
        order_key AS o_orderkey,
        cust_key AS o_custkey,
        order_date AS o_orderdate,
        net_price + tax_amount AS o_totalprice,
        tax_amount AS o_tax
    FROM order_facts
    WHERE feed = 'asia' AND hash(order_key) % 100 = 0
)
ORDER BY o_orderkey
"""

FEED_SQL = {
    "americas": AMERICAS_SQL,
    "europe": EUROPE_SQL,
    "asia": ASIA_SQL,
}

# The gold tables are computed straight from the untouched TPC-H tables, never from the feeds, so
# a pipeline that reproduces them has genuinely undone the drift rather than agreed with itself.
GOLD_SQL = {
    # What the unified intermediate should hold: one row per order, deduplicated, tagged by source.
    # Only europe and asia report tax, so it is null for americas rather than silently zero: the
    # union has to keep a column that not every source can fill, which is the realistic case.
    "gold_orders_unified": """
        SELECT
            order_key,
            cust_key,
            order_date,
            net_price,
            CASE WHEN feed = 'americas' THEN NULL ELSE tax_amount END AS tax_amount,
            feed AS source
        FROM order_facts
        ORDER BY order_key
    """,
    # What the mart should hold; nation comes from the dimension tables, which the feeds do not
    # carry. Tax sums over the reporting feeds only, so a nation served purely by americas has none.
    "gold_revenue_by_nation_quarter": """
        SELECT
            nation_name,
            date_trunc('quarter', order_date) AS order_quarter,
            CAST(sum(net_price) AS DECIMAL(18, 2)) AS net_revenue,
            CAST(sum(CASE WHEN feed = 'americas' THEN NULL ELSE tax_amount END) AS DECIMAL(18, 2)) AS tax_amount,
            count(*) AS order_count
        FROM order_facts
        GROUP BY nation_name, order_quarter
        ORDER BY nation_name, order_quarter
    """,
}


def generate_feeds(tpch_dir: str | Path, out_dir: str | Path) -> Path:
    """Split TPC-H orders into regional feeds with deliberate schema drift."""
    source = Path(tpch_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()

    # Read the TPC-H parquet in place rather than loading it, so this stays cheap at larger scale factors
    for table in SOURCE_TABLES:
        parquet = source / f"{table}.parquet"
        if not parquet.exists():
            raise FileNotFoundError(f"{parquet} not found; run `data tpch` first to generate it")
        con.execute(f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM read_parquet('{parquet}')")

    con.execute(ORDER_FACTS_SQL)

    for feed in FEEDS:
        con.execute(f"COPY ({FEED_SQL[feed]}) TO '{out / f'feed_{feed}.parquet'}' (FORMAT PARQUET)")

    for table in GOLD_TABLES:
        con.execute(f"COPY ({GOLD_SQL[table]}) TO '{out / f'{table}.parquet'}' (FORMAT PARQUET)")

    con.close()

    return out
