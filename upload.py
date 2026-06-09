import os
from apiclient.discovery import build
from apiclient.errors import HttpError
from apiclient.http import MediaFileUpload
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client.tools import argparser, run_flow

# OAuth 2.0 details
CLIENT_SECRETS_FILE = "client_secrets.json"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
MISSING_CLIENT_SECRETS_MESSAGE = """
WARNING: Please configure OAuth 2.0
To make this script work, you need to populate the client_secrets.json file.
"""

# Function to get authenticated service
def get_authenticated_service():
    flow = flow_from_clientsecrets(CLIENT_SECRETS_FILE, scope=YOUTUBE_UPLOAD_SCOPE, message=MISSING_CLIENT_SECRETS_MESSAGE)
    storage = Storage("oauth2.json")
    credentials = storage.get()

    if credentials is None or credentials.invalid:
        credentials = run_flow(flow, storage)

    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)

""" DEFAULT TO THIS IF THE BELOW FUNCTION DOESNT WORK
# Function to upload a video to YouTube
def upload_video(youtube, video_path, title, description, privacy_status):
    tags = None
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': privacy_status
        }
    }

    insert_request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True)
    )

    response = insert_request.execute()
    return response
"""

# Function to upload a video to YouTube
def upload_video(youtube, video_path, title, description, privacy_status):
    tags = None
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': privacy_status
        }
    }

    # Specify only the necessary parts
    parts_to_include = "snippet,status"

    insert_request = youtube.videos().insert(
        part=parts_to_include,
        body=body,
        media_body=MediaFileUpload(video_path, chunksize=256 * 1024, resumable=True)
    )

    response = insert_request.execute()
    return response

# Function to delete a file
def delete_file(file_path):
    try:
        os.remove(file_path)
        print(f"Deleted file: {file_path}")
    except Exception as e:
        print(f"Error deleting file: {e}")

# Main function
def upload_function():
    # Get authenticated YouTube service
    youtube = get_authenticated_service()

    # Folder containing subtitled clips
    subtitled_clips_folder = 'themes/Sigma/subtitled_clips'

    # Iterate over subtitled clips in the folder
    for filename in os.listdir(subtitled_clips_folder):
        if filename.endswith('.mp4'):
            video_path = os.path.join(subtitled_clips_folder, filename)
            title = filename.split('.')[0]  # Use filename as title
            description = "Uploaded via Python"  # Modify as needed
            #tags
            privacy_status = "public"  # Modify as needed
            print("Check")
            # Upload video to YouTube
            try:
                response = upload_video(youtube, video_path, title, description, privacy_status)
                print("Video uploaded successfully!")
                print("Video ID:", response['id'])

                # Delete the uploaded file
                delete_file(video_path)
            except HttpError as e:
                print("An HTTP error occurred:", e)
            except Exception as e:
                print("An error occurred:", e)

if __name__ == "__main__":
    upload_function()
