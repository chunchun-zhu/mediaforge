from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
MAX_FILES = 30
MAX_BYTES = 200 * 1024 * 1024
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm"}
POSITIONS = {"top-left", "top-center", "top-right", "center-left", "center", "center-right", "bottom-left", "bottom-center", "bottom-right"}
POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="media")
app = FastAPI(title="MediaForge", description="批量媒体水印与格式转换", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _xy(position: str, width: int, height: int, box: tuple[int, int, int, int], margin: int) -> tuple[int, int]:
    left, top, right, bottom = box
    horizontal = position.split("-")[-1] if "-" in position else "center"
    vertical = position.split("-")[0] if "-" in position else "center"
    if position == "center":
        vertical, horizontal = "center", "center"
    x = margin if horizontal == "left" else width - (right-left) - margin if horizontal == "right" else (width-(right-left))//2
    y = margin if vertical == "top" else height - (bottom-top) - margin if vertical == "bottom" else (height-(bottom-top))//2
    return x-left, y-top


def _watermark(image: Image.Image, text: str, logo: Image.Image | None, opacity: int, scale: int, position: str) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGBA")
    w, h = image.size
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    margin = max(16, round(min(w, h) * 0.035))
    if logo is not None:
        mark = logo.convert("RGBA")
        max_side = max(24, round(min(w, h) * scale / 100))
        mark.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        alpha = mark.getchannel("A").point(lambda p: p * opacity // 100)
        mark.putalpha(alpha)
        x, y = _xy(position, w, h, (0, 0, *mark.size), margin)
        layer.alpha_composite(mark, (x, y))
    elif text.strip():
        draw = ImageDraw.Draw(layer)
        font_size = max(12, round(min(w, h) * scale / 100))
        font = _font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=max(1, font_size // 14))
        x, y = _xy(position, w, h, bbox, margin)
        draw.text((x-bbox[0], y-bbox[1]), text, font=font, fill=(255, 255, 255, round(255*opacity/100)), stroke_width=max(1, font_size//14), stroke_fill=(0, 0, 0, round(135*opacity/100)))
    return Image.alpha_composite(image, layer)


def process_image(source: Path, target: Path, text: str, logo_path: Path | None, opacity: int, scale: int, position: str, fmt: str) -> None:
    with Image.open(source) as im:
        logo = Image.open(logo_path) if logo_path else None
        try:
            result = _watermark(im, text, logo, opacity, scale, position)
        finally:
            if logo:
                logo.close()
    if fmt == "JPEG":
        result.convert("RGB").save(target, "JPEG", quality=92, optimize=True)
    else:
        result.save(target, fmt, quality=92 if fmt == "WEBP" else None, optimize=True)
    result.close()


def process_video(source: Path, target: Path, text: str, logo_path: Path | None, opacity: int, scale: int, position: str, fmt: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 FFmpeg。请安装 FFmpeg 并加入系统 PATH，再重试视频处理。")
    horizontal, vertical = position.split("-") if position != "center" else ("center", "center")
    margin = "max(16,min(w,h)*0.035)"
    x = margin if horizontal == "left" else "w-text_w-" + margin if horizontal == "right" else "(w-text_w)/2"
    y = margin if vertical == "top" else "h-text_h-" + margin if vertical == "bottom" else "(h-text_h)/2"
    if logo_path:
        logo_scale = f"min(iw\\,{scale}/100*min(main_w\\,main_h))"
        xlogo = margin if horizontal == "left" else f"main_w-overlay_w-{margin}" if horizontal == "right" else "(main_w-overlay_w)/2"
        ylogo = margin if vertical == "top" else f"main_h-overlay_h-{margin}" if vertical == "bottom" else "(main_h-overlay_h)/2"
        base_filter = f"[1:v]format=rgba,colorchannelmixer=aa={opacity/100:.3f},scale='{logo_scale}':-1[wm];[0:v][wm]overlay=x='{xlogo}':y='{ylogo}'[v]"
    else:
        safe = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")
        fontfile = "C:/Windows/Fonts/arial.ttf" if Path("C:/Windows/Fonts/arial.ttf").exists() else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        base_filter = f"[0:v]drawtext=fontfile='{fontfile}':text='{safe}':fontsize='max(18,min(w,h)*{scale/100:.4f})':fontcolor=white@{opacity/100:.3f}:borderw=2:bordercolor=black@0.55:x='{x}':y='{y}'[v]"
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if logo_path:
        cmd += ["-i", str(logo_path)]
    if fmt == "GIF":
        gif_filter = base_filter + ";[v]fps=12,scale='min(720,iw)':-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer[out]"
        cmd += ["-filter_complex", gif_filter, "-map", "[out]", "-t", "20", "-loop", "0"]
    else:
        cmd += ["-filter_complex", base_filter, "-map", "[v]"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "22", "-c:a", "aac", "-movflags", "+faststart"]
    cmd.append(str(target))
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if run.returncode:
        raise RuntimeError(run.stderr.strip()[-1200:] or "FFmpeg 视频处理失败")


@app.post("/api/process")
async def process(files: list[UploadFile] = File(...), watermark_text: str = Form(""), logo: UploadFile | None = File(None),
                  opacity: int = Form(65), size: int = Form(6), position: str = Form("bottom-right"),
                  image_format: Literal["WEBP", "PNG", "JPEG"] = Form("WEBP"), video_format: Literal["MP4", "GIF"] = Form("MP4")):
    if not files or len(files) > MAX_FILES:
        raise HTTPException(400, f"请选择 1 到 {MAX_FILES} 个文件。")
    if not 0 <= opacity <= 100 or not 2 <= size <= 25 or position not in POSITIONS:
        raise HTTPException(400, "水印参数超出有效范围。")
    if not watermark_text.strip() and not logo:
        raise HTTPException(400, "请输入水印文字或上传 Logo。")
    job = ROOT / "data" / "jobs" / uuid.uuid4().hex
    job.mkdir(parents=True, exist_ok=False)
    try:
        logo_path = None
        if logo:
            logo_ext = Path(logo.filename or "logo.png").suffix.lower()
            if logo_ext not in IMAGE_EXTS:
                raise HTTPException(400, "Logo 请使用 PNG、JPEG 或 WebP 图片。")
            logo_path = job / ("watermark" + logo_ext)
            blob = await logo.read(MAX_BYTES + 1)
            if len(blob) > MAX_BYTES:
                raise HTTPException(413, "Logo 文件不能超过 200 MB。")
            logo_path.write_bytes(blob)
        tasks = []
        names = set()
        total = 0
        for index, upload in enumerate(files, 1):
            ext = Path(upload.filename or "").suffix.lower()
            if ext not in IMAGE_EXTS | VIDEO_EXTS:
                raise HTTPException(400, f"不支持的文件类型：{upload.filename}")
            blob = await upload.read(MAX_BYTES + 1)
            if len(blob) > MAX_BYTES:
                raise HTTPException(413, f"单个文件不能超过 200 MB：{upload.filename}")
            total += len(blob)
            if total > 1024 * 1024 * 1024:
                raise HTTPException(413, "本次上传总量不能超过 1 GB。")
            safe_stem = Path(upload.filename or f"file-{index}").stem[:80]
            original = job / f"source-{index}{ext}"
            original.write_bytes(blob)
            is_image = ext in IMAGE_EXTS
            out_ext = {"WEBP": ".webp", "PNG": ".png", "JPEG": ".jpg"}[image_format] if is_image else {"MP4": ".mp4", "GIF": ".gif"}[video_format]
            name = f"{safe_stem}{out_ext}"
            if name.lower() in names:
                name = f"{safe_stem}-{index}{out_ext}"
            names.add(name.lower())
            target = job / name
            if is_image:
                tasks.append(asyncio.get_running_loop().run_in_executor(POOL, process_image, original, target, watermark_text, logo_path, opacity, size, position, image_format))
            else:
                tasks.append(asyncio.get_running_loop().run_in_executor(POOL, process_video, original, target, watermark_text, logo_path, opacity, size, position, video_format))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = [str(result) for result in results if isinstance(result, BaseException)]
        if errors:
            raise HTTPException(422, "部分文件处理失败：" + "；".join(errors[:3]))
        archive = job / "mediaforge-results.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for result in sorted(job.iterdir()):
                if result.is_file() and result not in {archive, logo_path} and not result.name.startswith("source-"):
                    zf.write(result, result.name)
        return FileResponse(archive, media_type="application/zip", filename="mediaforge-results.zip", background=__import__("starlette.background", fromlist=["BackgroundTask"]).BackgroundTask(shutil.rmtree, job, ignore_errors=True))
    except BaseException:
        shutil.rmtree(job, ignore_errors=True)
        raise

