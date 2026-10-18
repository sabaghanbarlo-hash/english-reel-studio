"""FFmpeg assembly: Ken Burns / stock clips -> crossfades -> narration + optional music -> burned-in subtitles."""
import shlex
import subprocess
from pathlib import Path

W, H, FPS = 1080, 1920, 30
XFADE = 0.3
GRADE = "unsharp=5:5:0.6,vignette=PI/6,noise=alls=4:allf=u,eq=contrast=1.06:saturation=0.9"
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an"]


def run(cmd) -> None:
    cmd = [str(c) for c in cmd]
    print("$", " ".join(shlex.quote(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


def duration(path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)]
    )
    return float(out)


def pad_audio(src, dst, pad: float) -> None:
    run(["ffmpeg", "-y", "-i", src, "-af", f"apad=pad_dur={pad}", "-ar", "44100", "-ac", "2", dst])


def concat_audio(wavs: list, out: Path) -> None:
    lst = out.parent / "audio_list.txt"
    lst.write_text("".join(f"file '{Path(w).name}'\n" for w in wavs))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])


def _motion(idx: int, frames: int):
    """Seven different camera moves so consecutive shots never feel identical."""
    p = f"(on/{frames})"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    kinds = [
        (f"1.0+0.16*{p}", cx, cy),                                  # push in
        ("1.14", f"(iw-iw/zoom)*{p}", cy),                          # pan right
        (f"1.16-0.16*{p}", cx, cy),                                 # pull out
        ("1.14", f"(iw-iw/zoom)*(1-{p})", cy),                      # pan left
        ("1.14", cx, f"(ih-ih/zoom)*(1-{p})"),                      # tilt up
        (f"1.0+0.12*{p}", f"(iw-iw/zoom)*{p}", f"(ih-ih/zoom)*{p}"),  # diagonal push
        ("1.14", cx, f"(ih-ih/zoom)*{p}"),                          # tilt down
    ]
    z, x, y = kinds[idx % len(kinds)]
    sway = "+sin(on/23)*5"  # slight handheld drift
    return z, f"max(0,min(iw-iw/zoom,{x}{sway}))", f"max(0,min(ih-ih/zoom,{y}))"


def make_clip(visual, dur: float, idx: int, out: Path) -> None:
    frames = max(2, int(round(dur * FPS)))
    if visual is None:
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x16202a:s={W}x{H}:r={FPS}", "-t", f"{dur:.3f}",
            "-vf", f"{GRADE},setsar=1", *ENC, out])
        return
    path, kind = visual
    if kind == "video":
        run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", path, "-t", f"{dur:.3f}",
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},{GRADE},setsar=1",
            *ENC, out])
        return
    z, x, y = _motion(idx, frames)
    vf = (
        f"scale=2160:3840:flags=lanczos:force_original_aspect_ratio=increase,crop=2160:3840,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
        f"{GRADE},setsar=1"
    )
    run(["ffmpeg", "-y", "-i", path, "-vf", vf, "-frames:v", frames, *ENC, out])


def join_clips(clips: list, shot_durs: list, out: Path) -> None:
    n = len(clips)
    if n == 1:
        run(["ffmpeg", "-y", "-i", clips[0], "-c", "copy", out])
        return
    inputs = []
    for c in clips:
        inputs += ["-i", c]
    chain, prev, acc = [], "[0:v]", 0.0
    for k in range(1, n):
        acc += shot_durs[k - 1]
        label = f"[v{k}]"
        chain.append(f"{prev}[{k}:v]xfade=transition=fade:duration={XFADE}:offset={acc:.3f}{label}")
        prev = label
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", prev, *ENC, out])


def final_mix(video, narration, subs, fonts, music, total: float, out) -> None:
    cmd = ["ffmpeg", "-y", "-i", video, "-i", narration]
    fade_out = f"afade=t=out:st={max(0.0, total - 0.8):.2f}:d=0.8"
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        audio = (
            f"[2:a]volume=0.10,afade=t=in:d=1.5[m];"
            f"[1:a][m]amix=inputs=2:duration=first:dropout_transition=0,{fade_out},loudnorm=I=-16:TP=-1.5:LRA=11[a]"
        )
    else:
        audio = f"[1:a]{fade_out},loudnorm=I=-16:TP=-1.5:LRA=11[a]"
    video_chain = f"[0:v]ass={subs}:fontsdir={fonts}[v]"
    cmd += ["-filter_complex", f"{video_chain};{audio}", "-map", "[v]", "-map", "[a]",
            "-t", f"{total:.3f}", "-r", FPS, "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-maxrate", "6M", "-bufsize", "12M",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
            "-movflags", "+faststart", out]
    run(cmd)
