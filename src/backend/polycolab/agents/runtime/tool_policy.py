"""Tool provenance rules shared by the private API and hosted client."""

DIRECT_TOOL_NAMES = frozenset(
    {
        "write_object_version",
        "create_relation",
        "write_summary",
        "comment_on_object_version",
        "report_progress",
        "review_object_version",
    }
)
VERIFICATION_TOOL_NAMES = frozenset(
    {"submit_verification", "inspect_verification", "cancel_verification"}
)
WRITE_TOOL_NAMES = DIRECT_TOOL_NAMES | {
    "submit_proposal",
    "submit_verification",
    "cancel_verification",
}
