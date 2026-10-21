"""FFmpeg helpers: audio assembly and the final mix (stickman video + narration + optional music + burned-in subtitles)."""
import shlex
import subprocess
from pathlib import Path

FPS = 24


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


def silence(sec: float, out) -> None:
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{sec:.3f}", out])


VOICE_FX = (
    "highpass=f=70,equalizer=f=220:t=q:w=1:g=2,equalizer=f=4000:t=q:w=1.5:g=-2,"
    "acompressor=threshold=-20dB:ratio=3:attack=15:release=200:makeup=3,aecho=0.8:0.6:60|120:0.18|0.10"
)


def final_mix(video, narration, subs, fonts, music, total: float, out, pad: bool = True) -> None:
    cmd = ["ffmpeg", "-y", "-i", video, "-i", narration]
    fade_out = f"afade=t=out:st={max(0.0, total - 0.9):.2f}:d=0.9"
    voice = f"[1:a]{VOICE_FX}[vo]"
    bed = None
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
        bed = "[2:a]volume=0.10,afade=t=in:d=1.5[m]"
    elif pad:  # generated soft A-minor drone, no licensing needed
        for f in (110.0, 164.81, 220.0, 261.63):
            cmd += ["-f", "lavfi", "-i", f"sine=f={f}:r=44100"]
        bed = ("[2:a][3:a][4:a][5:a]amix=inputs=4:normalize=0,volume=0.07,tremolo=f=0.12:d=0.5,"
               "lowpass=f=1200,aecho=0.8:0.88:700|1100:0.35|0.25,afade=t=in:d=2[m]")
    mastering = f"{fade_out},loudnorm=I=-16:TP=-1.5:LRA=11[a]"
    if bed:
        audio = f"{voice};{bed};[vo][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,{mastering}"
    else:
        audio = f"{voice};[vo]{mastering}"
    video_chain = f"[0:v]ass={subs}:fontsdir={fonts}[vid]"
    cmd += ["-filter_complex", f"{video_chain};{audio}", "-map", "[vid]", "-map", "[a]",
            "-t", f"{total:.3f}", "-r", FPS, "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
            "-ar", "44100", "-movflags", "+faststart", out]
    run(cmd)
