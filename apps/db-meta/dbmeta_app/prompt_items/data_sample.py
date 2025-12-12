import json

from sqlalchemy import inspect, text

from dbmeta_app.api.model import PromptItem, PromptItemType
from dbmeta_app.wh_db.db import get_db


# deprecated
def get_data_sample_prompt_item():
    engine = get_db()
    inspector = inspect(engine)
    sample_data = {}

    with engine.connect() as conn:
        for table in inspector.get_table_names():
            if table.startswith("_"):  # Skip system/internal tables
                continue

            try:
                # Fetch a small number of rows (adjust LIMIT as needed)
                result = conn.execute(text(f"SELECT * FROM {table} LIMIT 5"))
                columns = result.keys()
                rows = [dict(zip(columns, row)) for row in result.fetchall()]

                if rows:
                    sample_data[table] = rows

            except Exception:
                # Log the error and continue
                pass

        sample_data_text = json.dumps(sample_data, indent=2)

    return PromptItem(
        text=sample_data_text,
        prompt_item_type=PromptItemType.data_sample,
        score=100_000,
    )
