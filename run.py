# Import functions from the pipeline scripts
from video_fetch import run_video_fetch
from clip_generation import run_clip_generation
from subtitle_generation import run_subtitle_generation


run_video_fetch()
print("video fetch complete")
print("starting clip generation")
run_clip_generation()
print("clip generation complete")
print("starting subtitle generation")
run_subtitle_generation()
print("subtitle generation complete")
print("upload-ready videos and metadata are prepared")
