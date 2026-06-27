def source_attribution(source_record=None, clip=None):
    source_record = source_record or {}
    clip = clip or {}
    return {
        "source_title": source_record.get("title") or clip.get("source_title", ""),
        "source_channel": source_record.get("channel") or clip.get("source_channel", ""),
        "source_video_url": source_record.get("video_url") or clip.get("source_video_url", ""),
        "clip_start": clip.get("start_time"),
        "clip_end": clip.get("end_time"),
    }
