import os
import time


RUN_STARTED_AT_ENV = "SHORTFORM_RUN_STARTED_AT_EPOCH"
RUN_DEADLINE_ENV = "SHORTFORM_RUN_DEADLINE_EPOCH"
PRODUCTION_DEADLINE_ENV = "SHORTFORM_PRODUCTION_DEADLINE_EPOCH"
STAGE_DEADLINE_ENV = "SHORTFORM_STAGE_DEADLINE_EPOCH"
THEME_DEADLINE_ENV = "SHORTFORM_THEME_DEADLINE_EPOCH"


def _env_float(name, default=0.0):
    try:
        return float(os.getenv(name, default) or default)
    except (TypeError, ValueError):
        return float(default)


def configure_run_budget(max_runtime_hours=12.0, upload_reserve_minutes=75.0, now=None):
    now = float(now if now is not None else time.time())
    hours = max(0.0, float(max_runtime_hours or 0.0))
    reserve_seconds = max(0.0, float(upload_reserve_minutes or 0.0) * 60.0)

    os.environ[RUN_STARTED_AT_ENV] = f"{now:.6f}"
    clear_work_scope()

    if hours <= 0:
        os.environ.pop(RUN_DEADLINE_ENV, None)
        os.environ.pop(PRODUCTION_DEADLINE_ENV, None)
        return {
            "enabled": False,
            "started_at": now,
            "run_deadline": 0.0,
            "production_deadline": 0.0,
            "upload_reserve_seconds": 0.0,
        }

    run_deadline = now + hours * 3600.0
    production_deadline = max(now, run_deadline - reserve_seconds)
    os.environ[RUN_DEADLINE_ENV] = f"{run_deadline:.6f}"
    os.environ[PRODUCTION_DEADLINE_ENV] = f"{production_deadline:.6f}"
    return {
        "enabled": True,
        "started_at": now,
        "run_deadline": run_deadline,
        "production_deadline": production_deadline,
        "upload_reserve_seconds": reserve_seconds,
    }


def deadline_epoch(production=True):
    name = PRODUCTION_DEADLINE_ENV if production else RUN_DEADLINE_ENV
    deadlines = [max(0.0, _env_float(name, 0.0))]

    if production:
        deadlines.extend([
            max(0.0, _env_float(STAGE_DEADLINE_ENV, 0.0)),
            max(0.0, _env_float(THEME_DEADLINE_ENV, 0.0)),
        ])

    active = [deadline for deadline in deadlines if deadline > 0]
    return min(active) if active else 0.0


def set_stage_deadline(deadline=0.0):
    deadline = max(0.0, float(deadline or 0.0))

    if deadline:
        os.environ[STAGE_DEADLINE_ENV] = f"{deadline:.6f}"
    else:
        os.environ.pop(STAGE_DEADLINE_ENV, None)


def set_theme_deadline(deadline=0.0):
    deadline = max(0.0, float(deadline or 0.0))

    if deadline:
        os.environ[THEME_DEADLINE_ENV] = f"{deadline:.6f}"
    else:
        os.environ.pop(THEME_DEADLINE_ENV, None)


def clear_work_scope():
    os.environ.pop(STAGE_DEADLINE_ENV, None)
    os.environ.pop(THEME_DEADLINE_ENV, None)


def weighted_slice_deadline(remaining_stage_weights, current_weight, now=None):
    now = float(now if now is not None else time.time())
    global_remaining = remaining_seconds(production=True, now=now)

    if global_remaining == float("inf"):
        return 0.0

    denominator = max(float(current_weight or 0.0), float(remaining_stage_weights or 0.0))

    if denominator <= 0:
        return now

    allocation = global_remaining * max(0.0, float(current_weight or 0.0)) / denominator
    return now + allocation


def fair_slice_deadline(scope_deadline, remaining_items, now=None):
    now = float(now if now is not None else time.time())
    scope_deadline = max(0.0, float(scope_deadline or 0.0))

    if scope_deadline <= 0:
        return 0.0

    available = max(0.0, scope_deadline - now)
    return now + available / max(1, int(remaining_items or 1))


def remaining_seconds(production=True, now=None):
    deadline = deadline_epoch(production=production)

    if deadline <= 0:
        return float("inf")

    current = float(now if now is not None else time.time())
    return max(0.0, deadline - current)


def can_start_work(estimated_seconds=0.0, production=True, safety_seconds=30.0):
    remaining = remaining_seconds(production=production)

    if remaining == float("inf"):
        return True

    needed = max(0.0, float(estimated_seconds or 0.0)) + max(0.0, float(safety_seconds or 0.0))
    return remaining >= needed


def budget_exhausted(production=True):
    return not can_start_work(production=production, safety_seconds=0.0)


def format_remaining(production=True):
    remaining = remaining_seconds(production=production)

    if remaining == float("inf"):
        return "unlimited"

    hours, remainder = divmod(int(remaining), 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m"

    if minutes:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"
