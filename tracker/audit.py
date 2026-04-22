import functools
import textwrap
import time


def audited(agent_name: str, action: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            app_id = args[0] if args else None
            input_summary = textwrap.shorten(
                str({"args": args, "kwargs": kwargs}), width=300, placeholder="..."
            )
            start = time.perf_counter()
            error = None
            success = True
            result = None
            try:
                result = fn(self, *args, **kwargs)
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                latency_ms = round((time.perf_counter() - start) * 1000)
                output_summary = textwrap.shorten(
                    str(result), width=300, placeholder="..."
                )
                llm_resp = getattr(self, "_last_llm_response", None)
                tokens_used = (
                    llm_resp.input_tokens + llm_resp.output_tokens
                    if llm_resp is not None
                    else None
                )
                self.tracker.log(
                    app_id=app_id,
                    agent=agent_name,
                    action=action,
                    input_summary=input_summary,
                    output_summary=output_summary if success else None,
                    tokens_used=tokens_used,
                    latency_ms=latency_ms,
                    success=success,
                    error=error,
                )
            return result

        return wrapper

    return decorator
