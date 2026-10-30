
from pydantic import BaseModel, ConfigDict, Field


class DailyEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    day_label: str | None = Field(default=None, alias="day")
    date: str | None = None

    start_time: str | None = Field(default=None, alias="start")
    end_time: str | None = Field(default=None, alias="end")

    break_minutes: int | None = None
    hours_worked: float | None = None

    regular_hours_reported: float | None = Field(
        default=None,
        alias="regular",
    )
    overtime_hours_reported: float | None = Field(
        default=None,
        alias="overtime",
    )
    double_time_hours_reported: float | None = Field(
        default=None,
        alias="double_time",
    )

    is_public_holiday_reported: str | bool | None = Field(
        default=None,
        alias="public_holiday",
    )
    pay_code: str | None = None
    notes: str | None = None
    source_excerpt: str | None = None


class TimesheetData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    employee_name: str | None = None
    employee_id: str | None = None
    company_name: str | None = None
    client_name: str | None = None
    project_name: str | None = None
    assignment_id: str | None = None
    week_ending: str | None = None

    daily_entries: list[DailyEntry] = Field(default_factory=list)

    reported_regular_hours: float | None = None
    reported_overtime_hours: float | None = None
    reported_double_time_hours: float | None = None
    reported_total_hours: float | None = None

    approvals: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)
