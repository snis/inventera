#!/usr/bin/env python3
"""
Migration script to add location and store columns and populate them
with user's updated data from Grocy.
"""

import os
import sqlite3

MAPPINGS = [
    {"name": "Förkläde (dusch)", "store": "Assistansbolaget", "location": "Förråd"},
    {"name": "Handskar (L)", "store": "Assistansbolaget", "location": "Förråd"},
    {"name": "Handskar (M)", "store": "Assistansbolaget", "location": "Förråd"},
    {"name": "Handsprit", "store": "Assistansbolaget", "location": "Förråd"},
    {"name": "Handtvål", "store": "Assistansbolaget", "location": "Förråd"},
    {"name": "Toalettpapper", "store": "Assistansbolaget", "location": "Förråd"},
    {"name": "YT dess", "store": "Assistansbolaget", "location": "Förråd"},
    {"name": "Canoderm (lotion)", "store": "Apoteket", "location": "Badrum"},
    {"name": "Dusch-tvål/olja", "store": "Apoteket", "location": "Badrum"},
    {"name": "Handkräm", "store": "Assistansbolaget", "location": "Förråd"},
    {"name": "Rakhyvelblad", "store": "ICA", "location": "Badrum"},
    {"name": "Raklödder", "store": "ICA", "location": "Badrum"},
    {"name": "Schampo", "store": "Apoteket", "location": "Badrum"},
    {"name": "Tvättlappar (torra)", "store": "ICA", "location": "Badrum"},
    {"name": "Våtservetter", "store": "ICA", "location": "Sovrumsgarderob"},
    {"name": "Kran (kateter)", "store": "1177 / Hjälpmedel", "location": "Badrum"},
    {"name": "Plåster", "store": "1177 / Hjälpmedel", "location": "Badrum"},
    {"name": "Underlägg", "store": "1177 / Hjälpmedel", "location": "SkjutdörrsGarderob"},
    {"name": "Urinpåse (kort)", "store": "1177 / Hjälpmedel", "location": "Förråd"},
    {"name": "Urinpåse (natt)", "store": "1177 / Hjälpmedel", "location": "Förråd"},
    {"name": "Baklofen", "store": "Apoteket", "location": "Medicinlåda"},
    {"name": "Effortil", "store": "Apoteket", "location": "Medicinlåda"},
    {"name": "Microlax", "store": "Apoteket", "location": "Medicinlåda"},
    {"name": "Movicol", "store": "Apoteket", "location": "Medicinlåda"},
    {"name": "Nässpray", "store": "Apoteket", "location": "Medicinlåda"},
    {"name": "Scheriproct", "store": "Apoteket", "location": "Medicinlåda"},
    {"name": "Solifenacin (Vesicare)", "store": "Apoteket", "location": "Medicinlåda"},
    {"name": "Ajax (golv)", "store": "ICA", "location": "SkjutdörrsGarderob"},
    {"name": "Diskmaskinstabletter", "store": "ICA", "location": "Kök"},
    {"name": "Diskmedel", "store": "ICA", "location": "Kök"},
    {"name": "Disktrasor", "store": "ICA", "location": "Kök"},
    {"name": "Hushållspapper", "store": "ICA", "location": "Förråd"},
    {"name": "Klorin", "store": "ICA", "location": "Förråd"},
    {"name": "Sköljmedel", "store": "ICA", "location": "Förråd"},
    {"name": "Soppåsar", "store": "ICA", "location": "Kök"},
    {"name": "Tvättmedel (flytande)", "store": "ICA", "location": "SkjutdörrsGarderob"},
    {"name": "WC rengöring (WC Duck)", "store": "ICA", "location": "Förråd"},
]


def migrate(db_path="instance/db.sqlite3"):
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    cols = [col[1] for col in c.execute("PRAGMA table_info(item);").fetchall()]
    if "location" not in cols:
        print("Adding column 'location'...")
        c.execute("ALTER TABLE item ADD COLUMN location VARCHAR(32);")
    if "store" not in cols:
        print("Adding column 'store'...")
        c.execute("ALTER TABLE item ADD COLUMN store VARCHAR(32);")
    if "task_id" not in cols:
        c.execute("ALTER TABLE item ADD COLUMN task_id VARCHAR(64);")
    if "added_to_task" not in cols:
        c.execute("ALTER TABLE item ADD COLUMN added_to_task DATETIME;")

    updated = 0
    for m in MAPPINGS:
        c.execute(
            "UPDATE item SET store = ?, location = ? WHERE TRIM(name) = TRIM(?)",
            (m["store"], m["location"], m["name"]),
        )
        updated += c.rowcount

    conn.commit()
    conn.close()
    print(f"Migration completed! Updated {updated} items.")


if __name__ == "__main__":
    migrate()
