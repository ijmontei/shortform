from moviepy.editor import *
import ffmpeg
import json
import whisper
from pytube import YouTube
import re
import os
from clipsai import ClipFinder, Transcriber
from openai import OpenAI

def run_subtitle_generation():
    clips_folder = 'themes/Sigma/clips'
    subtitled_clips_folder = 'themes/Sigma/subtitled_clips'
    temp_files_path = 'themes/Sigma/subtitled_clips/temp'


    # Function to extract audio from video
    def extract_audio(video_filename, audio_filename, output_path):
        input_stream = ffmpeg.input(video_filename)
        audio = input_stream.audio
        output_stream = ffmpeg.output(audio, os.path.join(output_path,audio_filename)).overwrite_output()
        ffmpeg.run(output_stream)

    # Function to transcribe audio
    def transcribe_audio(audio_filename):
        model = whisper.load_model("small.en")
        return model.transcribe(audio_filename, word_timestamps=True, fp16=False)

    # Function to save word level information to JSON
    def save_wordlevel_info_to_json(wordlevel_info, filename='data/transcribe.json'):
        with open(filename, 'w') as f:
            json.dump(wordlevel_info, f, indent=4)

    # Function to load word level information from JSON
    def load_wordlevel_info_from_json(filename='data/transcribe.json'):
        with open(filename, 'r') as f:
            return json.load(f)

    # Function to process video with captions
    def process_video_with_captions(input_video, captions, output_filename, fps=24):
        input_video = VideoFileClip(input_video)
        final_video = CompositeVideoClip([input_video] + captions).set_audio(input_video.audio)
        final_video.write_videofile(output_filename, fps=fps, codec="libx264", audio_codec="aac", threads=32)

    # Function to split text into lines
    def split_text_into_lines(data):
        # Set parameters for line splitting
        MaxChars = 20
        MaxDuration = 40
        MaxGap = 15

        subtitles = []
        line = []
        line_duration = 0
        line_chars = 0

        # Iterate through word data
        for idx, word_data in enumerate(data):
            word = word_data["word"]
            start = word_data["start"]
            end = word_data["end"]

            # Append word to line
            line.append(word_data)
            line_duration += end - start

            # Check if line needs to be split
            temp = " ".join(item["word"] for item in line)
            new_line_chars = len(temp)
            duration_exceeded = line_duration > MaxDuration
            chars_exceeded = new_line_chars > MaxChars

            # Check for gap between words
            if idx > 0:
                gap = word_data['start'] - data[idx - 1]['end']
                maxgap_exceeded = gap > MaxGap
            else:
                maxgap_exceeded = False

            # If conditions for line split are met, create a new subtitle line
            if duration_exceeded or chars_exceeded or maxgap_exceeded:
                if line:
                    subtitle_line = {
                        "word": " ".join(item["word"] for item in line),
                        "start": line[0]["start"],
                        "end": line[-1]["end"],
                        "textcontents": line
                    }
                    subtitles.append(subtitle_line)
                    line = []
                    line_duration = 0
                    line_chars = 0

        # Append any remaining words to the last subtitle line
        if line:
            subtitle_line = {
                "word": " ".join(item["word"] for item in line),
                "start": line[0]["start"],
                "end": line[-1]["end"],
                "textcontents": line
            }
            subtitles.append(subtitle_line)

        return subtitles

    # Function to create captions
    def create_caption(textJSON, framesize, font="Impact", fontsize=70, color='white', bgcolor='rgba(255, 255, 0, 0.5)',
                    stroke_color='black', stroke_width=4, align="center", kerning = 2):
        word_clips = []
        xy_textclips_positions = []

        frame_width = framesize[0]
        frame_height = framesize[1]

        space_width = " "
        space_height = ""
        full_duration = textJSON['end'] - textJSON['start']
        
        total_sentence_width = sum(TextClip(word['word'].upper(), font=font, fontsize=fontsize, color=color, stroke_color=stroke_color, kerning=kerning, stroke_width=stroke_width).size[0] for word in textJSON['textcontents'])
        start_x = (frame_width - total_sentence_width) / 2
        x_pos = start_x
        
        for index, wordJSON in enumerate(textJSON['textcontents']):
            duration = wordJSON['end'] - wordJSON['start']
            word_clip = TextClip(wordJSON['word'].upper(), font=font, fontsize=fontsize, color=color, stroke_color=stroke_color,kerning = kerning,
                                stroke_width=1.5).set_start(textJSON['start']).set_duration(full_duration).fadein(0.2)
            word_clip_space = TextClip(" ", font=font, fontsize=fontsize, color='black', stroke_color=stroke_color, kerning = kerning,
                                    stroke_width=stroke_width).set_start(textJSON['start']).set_duration(full_duration)
            word_width, word_height = word_clip.size
            space_width, space_height = word_clip_space.size
            
            # Calculate x position to center the subtitle text
            x_pos = start_x

            # Calculate y position for subtitle text
            y_pos = frame_height * .8

            xy_textclips_positions.append({
                "x_pos": x_pos,
                "y_pos": y_pos,
                "width": word_width,
                "height": word_height,
                "word": wordJSON['word'],
                "start": wordJSON['start'],
                "end": wordJSON['end'],
                "duration": duration
            })

            word_clip = word_clip.set_position((x_pos, y_pos))
            word_clip_space = word_clip_space.set_position((x_pos + word_width, y_pos))
            
            word_clips.append(word_clip_space)
            word_clips.append(word_clip)

            # Update starting x position for the next words
            start_x += word_width + space_width

        for highlight_word in xy_textclips_positions:
            word_clip_highlight = TextClip(highlight_word['word'].upper(), font=font, fontsize=fontsize+.5, color='yellow', stroke_color='rgb(29,21,2)', bg_color=bgcolor,
                                        kerning = kerning, stroke_width= 2.5).set_start(highlight_word['start']).set_duration(
                highlight_word['duration']).fadein(0) #bg_color=bgcolor, #green color='rgb(50,255,0)', stroke_color='rgb(30,60,15)',
            word_clip_highlight = word_clip_highlight.set_position((highlight_word['x_pos'], highlight_word['y_pos']-1.5))
            word_clips.append(word_clip_highlight)

        return word_clips

    temp_counta = 1
    for clip_filename in os.listdir(clips_folder):
        # Skip non-video files (like .DS_Store)
        if not clip_filename.endswith('.mp4'):
            continue
        
        temp_count = str(temp_counta)
        clip_path = os.path.join(clips_folder, clip_filename)
        audio_filename = clip_filename.replace('.mp4', '.mp3')
        temp_files_point = os.path.join(temp_files_path,audio_filename)
        extract_audio(clip_path, audio_filename, temp_files_path)
        fin_title = " "
        transcription_result = transcribe_audio(temp_files_point)
        
        summarization_prompt = f"Create a youtube title from this transcript; make the title under 55 characters, DO NOT INCLUDE A COLON IN THE TITLE, and it should evoke curiousity out of the reader: {transcription_result}"
        max_tokens = 50
        client = OpenAI(api_key='')
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a viral youtube creator."},
                {"role": "user", "content":f"{summarization_prompt}"}
            ]
        )
        fin_title = response.choices[0].message.content.strip('"\'')
        print(fin_title)
        subtitle_filename = os.path.join(subtitled_clips_folder, f"{fin_title}.mp4")

        wordlevel_info = [{'word': word['word'].strip(), 'start': word['start'], 'end': word['end']} for segment in transcription_result['segments'] for word in segment['words']]
        # Save word level information to JSON
        save_wordlevel_info_to_json(wordlevel_info)

        # Load word level information from JSON
        wordlevel_info_modified = load_wordlevel_info_from_json()

        # Split text into lines
        linelevel_subtitles = split_text_into_lines(wordlevel_info_modified)

        frame_size = (1080, 1480)
        # Create captions for each line
        all_linelevel_splits = [create_caption(line, frame_size) for line in linelevel_subtitles]

        # Flatten the list of captions
        word_clips_list = [clip for sublist in all_linelevel_splits for clip in sublist]
        
        # Process video with captions
        process_video_with_captions(clip_path, word_clips_list, subtitle_filename)

        os.remove(temp_files_point)
        temp_counta +=1

if __name__ == "__main__":
    run_subtitle_generation()
