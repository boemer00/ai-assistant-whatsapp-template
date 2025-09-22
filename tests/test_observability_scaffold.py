import pytest


def test_scaffold_modules_exist():
    import app.obs.context as ctx
    import app.obs.logger as log
    import app.obs.metrics as met
    import app.obs.middleware as mid

    assert hasattr(ctx, "request_id_var")
    assert hasattr(log, "log_event")
    assert hasattr(met, "record_timing")
    assert hasattr(met, "inc_counter")
    assert hasattr(met, "get_metrics_snapshot")
    assert hasattr(mid, "ObservabilityMiddleware")
