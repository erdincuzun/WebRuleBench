"""
webapp — WebRuleBench web application (Flask).

  core.py      application object, paths, session/authorization, language, shared helpers
  routes/      one blueprint per section (auth, users, pages, data, templates, annotation,
               groundtruth, evaluation, llm, reports)
  app.py       registers the blueprints and starts the server:  webrulebench serve  (python -m webrulebench.webapp)
  templates/ static/ i18n/   user interface
  manage_users.py            user management from the command line
"""
