def save_schema_metadata(engine, dataset_id, schema_name, table_metadata):
    """Store schema metadata for later use in LLM prompts."""
    with engine.connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dataset_metadata (
                dataset_id TEXT PRIMARY KEY,
                schema_name TEXT,
                table_metadata JSONB
            )
        """)
        conn.execute(
            """
            INSERT INTO dataset_metadata
            (dataset_id, schema_name, table_metadata)
            VALUES (%s, %s, %s)
            ON CONFLICT (dataset_id) DO UPDATE SET
            schema_name = EXCLUDED.schema_name,
            table_metadata = EXCLUDED.table_metadata
            """,
            (dataset_id, schema_name, table_metadata)
        )


def detect_relationships(tables_dfs):
    relationships = []
    table_names = list(tables_dfs.keys())

    for i in range(len(table_names)):
        for j in range(i + 1, len(table_names)):
            t1, t2 = table_names[i], table_names[j]
            df1, df2 = tables_dfs[t1], tables_dfs[t2]

            common_cols = set(df1.columns).intersection(set(df2.columns))
            for col in common_cols:
                if df1[col].notna().sum() > 0 and df2[col].notna().sum() > 0:
                    match_ratio = df1[col].isin(df2[col]).mean()
                    reverse_ratio = df2[col].isin(df1[col]).mean()

                    if match_ratio > 0.8:
                        relationships.append({
                            "from_table": t1,
                            "from_column": col,
                            "to_table": t2,
                            "to_column": col,
                            "type": "foreign_key"
                        })
                    elif reverse_ratio > 0.8:
                        relationships.append({
                            "from_table": t2,
                            "from_column": col,
                            "to_table": t1,
                            "to_column": col,
                            "type": "foreign_key"
                        })
    return relationships
