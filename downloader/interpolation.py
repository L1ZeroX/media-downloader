"""Motion-compensated 60 fps filter for the opt-in beta channel."""
import math


def interpolation_filter(source_fps, duration):
    if source_fps is None or not math.isfinite(source_fps) or source_fps <= 0:
        raise ValueError("元動画のフレームレートを確認できません。通常の60fpsを選択してください。")
    if source_fps >= 59.99:
        return None
    motion = "minterpolate=fps=60:mi_mode=mci:mc_mode=obmc:me_mode=bilat:me=epzs:search_param=16:scd=fdiff"
    # The filter needs future frames; pad and trim to preserve the original ending.
    if duration and math.isfinite(duration) and duration > 0:
        return f"tpad=stop_mode=clone:stop_duration={max(.2, 3/source_fps):.6f},{motion},trim=duration={duration:.6f}"
    return motion
