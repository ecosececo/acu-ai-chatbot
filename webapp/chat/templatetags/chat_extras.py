"""Custom template tags for the chat app."""

from django import template

register = template.Library()


@register.filter
def truncate_chars(value, max_length):
    """Truncate a string to a maximum number of characters."""
    if len(str(value)) > max_length:
        return str(value)[:max_length] + "..."
    return value
