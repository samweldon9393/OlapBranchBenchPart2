# OlapBranchBench

Benchmarks of data branching across three backends (Bauplan, Databricks, Snowflake) over the same dataset, in two parts.

**Part 1** measures the branching primitives on their own: each run times the creation and the deletion of a branch (or the per-backend equivalent) and appends the measurements to a single parquet file.

**Part 2** measures the same backends on end-to-end workloads that contain branching, so the primitive is timed alongside the work that surrounds it in practice.

## Table of contents

- [Overview](#overview)
- [Setup](#setup)
- [Dataset](#dataset)
- [Part 1: branching primitives](#part-1-branching-primitives)
  - [Running a benchmark](#running-a-benchmark)
  - [Branching across backends](#branching-across-backends)
  - [Results](#results)
- [Part 2: end-to-end workloads](#part-2-end-to-end-workloads)
  - [Running a workload](#running-a-workload)
  - [Data engineering](#data-engineering)
  - [WAP](#wap)
  - [Fixtures](#fixtures)
  - [What is measured](#what-is-measured)
  - [Status](#status)

## Overview

The repository is a small Typer CLI. A backend-agnostic engine runs an operation N times (serial or across worker threads, with optional jitter) and times only the operation itself. Each backend supplies a thin wrapper that knows how to open a client and how to create and delete a branch; everything else (orchestration, timing, output) is shared. A second (optional) command generates the TPC-H dataset with different scale factors, used as the common input.

Part 2 keeps that shape and widens it. A workload is data — a fixture, a DAG of targets, and a SQL check per target — and every backend implements the same operations behind one protocol, so the loop and the workload definitions are each written once.

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/). Install the dependencies with:

```
uv sync
```

Credentials are read from a `.env` file (copy `.env.example` and fill in the values for the backends).

Bauplan needs an API key (see [this guide](https://docs.bauplanlabs.com/tutorial/installation) for a tutorial on how to get one):

```
BAUPLAN_API_KEY=
```

Snowflake uses key-pair authentication, which avoids interactive MFA on parallel runs:

```
SF_ACCOUNT=
SF_USER=
SF_ROLE=
SF_WAREHOUSE=
SF_PRIVATE_KEY_FILE=
```

Run this in a Snowflake worksheet to read the first four values directly:

```sql
SELECT
    CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME() AS sf_account,
    CURRENT_USER()      AS sf_user,
    CURRENT_ROLE()      AS sf_role,
    CURRENT_WAREHOUSE() AS sf_warehouse;
```

Then generate a key pair and register the public key on your user:

```
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
```

Then, in a Snowflake worksheet, run 
```
ALTER USER <your_user> SET RSA_PUBLIC_KEY='<body of rsa_key.pub, without the BEGIN/END lines>
``` 
and point `SF_PRIVATE_KEY_FILE` at `rsa_key.p8`.

Databricks uses a SQL warehouse and a personal access token:

```
DATABRICKS_SERVER_HOSTNAME=
DATABRICKS_HTTP_PATH=
DATABRICKS_TOKEN=
```

The hostname, HTTP path and token come from the SQL warehouse "Connection details" page; you can fetch them from `Compute` > `<YOUR_WAREHOUSE>` > `Connection details`.

## Dataset

All three backends branch the same TPC-H scale-factor-1 dataset, composed of 8 tables in total (`customer`, `lineitem`, `nation`, `orders`, `part`, `partsupp`, `region`, `supplier`). If your warehouses already hold it, there is nothing to do.

Otherwise generate it locally with DuckDB:

```
uv run main.py data tpch --sf 1
```

This writes one parquet per table to `data/tpch_sf1/` (as a check, for SF1, `lineitem` has 6,001,215 rows). Upload those files to object storage and load them into Bauplan, Snowflake and Databricks.

These same 8 tables are all part 2 needs as well. Everything else it works on is derived from them inside the warehouse at the start of a run, so there is nothing extra to generate or upload.

## Part 1: branching primitives

### Running a benchmark

```
uv run main.py bench bauplan <BRANCH>
uv run main.py bench snowflake <DATABASE>
uv run main.py bench databricks <CATALOG>.<SCHEMA>
```

The first argument is the backend and the second is what to branch from: a ref for bauplan, a source database for Snowflake, a source `catalog.schema` for Databricks. The options are `--n-branches`, `--parallel` / `--no-parallel`, `--n-workers`, `--jitter-ms`, `--chained`, `--verify-clone`, `--namespace` and `--results-path`; see `uv run main.py bench --help`. `--chained` makes each branch start from the previous one instead of from the fixed base (sequential only). Each run appends one row per timed operation to the results parquet, recording `duration_s` plus the wall-clock `started_at` and `ended_at` separately for the create and the delete.

`--verify-clone` checks, after each branch is created and before it is deleted, that every source table is present in the new branch, and aborts the run if any is missing. The check runs outside the timed region, so it does not affect the measurements.

### Branching across backends

The three platforms expose different primitives, and the benchmark maps each to a create and a delete operation that are timed separately.

Bauplan has native git-for-data branches, so it calls `create_branch` and `delete_branch` directly on a ref. Notice that, unlike Snowflake and Databricks, Bauplan branches the _entire_ lakehouse, not just this dataset.

Snowflake has no branches; its analog is a zero-copy database clone. Create is `CREATE DATABASE <name> CLONE <source>` and delete is `DROP DATABASE`. A single statement covers the whole database.

Databricks only offers a per-table shallow clone, with no database or schema level clone. A branch is therefore a new schema into which every table of the source schema is shallow-cloned, and delete is `DROP SCHEMA ... CASCADE`. Notice that Databricks does _not_ allow the `--chained` flag.

### Results

Speedup is based on atomic create p95, relative to Bauplan within the same execution mode. Testing was carried out from the same region as each provider: `us-east-1` for Bauplan and Snowflake, `us-west-2` for Databricks.

**Serial**

| Setup | Atomic create avg (s) | Atomic create p95 (s) | Bauplan relative speedup |
|---|---|---|---|
| bauplan | 0.083 | 0.099 | 1.0x |
| snowflake | 8.406 | 9.866 | 99.7x |
| snowflake-iceberg | 10.315 | 11.652 | 117.7x |
| databricks | 24.950 | 26.400 | 266.7x |

**Parallel**

| Setup | Atomic create avg (s) | Atomic create p95 (s) | Bauplan relative speedup |
|---|---|---|---|
| bauplan | 0.195 | 0.827 | 1.0x |
| snowflake | 8.430 | 9.713 | 11.7x |
| snowflake-iceberg | 9.989 | 11.691 | 14.1x |
| databricks | 34.033 | 45.656 | 55.2x |

**Chained**

| Setup | Atomic create avg (s) | Atomic create p95 (s) | Bauplan relative speedup |
|---|---|---|---|
| bauplan | 0.091 | 0.134 | 1.0x |
| snowflake | 10.119 | 12.176 | 90.9x |
| snowflake-iceberg | 10.371 | 13.024 | 97.2x |
| databricks | N/A | N/A | N/A |

Databricks is `N/A` for chained because it does not allow for chained shallow copies.

## Part 2: end-to-end workloads

Part 1 times a branch on its own. Part 2 puts branching inside the work it normally accompanies: a mock agent trying to get something right, branching before each attempt, checking the result, and throwing the branch away when the attempt was wrong.

Every workload runs the same loop:

```
create root branch off the base ref     (untimed)
build the workload's fixture on it      (untimed)
  ↓
repeat until the work is done, or the step budget runs out:
    branch off a committed branch
    attempt one target on it
    check every target built so far
    if every check passed, keep the branch: merge it back, or leave it for others to build on
    otherwise delete it and try again from the last good state
  ↓
delete every branch the run created     (untimed)
```

A step is accepted only when every check on it passed, which is the same rule for all workloads. Because only accepted steps are kept, the tree a run builds is made of successful work, and its shape is set by three numbers: how many branches come off the root, how many off each branch after that, and how deep it may go. A chain is a fanout of one at every level; a star is a depth of one. Any number of workers can attempt steps at once.

### Running a workload

Each workload is a subcommand, carrying the shape and concurrency it is normally run at:

```
uv run main.py macrobench data-engineering bauplan <REF>
uv run main.py macrobench wap bauplan <REF>
```

The first argument is the backend and the second is what the root branch is cut from. Every setting is also an option — `--seed`, `--p-correct`, `--root-fanout`, `--inner-fanout`, `--max-depth`, `--max-steps`, `--n-workers`, `--merge-on-commit`, `--namespace`, `--cache` and `--results-path`; see `uv run main.py macrobench <workload> --help`.

`--seed` makes a single-worker run reproducible: it drives both which target the agent attempts and whether that attempt is a correct one, so the same seed replays the same successes and dead ends. `--p-correct` is the chance any one attempt is correct, so lowering it means more dead ends and a longer walk to the same finished state. With several workers, thread timing decides which branch gets extended when, so runs stop being exactly reproducible.

`--cache` is off by default and always passed explicitly rather than left for the platform to resolve, since these workloads rebuild identical artifacts constantly and a warm cache would time a lookup instead of the work.

### Data engineering

A chain, one worker. Three regional feeds of the same orders disagree with each other the way real multi-source feeds do — one reports price before discount, one after and with an extra tax column, one uses raw column names and repeats about 1% of its rows. The agent standardizes each feed, unions them into one table tagged by source, and builds a revenue mart by nation and quarter on top:

```
feed_americas ─→ stg_americas ─┐
feed_europe   ─→ stg_europe   ─┼─→ orders_unified ─→ revenue_by_nation_quarter
feed_asia     ─→ stg_asia     ─┘
```

Each model has a correct and a broken version, and a target passes when it reproduces its gold table exactly. The agent only attempts a target whose inputs already pass, so it walks up the DAG and never builds on a broken parent. Accepted steps stack into a single deep chain, published once at the end.

### WAP

A star, eight workers. Batches of orders arrive; each is appended to the published table on its own branch off the root, audited there, then merged back into the root or deleted. Three audits run on the batch just appended: order keys are unique, no customer key is null, and every customer exists. The broken version of a batch appends its rows twice, which the uniqueness audit catches.

Because the root is shared, this is where merge contention shows up. Bauplan resolves merges per key, so when several workers publish into the same root only the first wins; the losers' branches are anchored to a commit the root has moved past and cannot be merged again no matter how many times they retry. Such a step is redone from scratch off the advanced root instead — re-branch, re-append, re-audit, merge — and the results record how many attempts it took. That redone work is the cost of contention, and it is what this workload mostly measures.

### Fixtures

Whatever a workload starts from is built inside the warehouse during setup, not shipped as parquet and uploaded:

```
create root branch off main         TPC-H only, untouched
  ↓
run the fixture on the root branch  untimed
  ↓
step 1 branches off the root and inherits all of it
```

Setup fails loudly if the fixture does not leave every table it owes. For data engineering the fixture builds the three drifted feeds and the gold tables they are checked against; gold is computed from the untouched TPC-H tables rather than from the feeds, so reproducing it means the drift was genuinely undone rather than a pipeline agreeing with itself. For WAP it builds the stream of batched orders and seeds the table they land in.

### What is measured

Each timed operation appends one row: `create_branch`, `mutate`, `evaluate`, `delete_branch` and `merge_branch`, plus one `<workload>_workload` row covering the whole timed region so a run's end-to-end cost is queryable without re-adding the parts and the gaps between them.

Everything around the loop is deliberately outside it — opening clients, cutting the root branch, building the fixture, and the teardown that deletes the run's branches afterwards. Branch names are built outside the measured region too, the same way part 1 does it.

Rows land in `results/macrobench.parquet` by default, carrying `backend`, `workload`, `exp_id`, `step`, `operation`, `target`, `branch_name`, `duration_s`, `started_at`, `ended_at`, `parent`, `depth`, `accepted`, `correct`, `params`, `failed_checks`, `attempts`, `committed`, `steps`, and the run's full `config` as a struct. Merge rows also carry `merge_attempt`, the try they belonged to. As in part 1, results are appended with `how="diagonal_relaxed"`, so adding a field does not break older files.

### Status

Implemented: the data engineering and WAP workloads, on Bauplan. Running either against `snowflake` or `databricks` raises `NotImplementedError` rather than pretending.

Not yet done: the other two workloads (data science, fixing bad data), the Snowflake and Databricks adapters, and schema evolution as a step — every attempt currently changes values, not shapes. Databricks is expected to fail the chained workload at depth 2, since it does not allow chained shallow clones, which is a result about the platform rather than a hole in the harness. No results are published for part 2 yet.
