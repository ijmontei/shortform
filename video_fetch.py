import os
import json
import time
from datetime import datetime
import yt_dlp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(BASE_DIR, "src")
CHANNELS_FILE = os.path.join(SRC_PATH, "channels.txt")
ID_FILE = os.path.join(SRC_PATH, "id.json")


def build_ytdl_opts(extra_opts=None):
    opts = {
        'quiet': True,
        'no_warnings': True,
    }

    cookies_file = os.getenv(
        "SHORTFORM_YTDLP_COOKIES",
        os.path.join(BASE_DIR, "cookies.txt"),
    )
    cookies_browser = os.getenv("SHORTFORM_YTDLP_COOKIES_BROWSER", "chrome")

    if os.path.exists(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookies_browser and os.getenv("SHORTFORM_DISABLE_BROWSER_COOKIES") != "1":
        opts["cookiesfrombrowser"] = (cookies_browser,)

    if extra_opts:
        opts.update(extra_opts)

    return opts

def run_video_fetch():
    # Start time for performance measurement
    start = time.time()

    # Function to get latest video URL for a given channel using yt-dlp
    def get_latest_video(channel_url):
        # yt-dlp options to simulate extraction without downloading
        ydl_opts = build_ytdl_opts({
            'extract_flat': False, # Ensure we get full metadata (like views)
            'playlist_items': '1', # Grab only the most recent video
            'simulate': True       # Do not download the video
        })
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                
                # yt-dlp returns a dictionary; if it's a channel/playlist, videos are in 'entries'
                if 'entries' in info and info['entries']:
                    video = info['entries'][0]
                else:
                    video = info
                
                # Format the view count to include commas and the word 'views' (e.g., "1,234 views")
                views_int = video.get('view_count', 0)
                views_str = f"{views_int:,} views" if views_int else "N/A"

                # Format the date from YYYYMMDD to a readable format (e.g., "Oct 24, 2023")
                raw_date = video.get('upload_date')
                if raw_date:
                    date_str = datetime.strptime(raw_date, '%Y%m%d').strftime('%b %d, %Y')
                else:
                    date_str = "N/A"
                    
                latest_video = {
                    'title': video.get('title', 'Unknown Title'),
                    'video_url': video.get('webpage_url') or f"https://www.youtube.com/watch?v={video.get('id')}",
                    'views': views_str,
                    'date_time': date_str
                }
                
                return latest_video
                
        except Exception as e:
            print(f"Error collecting video data for {channel_url}: {e}")
            return None

    os.makedirs(SRC_PATH, exist_ok=True)

    # Read YouTube channels from file
    with open(CHANNELS_FILE, 'r') as file:
        # Added a check to ignore empty lines
        channels = [channel.strip() for channel in file.readlines() if channel.strip()]

    # Define the path to the JSON file
    json_filename = ID_FILE

    # Load existing JSON data
    existing_videos = {}
    if os.path.exists(json_filename) and os.path.getsize(json_filename) > 0:
        try:
            with open(json_filename, 'r') as json_file:
                existing_videos = json.load(json_file)
        except json.decoder.JSONDecodeError:
            print(f"Error: Unable to load JSON data from {json_filename}. File may be empty or corrupted.")

    # Dictionary to store latest videos for each channel
    latest_videos = {}

    # Iterate through channels to get latest videos
    for channel in channels:
        latest_video = get_latest_video(channel)
        if latest_video:
            # Check if the latest video already exists in the existing videos
            existing_urls = [v['video_url'] for v in existing_videos.values()]
            if latest_video['video_url'] not in existing_urls:
                latest_videos[channel] = latest_video

    # Merge latest videos with existing videos
    existing_videos.update(latest_videos)

    # Write the merged dictionary to the JSON file
    with open(json_filename, 'w') as json_file:
        json.dump(existing_videos, json_file, indent=4)

    print("Latest videos have been saved to", json_filename)

    # End time for performance measurement
    end = time.time()
    # Calculate execution time
    length = end - start
    print(f"It took {round(length / 60, 2)} minutes!")

# Optional block so you can run this script directly
if __name__ == '__main__':
    run_video_fetch()
