# MediaForge · 批量媒体处理工具

独立的全栈图片 / 短视频加水印与格式转换工具。FastAPI 提供处理 API，Pillow 负责图片处理，FFmpeg 负责视频水印与转 GIF；输出文件会打包为 ZIP 下载。

## 功能

- 拖拽或选择多张图片 / 多段视频
- 文字水印：自定义文字、透明度、大小、九宫格位置
- 可选上传 PNG / WebP / JPEG Logo 水印
- 批量处理：图片导出 PNG、JPEG 或 WebP；视频保留 MP4 或转换为 GIF
- 下载结果 ZIP；上传和输出目录在处理结束后自动清理
- 图片支持 JPEG、PNG、WebP、BMP；视频支持 MP4、MOV、WEBM（需 FFmpeg）

## 启动

需要 Python 3.10+。视频处理还需要将 FFmpeg 安装到系统并加入 PATH（`ffmpeg -version` 可验证）。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

浏览器打开 <http://127.0.0.1:8000>；API 文档位于 <http://127.0.0.1:8000/docs>。

macOS / Linux 激活虚拟环境：`source .venv/bin/activate`。

## 处理限制

- 每次最多 30 个文件，每个文件最大 200 MB。
- 视频依赖本机 FFmpeg；转 GIF 会缩小尺寸、限制帧率以控制文件大小。
- 服务当前按单用户本机工具设计，不包含账户系统。不要将未经身份验证的实例暴露到公网。

## 项目结构

```text
├── app.py                 # API、图片处理、FFmpeg 调度与 ZIP
├── static/index.html      # 上传、设置、处理进度与下载界面
└── requirements.txt
```

