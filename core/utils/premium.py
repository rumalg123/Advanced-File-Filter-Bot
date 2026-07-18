"""Consistent user-facing premium and quota status formatting."""

from datetime import date

from core.utils.validators import normalize_expiry_date


def format_user_plan_status(
    user,
    daily_limit: int,
    is_premium_active: bool = False,
    status_message: str | None = None,
    current_date: date | None = None,
) -> str:
    """Format status from stored grant dates and date-scoped quota usage."""
    if is_premium_active:
        status = status_message or "Premium active"
        text = f"✅ <b>Your Status:</b> {status}\n"
        expiry = normalize_expiry_date(
            getattr(user, 'premium_expiry_date', None)
        )
        if expiry:
            text += (
                "📅 <b>Your Expiry:</b> "
                f"{expiry.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            )
        return text

    text = ""
    if status_message:
        text += f"⚠️ <b>Your Status:</b> {status_message}\n"
        text += "📊 <b>Current Plan:</b> Free Plan\n"
    else:
        text += "📊 <b>Your Status:</b> Free Plan\n"

    today = current_date or date.today()
    daily_count = (
        max(0, int(getattr(user, 'daily_retrieval_count', 0) or 0))
        if getattr(user, 'last_retrieval_date', None) == today else 0
    )
    limit = max(0, int(daily_limit))
    remaining = max(0, limit - daily_count)
    text += f"📁 Today's Usage: {daily_count}/{limit}\n"
    text += f"📁 Remaining: {remaining}\n"
    return text
