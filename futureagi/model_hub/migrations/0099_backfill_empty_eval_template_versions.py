"""Backfill EvalTemplateVersion rows whose prompt is empty across every column.

Pre-fix /create-v2/ and /versions/create/ code paths seeded
EvalTemplateVersion rows at form-mount time with empty defaults, before
the user had typed any prompt content. Keystroke /update/ calls then
mutated the live template row only — the version snapshot was never
re-synced. The result: every V1 (and old V2+ from /versions/create/)
that pre-dates the fix has its prompt fields empty, even though the
live template row holds the real content the user actually typed.

The view-layer fix in the same change-set closes this for new versions
(V1 is created lazily on first publish, with content copied from the
live row at that moment). This migration recovers the existing broken
rows by copying the prompt-bearing fields from the live EvalTemplate
into each empty version.

Eval-type aware:
    AgentEvaluator         -> criteria + config.rule_prompt + config.instructions
    CustomPromptEvaluator  -> criteria + config.rule_prompt
                              + (optional) prompt_messages / config.messages
    CustomCodeEval         -> criteria (== code) + config.code + config.language
    Composite              -> skipped (no prompt of its own)

Guarantees:
    - User-owned templates only. System evals are unconditionally excluded;
      their canonical source is the YAML tree applied by seed_system_evals.
    - Non-deleted templates only.
    - Strictly additive: only fills empty fields. Never overwrites or
      deletes existing content. Templates whose live row is also empty
      are left untouched (they have no recoverable source).
    - Idempotent: re-runs match no candidates because filled rows are
      excluded by the emptiness check.

Reverse is a no-op. The live template state we copy from at apply time
may have moved on by the time of a reverse; restoring the empty state
would re-introduce the very bug this migration fixes. Roll back via
database point-in-time restore if absolutely needed.
"""

from django.db import migrations


_SKIP_EVAL_TYPES = frozenset({"CompositeEvaluator", "Composite"})


def _is_composite(template, version) -> bool:
    cs_eval_type = (version.config_snapshot or {}).get("eval_type_id")
    if cs_eval_type and cs_eval_type in _SKIP_EVAL_TYPES:
        return True
    if (template.eval_type or "") == "composite":
        return True
    cfg_type = (template.config or {}).get("eval_type_id")
    if cfg_type and cfg_type in _SKIP_EVAL_TYPES:
        return True
    if (getattr(template, "composite_child_axis", "") or "").strip():
        return True
    return False


def _version_is_empty(version) -> bool:
    if version.prompt_messages:
        return False
    if (version.criteria or "").strip():
        return False
    cs = version.config_snapshot or {}
    for key in ("rule_prompt", "instructions", "code"):
        val = cs.get(key)
        if isinstance(val, str) and val.strip():
            return False
    msgs = cs.get("messages")
    if isinstance(msgs, list) and len(msgs) > 0:
        return False
    return True


def _live_has_content(template) -> bool:
    if (template.criteria or "").strip():
        return True
    cfg = template.config or {}
    for key in ("rule_prompt", "instructions", "code"):
        val = cfg.get(key)
        if isinstance(val, str) and val.strip():
            return True
    msgs = cfg.get("messages")
    if isinstance(msgs, list) and len(msgs) > 0:
        return True
    return False


def _apply_live_to_version(version, template) -> None:
    cfg = template.config or {}

    if (template.criteria or "").strip():
        version.criteria = template.criteria

    msgs = cfg.get("messages")
    if isinstance(msgs, list) and len(msgs) > 0:
        version.prompt_messages = msgs

    snapshot = dict(version.config_snapshot or {})
    for key in ("rule_prompt", "instructions", "code", "language"):
        val = cfg.get(key)
        if isinstance(val, str) and val.strip():
            snapshot[key] = val
    if isinstance(msgs, list) and len(msgs) > 0:
        snapshot["messages"] = msgs
    version.config_snapshot = snapshot


def backfill(apps, schema_editor):
    EvalTemplateVersion = apps.get_model("model_hub", "EvalTemplateVersion")

    qs = (
        EvalTemplateVersion.objects.select_related("eval_template")
        .filter(
            eval_template__owner="user",
            eval_template__deleted=False,
        )
        .order_by("eval_template_id", "version_number")
    )

    updated = 0
    skipped_filled = 0
    skipped_composite = 0
    unrecoverable = 0

    for version in qs.iterator(chunk_size=500):
        template = version.eval_template

        if _is_composite(template, version):
            skipped_composite += 1
            continue

        if not _version_is_empty(version):
            skipped_filled += 1
            continue

        if not _live_has_content(template):
            unrecoverable += 1
            continue

        _apply_live_to_version(version, template)
        version.save(
            update_fields=[
                "prompt_messages",
                "criteria",
                "config_snapshot",
                "updated_at",
            ]
        )
        updated += 1

    print(
        f"[0099] EvalTemplateVersion backfill — "
        f"updated={updated} already_filled={skipped_filled} "
        f"composite_skipped={skipped_composite} unrecoverable={unrecoverable}"
    )


def reverse(apps, schema_editor):
    # No-op. See module docstring.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("model_hub", "0098_merge_20260513_1258"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse, elidable=False),
    ]
