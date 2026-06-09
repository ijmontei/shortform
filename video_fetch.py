import os
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
import time

def run_video_fetch():
    # Start time for performance measurement
    start = time.time()

    # Function to get latest video URL for a given channel
    def get_latest_video(channel_url):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")  # Run Chrome in headless mode to improve speed
        driver = webdriver.Chrome(options=options)  # You may need to adjust this based on your WebDriver setup
        driver.get(channel_url)
        
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div#details')))
            title_element = driver.find_element(By.CSS_SELECTOR, 'a#video-title-link')
            title = title_element.get_attribute('title')
            vurl = title_element.get_attribute('href')
            views_element = driver.find_element(By.XPATH, './/*[@id="metadata"]//span[@class="inline-metadata-item style-scope ytd-video-meta-block"][1]')
            views = views_element.text
            date_time_element = driver.find_element(By.XPATH, './/*[@id="metadata"]//span[@class="inline-metadata-item style-scope ytd-video-meta-block"][2]')
            date_time = date_time_element.text
            latest_video = {
                'title': title,
                'video_url': vurl,
                'views': views,
                'date_time': date_time
            }
        except StaleElementReferenceException:
            # Element reference became stale, retry
            return get_latest_video(channel_url)
        except Exception as e:
            print(f"Error collecting video data for {channel_url}: {e}")
            latest_video = None

        driver.quit()
        return latest_video

    # Read YouTube channels from file
    with open('themes/Sigma/video_pull/channels.txt', 'r') as file:
        channels = file.readlines()

    # Remove whitespace characters like `\n` at the end of each line
    channels = [channel.strip() for channel in channels]

    # Define the path to the JSON file
    json_filename = 'themes/Sigma/video_pull/id.json'

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
            if latest_video['video_url'] not in [v['video_url'] for v in existing_videos.values()]:
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
    length = end-start
    print("It took", round((length)/60,2), "minutes!")

