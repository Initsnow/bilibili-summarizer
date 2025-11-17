from bilibili_api import Credential, video, channel_series
import asyncio
import aiohttp
import os
import argparse
import logging
import time
from tqdm.asyncio import tqdm

from generate_subtitles import generate_subtitles

# --- Cache Configuration ---
CACHE_DIR = ".cache/subtitles"
CACHE_MAX_AGE_DAYS = 30
# --- End Cache Configuration ---

def cleanup_cache(directory: str, max_age_days: int):
    """Deletes files in a directory older than max_age_days."""
    if not os.path.exists(directory):
        return
    
    logging.info(f"Cleaning up cache in '{directory}' older than {max_age_days} days...")
    cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)
    
    cleaned_count = 0
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        if os.path.isfile(file_path):
            try:
                if os.path.getmtime(file_path) < cutoff_time:
                    os.remove(file_path)
                    cleaned_count += 1
            except OSError as e:
                logging.error(f"Error removing cache file {file_path}: {e}")
    if cleaned_count > 0:
        logging.info(f"Removed {cleaned_count} outdated cache file(s).")
    else:
        logging.info("No outdated cache files to remove.")
from download_audio import download_audio
from summarize import summarize
from read_prompt import read_prompt
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def save(page_number: int, filename: str, content: str, output_dir: str):
    """Saves content to a file in the specified directory with a sanitized filename."""
    # Sanitize filename to remove characters invalid for file paths
    safe_filename = "".join(c for c in filename if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
    
    os.makedirs(output_dir, exist_ok=True)
    # Format page number with leading zeros for consistent sorting
    file_path = os.path.join(output_dir, f"P{page_number:03d}_{safe_filename}.md")
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    logging.info(f"Successfully saved: {file_path}")
    return file_path

async def get_subtitle(v: video.Video, page_number: int, device: str, model_size: str, bvid: str):
    """Gets subtitles for a specific page, using a cache to avoid re-generation."""
    cache_key = f"{bvid}_{page_number}"
    cache_file_path = os.path.join(CACHE_DIR, f"{cache_key}.txt")

    # 1. Check cache first
    if os.path.exists(cache_file_path):
        logging.info(f"Loading subtitles for P{page_number} from cache.")
        with open(cache_file_path, "r", encoding="utf-8") as f:
            return f.read()

    # 2. If not in cache, fetch or generate
    logging.info(f"No cache found for P{page_number}. Fetching or generating subtitles.")
    cid = await v.get_cid(page_number - 1)
    subtitle_data = await v.get_subtitle(cid)
    
    subtitle_text = None
    
    # Try to get official subtitles
    if subtitle_data and subtitle_data.get("subtitles"):
        logging.info(f"Found official subtitles for P{page_number}.")
        url = f"https:{subtitle_data['subtitles'][0]['subtitle_url']}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                j = await response.json()
                subtitle_text = "\n".join([item["content"] for item in j["body"]])
    else:
        # Generate subtitles if none are found
        logging.info(f"No official subtitles found for P{page_number}. Generating from audio...")
        audio_file = await download_audio(v, page_number)
        subtitle_text = generate_subtitles(audio_file, "text", device=device, model_size=model_size)

    # 3. Save to cache if content was successfully obtained
    if subtitle_text and subtitle_text.strip():
        logging.info(f"Saving subtitles for P{page_number} to cache.")
        with open(cache_file_path, "w", encoding="utf-8") as f:
            f.write(subtitle_text)
            
    return subtitle_text

async def process_page(v: video.Video, page_details: dict, prompt_text: str, bvid: str, args: argparse.Namespace, save_page_number: int = None):
    """Processes a single video page, including retries."""
    page_number = page_details['page']
    title = page_details['part']
    max_retries = 3
    
    _save_page_number = save_page_number if save_page_number is not None else page_number
    
    for attempt in range(max_retries):
        try:
            logging.info(f"Processing P{_save_page_number}: {title}")
            
            subtitle_text = await get_subtitle(v, page_number, device=args.device, model_size=args.model_size, bvid=bvid)
            if not subtitle_text or not subtitle_text.strip():
                logging.warning(f"Subtitle for P{_save_page_number} is empty. Skipping summary.")
                return

            summary = await summarize(subtitle_text, prompt_text)
            if summary:
                save(_save_page_number, title, summary, args.output_dir)
            else:
                logging.error(f"Failed to generate summary for P{_save_page_number}.")

            return  # Success, exit retry loop

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logging.warning(f"Network error on P{_save_page_number}, attempt {attempt + 1}/{max_retries}: {e}")
            if attempt + 1 == max_retries:
                logging.error(f"P{_save_page_number} failed after {max_retries} retries. Skipping.")
            else:
                await asyncio.sleep(5 * (attempt + 1))  # Exponential backoff
        except Exception as e:
            logging.error(f"An unexpected error occurred while processing P{_save_page_number}: {e}", exc_info=True)
            break  # Do not retry on unknown errors

async def process_bvid(args, credential):
    """Processes a single Bilibili video, identified by its BVID."""
    v = video.Video(bvid=args.bvid, credential=credential)
    prompt_text = read_prompt(args.prompt)
    
    try:
        all_pages = await v.get_pages()
        logging.info(f"Found {len(all_pages)} pages for BVID {args.bvid}.")
    except Exception as e:
        logging.error(f"Failed to retrieve video pages for {args.bvid}. Check BVID and credentials. Error: {e}")
        return

    pages_to_process = [
        p for p in all_pages 
        if p['page'] >= args.start_page and (args.end_page is None or p['page'] <= args.end_page)
    ]

    for page in tqdm(pages_to_process, desc=f"Processing Pages for {args.bvid}"):
        title = page['part']
        page_number = page['page']
        
        # Sanitize filename for checking existence
        safe_filename = "".join(c for c in title if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
        output_path = os.path.join(args.output_dir, f"P{page_number:03d}_{safe_filename}.md")

        # Checkpoint: Skip if file already exists
        if os.path.exists(output_path):
            logging.info(f"Skipping P{page_number} '{title}' as it already exists.")
            continue
            
        await process_page(v, page, prompt_text, bvid=args.bvid, args=args)

async def process_season(args, credential):
    """Processes all videos in a Bilibili channel series (season)."""
    series = channel_series.ChannelSeries(
        id_=args.season_id,
        type_=channel_series.ChannelSeriesType.SEASON,
        credential=credential,
    )
    video_list = await series.get_videos()
    
    logging.info(f"Found {len(video_list['archives'])} videos in season {args.season_id}.")

    global_page_counter = 1
    for video_info in tqdm(video_list["archives"], desc=f"Processing Season {args.season_id}"):
        bvid = video_info["bvid"]
        
        v = video.Video(bvid=bvid, credential=credential)
        prompt_text = read_prompt(args.prompt)
        
        try:
            all_pages = await v.get_pages()
        except Exception as e:
            logging.error(f"Failed to retrieve pages for {bvid}. Skipping video. Error: {e}")
            continue

        # Note: We are not using args.start_page or args.end_page for seasons,
        # we process all pages of all videos.
        for page in all_pages:
            title = page['part']
            
            # Sanitize filename for checking existence
            safe_filename = "".join(c for c in title if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
            output_path = os.path.join(args.output_dir, f"P{global_page_counter:03d}_{safe_filename}.md")

            # Checkpoint: Skip if file already exists
            if os.path.exists(output_path):
                logging.info(f"Skipping P{global_page_counter} '{title}' as it already exists.")
                global_page_counter += 1
                continue
            
            await process_page(v, page, prompt_text, bvid=bvid, args=args, save_page_number=global_page_counter)
            global_page_counter += 1

async def main():
    parser = argparse.ArgumentParser(description="Bilibili Video Summarizer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bvid", type=str, help="The BVID of the video to process.")
    group.add_argument("--season-id", type=int, help="The ID of the channel series (season/collection) to process.")
    
    parser.add_argument("--start-page", type=int, default=1, help="The page number to start from (only for BVID).")
    parser.add_argument("--end-page", type=int, default=None, help="The page number to stop at (inclusive, only for BVID).")
    parser.add_argument("--prompt", type=str, required=True, help="The name of the prompt file (without extension) to use for summarization.")
    parser.add_argument("--output-dir", type=str, default="result", help="The directory to save the summary files.")
    parser.add_argument("--device", type=str, default="cuda", choices=["cuda", "cpu"], help="Device to use for subtitle generation (cuda or cpu).")
    parser.add_argument("--model-size", type=str, default="small", choices=["tiny", "base", "small", "medium", "large-v3"], help="Whisper model size to use for subtitle generation.")
    args = parser.parse_args()

    # Create cache directory and clean up old files
    os.makedirs(CACHE_DIR, exist_ok=True)
    cleanup_cache(CACHE_DIR, CACHE_MAX_AGE_DAYS)

    # Load credentials from .env file
    load_dotenv()
    c = Credential(
        sessdata=os.getenv("SESSDATA"),
        bili_jct=os.getenv("BILI_JCT"),
        buvid3=os.getenv("BUVID3"),
    )
    if not c.sessdata:
        logging.warning("Credential SESSDATA not found. Operations may be limited. Please create a .env file.")


    if args.season_id:
        await process_season(args, c)
    else:
        await process_bvid(args, c)

if __name__ == "__main__":
    asyncio.run(main())