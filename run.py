import os

# Import functions from the pipeline scripts
from video_fetch import run_video_fetch
from clip_generation import run_clip_generation
from subtitle_generation import run_subtitle_generation
from upload import upload_function


run_video_fetch()
print("video fetch complete")
print("starting clip generation")
run_clip_generation()
print("clip generation complete")
print("starting subtitle generation")
run_subtitle_generation()
print("subtitle generation complete")

if os.getenv("SHORTFORM_ENABLE_YOUTUBE_UPLOAD") == "1":
    upload_function()
    print("youtube upload complete")
else:
    print("upload automation skipped; upload-ready videos and manifests are prepared")
