
from dataclasses import asdict, dataclass
from typing import Literal

from app.extraction.models import TimesheetData


Severity = Literal["low", "medium", "high"]


@dataclass
class RuleViolation:
    severity: Severity
    message: str
    field: str | None = None


def validate_timesheet(
    timesheet: TimesheetData,
) -> list[RuleViolation]:
    """Run deterministic checks against extracted timesheet data."""

    violations: list[RuleViolation] = []

    # TS001: Required identity information.
    if not timesheet.employee_name:
        violations.append(
            RuleViolation(
                severity="medium",
                message="Employee name is missing.",
                field="employee_name",
            )
        )

    if not timesheet.employee_id:
        violations.append(
            RuleViolation(
                severity="medium",
                message="Employee ID is missing.",
                field="employee_id",
            )
        )

    # TS002 and TS003: Daily hours.
    for index, entry in enumerate(timesheet.daily_entries):
        hours = entry.hours_worked

        if hours is None:
            continue

        if hours < 0:
            violations.append(
                RuleViolation(
                    severity="high",
                    message=f"Daily hours cannot be negative: {hours}.",
                    field=f"daily_entries[{index}].hours_worked",
                )
            )
            continue

        if hours > 16:
            violations.append(
                RuleViolation(
                    severity="high",
                    message=f"Daily hours exceed 16: {hours}.",
                    field=f"daily_entries[{index}].hours_worked",
                )
            )
        elif hours > 8:
            violations.append(
                RuleViolation(
                    severity="medium",
                    message=(
                        f"Daily hours exceed 8 ({hours}); "
                        "check applicable overtime rules."
                    ),
                    field=f"daily_entries[{index}].hours_worked",
                )
            )

    # TS008: Compare extracted daily hours with the reported weekly total.
    known_daily_hours = [
        entry.hours_worked
        for entry in timesheet.daily_entries
        if entry.hours_worked is not None
    ]

    if (
        timesheet.reported_total_hours is not None
        and known_daily_hours
        and len(known_daily_hours) == len(timesheet.daily_entries)
    ):
        daily_total = round(sum(known_daily_hours), 2)
        weekly_total = round(timesheet.reported_total_hours, 2)

        if daily_total != weekly_total:
            violations.append(
                RuleViolation(
                    severity="medium",
                    message=(
                        f"Daily total ({daily_total}) does not match "
                        f"reported weekly total ({weekly_total})."
                    ),
                    field="reported_total_hours",
                )
            )

    return violations


def build_validation_report(
    timesheet: TimesheetData,
) -> dict:
    violations = validate_timesheet(timesheet)

    return {
        "employee_name": timesheet.employee_name,
        "employee_id": timesheet.employee_id,
        "week_ending": timesheet.week_ending,
        "status": (
            "human_review_required" if violations else "passed"
        ),
        "violations": [asdict(item) for item in violations],
    }
