# Import functions from the three scripts
from video_fetch import run_video_fetch
from clip_generation import run_clip_generation
from subtitle_generation import run_subtitle_generation
from upload import upload_function


run_video_fetch()
print("done")
print("starting")
run_clip_generation()
print("done")
print("starting")
run_subtitle_generation()
print("complete")
upload_function()
print("complete")