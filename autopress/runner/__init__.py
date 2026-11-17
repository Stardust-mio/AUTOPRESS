# OWNED BY G4
"""Runner engine (G4): run control, result classification, step execution, the run session
(GUI-thread facade + worker QThread), preflight checks and click/region preview.

Public modules: ``control`` (RunControl, StopRequested), ``classify`` (classify_text), ``engine``
(RunSession), ``preflight`` (run_preflight), ``preview`` (preview_profile). Internal: ``backend``
(Backend protocol + RealBackend), ``steps`` (one step + capture rules), ``worker`` (Runner: the
per-code loop in the worker thread), ``waits`` (pauses, waits, stops), ``shared`` (state shared
with the GUI thread), ``messages`` (localized texts)."""
