"""Email drivers. Importing the package registers all of them."""
from providers.email import console, postmark, resend, sendgrid, smtp  # noqa: F401
