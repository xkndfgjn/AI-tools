"""Broadcast (multi-target) text message.

Serial loop over open_chat + type + Enter per target, with a short anti-abuse
delay between sends (on by default). Returns a per-target breakdown so the
caller can see exactly who got it and who didn't.

Why a dedicated op instead of looping /api/execute on the caller side:
- one request, one serial-lock transaction, no re-activation churn between
  messages
- structured sent/failed result instead of N independent responses
- pacing lives in one place (configurable here, not in every caller)

Anti-abuse pacing default is intentionally short (500ms + 0-300ms jitter).
The dominant per-target cost is open_chat itself (~2.5s, mostly the search
result refresh wait), NOT this pacing. Set interval_ms=0 to disable pacing
entirely if you know what you're doing.
"""
from __future__ import annotations

import asyncio

from .base import BaseOperation, OperationContext, OperationResult, OperationStatus
from .registry import register_operation
from ._helpers import open_chat, sleep_ms
from ._broadcast import normalize_targets, plan_delays


@register_operation("broadcast_message")
class BroadcastMessageOperation(BaseOperation):
    description = "Send the same text message to multiple contacts/groups"
    requires_confirmation = False

    async def execute(self, ctx: OperationContext, params: dict) -> OperationResult:
        targets = normalize_targets(params.get("targets"))
        text = params.get("text")
        if not targets:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Missing or empty parameter: targets",
            )
        if text is None:
            return OperationResult(
                status=OperationStatus.FAILED,
                message="Missing parameter: text",
            )
        text = str(text)

        # Anti-abuse pacing. Default is short (500ms + 0-300ms jitter) so a
        # small broadcast finishes quickly while still breaking a perfectly
        # regular cadence. Set interval_ms=0 to disable.
        interval_ms = int(params.get("interval_ms", 500))
        jitter_ms = int(params.get("jitter_ms", 300))
        max_targets = int(params.get("max_targets", 0))
        stop_on_fail = bool(params.get("stop_on_fail", False))

        if max_targets > 0 and len(targets) > max_targets:
            return OperationResult(
                status=OperationStatus.FAILED,
                message=(
                    f"Too many targets: {len(targets)} exceeds max_targets="
                    f"{max_targets}; raise max_targets or trim the list"
                ),
            )

        delays = plan_delays(len(targets), interval_ms, jitter_ms)
        ctx.logger.info(
            f"broadcast_message: {len(targets)} targets, "
            f"interval~{interval_ms}+{jitter_ms}ms, stop_on_fail={stop_on_fail}"
        )

        sent: list[dict] = []
        failed: list[dict] = []
        for i, to in enumerate(targets):
            ok, msg = await open_chat(ctx, to)
            if not ok:
                failed.append({"to": to, "error": msg})
                ctx.logger.warning(f"broadcast skip '{to}': {msg}")
                if stop_on_fail:
                    break
                continue

            await asyncio.to_thread(ctx.controller.type_text, text)
            await sleep_ms(ctx, 200)
            await asyncio.to_thread(ctx.controller.press_keys, "Enter")
            await sleep_ms(ctx, 500)
            sent.append({"to": to})
            ctx.logger.info(f"broadcast sent to '{to}'")

            if delays[i] > 0:
                await sleep_ms(ctx, delays[i])

        total = len(targets)
        sent_count = len(sent)
        failed_count = len(failed)
        if sent_count == 0:
            status = OperationStatus.FAILED
            message = f"All {total} broadcasts failed"
        else:
            status = OperationStatus.SUCCESS
            message = (
                f"Sent to {sent_count}/{total}"
                + (f", {failed_count} failed" if failed_count else "")
            )

        return OperationResult(
            status=status,
            data={
                "sent": sent,
                "failed": failed,
                "count": sent_count,
                "total": total,
                "partial": failed_count > 0,
            },
            message=message,
        )
