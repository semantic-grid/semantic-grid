"""UI specification models for grid and chart rendering."""

from enum import Enum

from pydantic import BaseModel, Field


class ColumnFormatter(str, Enum):
    """Built-in column formatters."""

    TEXT = "text"
    NUMBER = "number"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    DATE = "date"
    DATETIME = "datetime"
    DATETIME_RELATIVE = "datetime_relative"
    BOOLEAN = "boolean"
    ADDRESS = "address"  # Ethereum/crypto address
    HASH = "hash"  # Transaction hash
    URL = "url"
    JSON = "json"


class ColumnSpec(BaseModel):
    """Specification for a single column in the grid."""

    field: str = Field(..., description="Column field name (matches data key)")
    header_name: str | None = Field(default=None, description="Display name for header")
    formatter: ColumnFormatter = Field(
        default=ColumnFormatter.TEXT, description="How to format the column"
    )
    width: int | None = Field(default=None, description="Column width in pixels")
    min_width: int | None = Field(default=None, description="Minimum column width")
    max_width: int | None = Field(default=None, description="Maximum column width")
    sortable: bool = Field(default=True, description="Whether column is sortable")
    filterable: bool = Field(default=True, description="Whether column is filterable")
    hidden: bool = Field(default=False, description="Whether column is hidden by default")

    # Formatter options
    decimals: int | None = Field(default=None, description="Decimal places for numbers")
    currency_symbol: str | None = Field(default=None, description="Currency symbol")
    date_format: str | None = Field(default=None, description="Date format string")
    truncate_length: int | None = Field(
        default=None, description="Max characters before truncating"
    )


class ChartType(str, Enum):
    """Types of charts that can be suggested."""

    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    AREA = "area"
    HISTOGRAM = "histogram"


class ChartSpec(BaseModel):
    """Specification for a chart visualization."""

    chart_type: ChartType = Field(..., description="Type of chart")
    title: str | None = Field(default=None, description="Chart title")
    x_field: str = Field(..., description="Field for X axis")
    y_field: str = Field(..., description="Field for Y axis")
    x_label: str | None = Field(default=None, description="X axis label")
    y_label: str | None = Field(default=None, description="Y axis label")
    color_field: str | None = Field(default=None, description="Field for color grouping")
    size_field: str | None = Field(default=None, description="Field for size (scatter)")


class SortDirection(str, Enum):
    """Sort direction."""

    ASC = "asc"
    DESC = "desc"


class SortSpec(BaseModel):
    """Default sort specification."""

    field: str = Field(..., description="Field to sort by")
    direction: SortDirection = Field(default=SortDirection.ASC, description="Sort direction")


class GroupingSpec(BaseModel):
    """Row grouping specification."""

    enabled: bool = Field(default=False, description="Whether grouping is enabled")
    fields: list[str] = Field(default_factory=list, description="Fields to group by")
    expanded_by_default: bool = Field(default=True, description="Expand groups by default")


class GridSpec(BaseModel):
    """Complete specification for rendering a data grid."""

    columns: list[ColumnSpec] = Field(default_factory=list, description="Column specifications")
    default_sort: SortSpec | None = Field(default=None, description="Default sort")
    grouping: GroupingSpec | None = Field(default=None, description="Row grouping")
    chart_suggestion: ChartSpec | None = Field(
        default=None, description="Suggested chart visualization"
    )
    row_height: int = Field(default=52, description="Row height in pixels")
    density: str = Field(
        default="standard", description="Grid density: compact, standard, comfortable"
    )

    # Features
    enable_export: bool = Field(default=True, description="Enable data export")
    enable_column_menu: bool = Field(default=True, description="Enable column menu")
    enable_quick_filter: bool = Field(default=True, description="Enable quick filter")
