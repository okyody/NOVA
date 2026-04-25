from apps.nova_runtime.bootstrap import build_role_plan, create_worker_app


def test_build_role_plan_for_api():
    plan = build_role_plan("api")
    assert plan.run_bus is False
    assert plan.run_cognitive is False
    assert plan.run_generation is False


def test_build_role_plan_for_cognitive():
    plan = build_role_plan("cognitive")
    assert plan.run_bus is True
    assert plan.run_cognitive is True
    assert plan.run_perception is False


def test_create_worker_app_sets_role():
    app = create_worker_app("generation")
    assert app.settings.runtime.role == "generation"
