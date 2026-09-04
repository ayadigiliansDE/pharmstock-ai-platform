from pharmstock.rebuild.bigquery_stage import atomic_replace_sql


def test_sandbox_replace_keeps_clustering_but_disables_partitioning() -> None:
    sql = atomic_replace_sql(
        target_table_id="project.dataset.target",
        staging_table_id="project.dataset.stage",
        source_table="inventory.stock_movement",
        partitioning_enabled=False,
    )
    assert "PARTITION BY" not in sql
    assert "CLUSTER BY `branch_id`, `product_id`, `movement_type`" in sql


def test_production_replace_retains_partition_design() -> None:
    sql = atomic_replace_sql(
        target_table_id="project.dataset.target",
        staging_table_id="project.dataset.stage",
        source_table="inventory.stock_movement",
    )
    assert "PARTITION BY DATE(occurred_at)" in sql
