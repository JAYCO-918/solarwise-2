"""Clients of external data services.

Every service here is optional.  When one cannot be reached the caller receives
an explicit :class:`IntegrationError`; nothing is ever substituted for the data
that could not be fetched.
"""

from solarwise.integrations.base import IntegrationError, IntegrationFailure

__all__ = ["IntegrationError", "IntegrationFailure"]
