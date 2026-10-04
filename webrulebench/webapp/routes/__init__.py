"""Bölüm başına Flask blueprint'leri (URL'ler blueprint öneki olmadan, uygulamadakiyle aynıdır)."""
from webrulebench.webapp.routes import (annotation, auth, data, evaluation, groundtruth, llm, pages, reports,  # noqa: F401
                           templates, users)

BLUEPRINTS = [auth.bp, users.bp, pages.bp, data.bp, templates.bp, annotation.bp, groundtruth.bp,
              evaluation.bp, llm.bp, reports.bp]
