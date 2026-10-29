"""CSV label import. Columns are exactly item_id, q1, q2."""
import csv
import io

Q1 = {"yes": "Yes", "no": "No", "unsure": "Unsure"}
Q2 = {"real fix": "Real fix", "hides it": "Hides it", "unsure": "Unsure"}
HEADER = ["item_id", "q1", "q2"]
MAX_BYTES = 1_048_576


class CsvError(ValueError):
    pass


def parse_labels(raw: bytes) -> list[dict]:
    if len(raw) > MAX_BYTES:
        raise CsvError("CSV uploads are limited to 1 MB.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CsvError("CSV must be UTF-8.") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or [name.strip() for name in reader.fieldnames] != HEADER:
        raise CsvError("CSV columns must be exactly item_id, q1, q2.")
    rows = []
    for index, row in enumerate(reader, start=2):
        item_id = (row.get("item_id") or "").strip()
        q1 = (row.get("q1") or "").strip().lower()
        q2 = (row.get("q2") or "").strip().lower()
        if not item_id or q1 not in Q1 or q2 not in Q2:
            raise CsvError(
                f"Row {index} has a missing item or a value outside the allowed answers."
            )
        rows.append({"item_id": item_id, "q1": Q1[q1], "q2": Q2[q2]})
    if not rows:
        raise CsvError("CSV has no data rows.")
    return rows
