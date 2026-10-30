
import argparse
import json
import sys
from pathlib import Path

from document_extration import build_source_text
from timesheet_extractor import extract_timesheet_fields
from rules import build_validation_report


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract and validate timesheet data."
    )

    parser.add_argument(
        "--file",
        help="Path to a timesheet document.",
    )

    parser.add_argument(
        "--email-body",
        help="Timesheet information from the email body.",
    )

    parser.add_argument(
        "--output",
        default="extracted_timesheet.json",
        help="Output JSON filename.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    try:
        # 1. Define the output path before using it.
        output_path = Path(args.output)

        # 2. Extract text from the document and/or email body.
        source_text = build_source_text(
            file_path=args.file,
            email_body=args.email_body,
        )

        # 3. Extract structured timesheet fields using the LLM.
        timesheet = extract_timesheet_fields(source_text)

        # 4. Validate the extracted data using deterministic rules.
        validation_report = build_validation_report(timesheet)

        # 5. Combine the results into one dictionary.
        output = {
            "timesheet": timesheet.model_dump(mode="json"),
            "validation": validation_report,
            "source_text": source_text,
        }

        # 6. Save the JSON file.
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path.write_text(
            json.dumps(
                output,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # 7. Print the results.
        print(
            json.dumps(
                output,
                indent=2,
                ensure_ascii=False,
            )
        )

        print(f"\nSaved to: {output_path.resolve()}")

    except Exception as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

