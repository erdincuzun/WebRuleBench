"""One Flask blueprint per section (URLs have no blueprint prefix and are the same as in the application)."""
from webrulebench.webapp.routes import (annotation, auth, data, evaluation, groundtruth, llm, pages, reports,  # noqa: F401
                           templates, users)

BLUEPRINTS = [auth.bp, users.bp, pages.bp, data.bp, templates.bp, annotation.bp, groundtruth.bp,
              evaluation.bp, llm.bp, reports.bp]
