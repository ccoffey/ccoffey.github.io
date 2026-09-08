#!/usr/bin/env python3
import os, sys, json, re, subprocess, hashlib
from html import escape
from datetime import datetime
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAJOR_BUILDS_DIR = os.path.join(BASE_DIR, 'major-builds')
QUICK_BUILDS_DIR = os.path.join(BASE_DIR, 'quick-builds')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

GA_MEASUREMENT_ID = os.environ.get('GA_MEASUREMENT_ID', 'G-RJN8XNMCEG')
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.webm')

def load_template(name):
    path = os.path.join(TEMPLATES_DIR, name)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def parse_photo_date(filename):
    if 'control_panel_graphic' in filename:
        return 'September 5, 2026 — Control Panel Vinyl Graphic (gorillagraphics.ie)', 'Control Panel Artwork'
    if 'claw_machine_demo' in filename:
        return 'September 6, 2026', 'Sep 6, 2026'
    
    m_step = re.search(r'step-(\d+)', filename)
    if m_step:
        return 'June 4, 2026', 'Jun 4, 2026'

    m_pxl = re.search(r'PXL_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', filename)
    if m_pxl:
        y, mo, d, h, mi, s = m_pxl.groups()
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
        return dt.strftime('%B %-d, %Y'), dt.strftime('%b %-d, %Y')
    
    m_wa = re.search(r'IMG-(\d{4})(\d{2})(\d{2})-WA(\d+)', filename)
    if m_wa:
        y, mo, d, seq = m_wa.groups()
        dt = datetime(int(y), int(mo), int(d))
        return dt.strftime('%B %-d, %Y'), dt.strftime('%b %-d, %Y')

    return 'Build Photo', 'Photo'

def get_photo_sort_key(filename):
    if 'control_panel_graphic' in filename:
        return (2026, 9, 5, 18, 9, 0)
    if 'claw_machine_demo' in filename:
        return (2026, 9, 6, 23, 59, 59)
    m_step = re.search(r'step-(\d+)', filename)
    if m_step:
        return (2026, 6, 4, 10, int(m_step.group(1)), 0)
    m_pxl = re.search(r'PXL_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', filename)
    if m_pxl:
        y, mo, d, h, mi, s = m_pxl.groups()
        return (int(y), int(mo), int(d), int(h), int(mi), int(s))
    m_wa = re.search(r'IMG-(\d{4})(\d{2})(\d{2})-WA(\d+)', filename)
    if m_wa:
        y, mo, d, seq = m_wa.groups()
        return (int(y), int(mo), int(d), 12, 0, int(seq))
    return (1970, 1, 1, 0, 0, 0)

def strip_exif_from_file(filepath):
    """Losslessly strips APP1 (EXIF / GPS / device metadata / XMP) from JPEG files."""
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
        if not data.startswith(b'\xff\xd8'):
            return False
        pos = 2
        out = [data[:2]]
        has_exif = False
        while pos < len(data):
            if data[pos] != 0xff:
                out.append(data[pos:])
                break
            marker = data[pos+1]
            if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
                out.append(data[pos:pos+2])
                pos += 2
                continue
            length = int.from_bytes(data[pos+2:pos+4], 'big')
            segment = data[pos:pos+2+length]
            if marker == 0xe1:  # APP1 (EXIF, GPS, camera metadata)
                has_exif = True
            else:
                out.append(segment)
            pos += 2 + length
        if has_exif:
            with open(filepath, 'wb') as f:
                f.write(b''.join(out))
            return True
    except Exception as e:
        print(f"Error stripping EXIF from {filepath}: {e}")
    return False

def is_video_optimized(video_path):
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format_tags=comment', '-of', 'default=noprint_wrappers=1:nokey=1', video_path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        return 'optimized_by_site_generator' in res.stdout
    except Exception:
        return False

def optimize_video_if_needed(video_path):
    """Re-encode video with libx264 + aac + faststart and strip metadata if > 25MB."""
    if not os.path.exists(video_path):
        return
    try:
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if size_mb > 25 and not is_video_optimized(video_path):
            print(f"[Video Optimizer] Optimizing {os.path.basename(video_path)} ({size_mb:.1f} MB)...")
            tmp_out = video_path + ".optimized.mp4"
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", "scale='min(1280,iw)':-2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "26", "-preset", "faster",
                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                "-metadata", "comment=optimized_by_site_generator",
                tmp_out
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0 and os.path.exists(tmp_out):
                new_size = os.path.getsize(tmp_out) / (1024 * 1024)
                os.replace(tmp_out, video_path)
                print(f"[Video Optimizer] Successfully compressed {os.path.basename(video_path)}: {size_mb:.1f}MB -> {new_size:.1f}MB")
            elif os.path.exists(tmp_out):
                os.remove(tmp_out)
    except Exception as e:
        print(f"[Video Optimizer] Error optimizing {video_path}: {e}")

def compute_sha256(filepath):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def deduplicate_project_media(folder_path, raw_files, slug):
    """
    Detects exact SHA-256 duplicate media files and removes the redundant file.
    Always preserves the canonical filename (shorter name, without ' 2' or '(1)').
    """
    seen_hashes = {}
    files_to_remove = set()

    # Sort so that canonical names without ' 2' or 'copy' are processed first
    sorted_files = sorted(raw_files, key=lambda x: (len(x), x))
    for f in sorted_files:
        f_path = os.path.join(folder_path, f)
        if not os.path.isfile(f_path):
            continue
        h = compute_sha256(f_path)
        if h in seen_hashes:
            canonical_file = seen_hashes[h]
            print(f"[{slug}] Auto-detected duplicate: '{f}' matches '{canonical_file}'. Removing duplicate.")
            try:
                os.remove(f_path)
                files_to_remove.add(f)
            except OSError as e:
                print(f"[{slug}] Error removing duplicate {f}: {e}")
        else:
            seen_hashes[h] = f

    return [f for f in raw_files if f not in files_to_remove]

def optimize_full_photo(photo_path, max_dim=2560, quality=85):
    """
    Downscales extremely large full-size camera photos (> 2560px or > 2.5MB)
    to a web-optimized JPEG with progressive encoding, saving 70-80% bandwidth
    while preserving high detail for lightbox zooming.
    """
    if not os.path.exists(photo_path):
        return
    try:
        size_bytes = os.path.getsize(photo_path)
        with Image.open(photo_path) as img:
            w, h = img.size
            if max(w, h) > max_dim or size_bytes > 2.5 * 1024 * 1024:
                scale = min(1.0, max_dim / max(w, h)) if max(w, h) > max_dim else 1.0
                new_w, new_h = int(round(w * scale)), int(round(h * scale))
                if scale < 1.0:
                    img_res = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                else:
                    img_res = img.copy()
                
                if img_res.mode in ('RGBA', 'P'):
                    img_res = img_res.convert('RGB')

                tmp_dst = photo_path + ".tmp.jpg"
                img_res.save(tmp_dst, 'JPEG', quality=quality, optimize=True, progressive=True)
                new_size = os.path.getsize(tmp_dst)
                if new_size < size_bytes:
                    os.replace(tmp_dst, photo_path)
                    print(f"[Photo Optimizer] Optimized {os.path.basename(photo_path)}: {size_bytes/(1024*1024):.1f}MB -> {new_size/(1024*1024):.1f}MB ({new_w}x{new_h})")
                elif os.path.exists(tmp_dst):
                    os.remove(tmp_dst)
    except Exception as e:
        print(f"[Photo Optimizer] Error optimizing {photo_path}: {e}")

def get_video_metadata(video_path):
    """
    Returns (width, height, aspect_ratio, is_portrait, duration) using ffprobe.
    """
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration:stream=width,height',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        w = int(lines[0]) if len(lines) > 0 else 1920
        h = int(lines[1]) if len(lines) > 1 else 1080
        dur_raw = float(lines[2]) if len(lines) > 2 else 0.0
        ar = round(w / h, 3) if h > 0 else 1.778
        total_sec = int(round(dur_raw))
        mins = total_sec // 60
        secs = total_sec % 60
        dur_str = f"{mins}:{secs:02d}"
        cs_cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'stream=color_space,color_transfer,color_primaries',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        cs_res = subprocess.run(cs_cmd, capture_output=True, text=True)
        cs_lines = [l.strip() for l in cs_res.stdout.strip().splitlines() if l.strip()]
        color_transfer = cs_lines[1] if len(cs_lines) > 1 else ''
        color_space = cs_lines[0] if len(cs_lines) > 0 else ''

        return {
            'width': w,
            'height': h,
            'aspect_ratio': ar,
            'is_portrait': (h > w),
            'duration': dur_str,
            'color_transfer': color_transfer,
            'color_space': color_space
        }
    except Exception as e:
        print(f"ffprobe warning for {video_path}: {e}")
    return {
        'width': 1920,
        'height': 1080,
        'aspect_ratio': 1.778,
        'is_portrait': False,
        'duration': '',
        'color_transfer': '',
        'color_space': ''
    }

def video_mime_type(filename):
    ext = os.path.splitext(filename)[1].lower()
    return {
        '.mov': 'video/quicktime',
        '.webm': 'video/webm'
    }.get(ext, 'video/mp4')

def ensure_video_poster(video_path, thumbs_dir):
    """Return a gallery-ready poster filename, extracting with color-space tone mapping when needed."""
    video_name = os.path.basename(video_path)
    base_name = os.path.splitext(video_name)[0]
    poster_fn = f"{base_name}_poster.jpg"
    poster_dst = os.path.join(thumbs_dir, poster_fn)
    poster_webp_fn = f"{base_name}_poster.webp"
    poster_webp_dst = os.path.join(thumbs_dir, poster_webp_fn)
    if not os.path.exists(poster_dst) or os.path.getmtime(video_path) > os.path.getmtime(poster_dst):
        try:
            # Check if video is HDR / HLG (arib-std-b67 / bt2020)
            meta = get_video_metadata(video_path)
            vf_filter = []
            if meta.get('color_transfer') == 'arib-std-b67' or 'bt2020' in meta.get('color_space', ''):
                vf_filter = ['-vf', 'colorspace=all=bt709:itrc=bt2020-10:iprimaries=bt2020:ispace=bt2020nc']

            cmd = [
                'ffmpeg', '-y', '-ss', '00:00:00.20', '-i', video_path
            ] + vf_filter + [
                '-frames:v', '1', '-update', '1', '-q:v', '2', poster_dst
            ]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode != 0:
                # Fallback without colorspace filter if unsupported
                cmd_fallback = [
                    'ffmpeg', '-y', '-ss', '00:00:00.20', '-i', video_path,
                    '-frames:v', '1', '-update', '1', '-q:v', '2', poster_dst
                ]
                subprocess.run(cmd_fallback, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            strip_exif_from_file(poster_dst)
            print(f"Extracted video poster with tone mapping: {poster_fn}")
        except Exception as e:
            print(f"Error extracting video poster for {video_name}: {e}")
            return ''

    if os.path.exists(poster_dst):
        if not os.path.exists(poster_webp_dst) or os.path.getmtime(poster_dst) > os.path.getmtime(poster_webp_dst):
            try:
                with Image.open(poster_dst) as img:
                    img.save(poster_webp_dst, 'WEBP', quality=82)
                print(f"Generated WebP video poster: {poster_webp_fn}")
            except Exception as e:
                print(f"Error generating WebP video poster for {video_name}: {e}")

    return poster_fn if os.path.exists(poster_dst) else ''

def gallery_summary(media):
    photo_count = sum(1 for item in media if item['type'] == 'image')
    video_count = sum(1 for item in media if item['type'] == 'video')
    parts = []
    if photo_count:
        parts.append(f"{photo_count} {'Photo' if photo_count == 1 else 'Photos'}")
    if video_count:
        parts.append(f"{video_count} {'Video' if video_count == 1 else 'Videos'}")
    return ' &bull; '.join(parts) if parts else 'No Media Yet'

def render_gallery_card(item, title, index):
    title_attr = escape(title, quote=True)
    thumb_attr = escape(item.get('thumb', ''), quote=True)
    thumb_webp_attr = escape(item.get('thumb_webp', ''), quote=True)
    date_attr = escape(item.get('short_date', ''), quote=True)
    media_type = item.get('type', 'image')
    card_class = 'photo-card video-card' if media_type == 'video' else 'photo-card'
    label = f"Play {title} build video" if media_type == 'video' else f"Open {title} build photo"
    alt = f"{title} build video thumbnail" if media_type == 'video' else f"{title} build photo"

    if media_type == 'video':
        duration_text = escape(item.get('duration', ''), quote=True)
        duration_span = f'<span class="video-duration-text">{duration_text}</span>' if duration_text else ''
        media_indicator = f'''
        <span class="video-duration-badge">
          {duration_span}
          <svg viewBox="0 0 24 24" class="video-badge-icon" aria-hidden="true"><circle cx="12" cy="12" r="9.5" stroke="currentColor" stroke-width="2" fill="none"/><polygon points="10,7.5 16.5,12 10,16.5" fill="currentColor"/></svg>
        </span>'''
    else:
        media_indicator = '''
        <span class="photo-expand-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M15 3h6v6m-6-6l6 6M9 21H3v-6m6 6L3 15"/></svg>
        </span>'''

    fn_id = escape(item.get('filename', ''), quote=True)
    if thumb_webp_attr:
        picture_markup = f'''<picture>
          <source type="image/webp" srcset="{thumb_webp_attr}">
          <img src="{thumb_attr}" alt="{escape(alt, quote=True)}" loading="lazy">
        </picture>'''
    else:
        picture_markup = f'<img src="{thumb_attr}" alt="{escape(alt, quote=True)}" loading="lazy">'

    return f'''
      <button type="button" id="{fn_id}" data-filename="{fn_id}" class="{card_class}" style="--ar: {item.get('aspect_ratio', 1.333)};" onclick="openLightbox({index})" aria-label="{escape(label, quote=True)}">
        {picture_markup}
        <span class="photo-date-pill">{date_attr}</span>{media_indicator}
      </button>'''

def render_story_box(story_html):
    if not story_html:
        return ''
    return f'''
    <section class="narrative-box">
      <h2 class="narrative-heading">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path></svg>
        <span>The Build Story</span>
      </h2>
      <div class="narrative-collapsible" id="narrativeCollapsible">
        <div class="narrative-content" id="narrativeContent">
          {story_html}
        </div>
        <div class="narrative-fade" id="narrativeFade"></div>
      </div>
      <div class="narrative-toggle-wrap" id="narrativeToggleWrap">
        <button class="narrative-toggle-btn" id="narrativeToggleBtn" onclick="toggleNarrative()">
          <span id="narrativeToggleText">Read full story</span>
          <svg class="narrative-toggle-icon" id="narrativeToggleIcon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </button>
      </div>
    </section>'''

def render_engineering_section(highlights, status=''):
    if not highlights:
        return ''

    cards = []
    for highlight in highlights:
        cards.append(f'''
        <article class="engineering-highlight-card">
          <p class="engineering-highlight-label">{escape(highlight.get('label', ''))}</p>
          <h3>{escape(highlight.get('title', ''))}</h3>
          <p>{escape(highlight.get('description', ''))}</p>
        </article>''')

    status_html = ''
    if status:
        status_html = f'<p class="engineering-status">{escape(status)}</p>'

    return f'''
    <section class="engineering-summary" aria-labelledby="engineering-summary-title">
      <div class="engineering-summary-header">
        <div>
          <p class="engineering-summary-kicker">Working-system evidence</p>
          <h2 id="engineering-summary-title">Engineering at a glance</h2>
        </div>
        {status_html}
      </div>
      <div class="engineering-highlight-grid">
{''.join(cards)}
      </div>
    </section>'''

def render_next_steps(next_steps):
    if not next_steps:
        return ''
    items_html = []
    for step in next_steps:
        items_html.append(f'        <li class="next-step-item">{escape(step)}</li>')
    
    return f'''
    <section class="next-steps-box">
      <div class="next-steps-header">
        <div class="next-steps-title-wrap">
          <svg class="next-steps-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
            <polyline points="2 17 12 22 22 17"></polyline>
            <polyline points="2 12 12 17 22 12"></polyline>
          </svg>
          <h2 class="next-steps-title">Next Steps &amp; Planned Upgrades</h2>
        </div>
      </div>
      <ul class="next-steps-list">
{'\n'.join(items_html)}
      </ul>
    </section>'''

def process_build_dir(base_dir, slug, url_prefix):
    folder_path = os.path.join(base_dir, slug)
    config_path = os.path.join(folder_path, 'build.json')
    if not os.path.exists(config_path):
        config_path = os.path.join(folder_path, 'project.json')

    config = {}
    if os.path.exists(config_path) and os.path.getsize(config_path) > 0:
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            print(f"[{slug}] Warning: Error loading {config_path}: {e}")
            config = {}

    defaults = {
        'title': slug.replace('-', ' ').title(),
        'subtitle': 'Hardware Build',
        'description': '',
        'tags': ['Hardware'],
        'dates': 'Active',
        'order': 99,
        'story': '<p>Build details coming soon.</p>'
    }
    for k, v in defaults.items():
        if k not in config or not config[k]:
            config[k] = v

    thumbs_dir = os.path.join(folder_path, 'thumbs')
    os.makedirs(thumbs_dir, exist_ok=True)

    raw_files = [f for f in os.listdir(folder_path)
                 if not f.startswith('.')
                 and not f.lower().endswith('.optimized.mp4')
                 and f not in ('thumbs', 'index.html', 'build.json', 'project.json')]

    # 1. Deduplicate media files by SHA-256 hash
    raw_files = deduplicate_project_media(folder_path, raw_files, slug)

    # 2. Sanitize photos (EXIF) and optimize oversized full-size photos
    for f in raw_files:
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            full_path = os.path.join(folder_path, f)
            if f.lower().endswith(('.jpg', '.jpeg')):
                strip_exif_from_file(full_path)
            optimize_full_photo(full_path, max_dim=2560, quality=85)

    # 3. Prune deleted thumbnails
    raw_stems = {os.path.splitext(f)[0] for f in raw_files}
    for thumb in os.listdir(thumbs_dir):
        thumb_stem = os.path.splitext(thumb)[0]
        is_poster = thumb.endswith(('_poster.jpg', '_poster.webp'))
        is_stem_valid = (thumb in raw_files) or is_poster or (thumb_stem in raw_stems)
        if not is_stem_valid:
            try:
                os.remove(os.path.join(thumbs_dir, thumb))
                print(f"[{slug}] Pruned deleted thumbnail: {thumb}")
            except OSError:
                pass

    # 4. Generate missing thumbnails (WebP with JPEG fallback)
    for f in raw_files:
        f_lower = f.lower()
        if f_lower.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            src = os.path.join(folder_path, f)
            stem = os.path.splitext(f)[0]
            dst_orig = os.path.join(thumbs_dir, f)
            dst_webp = os.path.join(thumbs_dir, f"{stem}.webp")

            # Ensure standard/fallback thumbnail exists
            if not os.path.exists(dst_orig) or os.path.getmtime(src) > os.path.getmtime(dst_orig):
                try:
                    with Image.open(src) as img:
                        img.thumbnail((600, 600), Image.Resampling.LANCZOS)
                        if img.mode in ('RGBA', 'P') and not f_lower.endswith('.png'):
                            img = img.convert('RGB')
                        img.save(dst_orig, optimize=True, quality=82)
                        print(f"[{slug}] Generated thumbnail: {f}")
                except Exception as e:
                    print(f"[{slug}] Error thumbnailing {f}: {e}")

            # Ensure modern WebP companion thumbnail exists
            if not os.path.exists(dst_webp) or (os.path.exists(dst_orig) and os.path.getmtime(dst_orig) > os.path.getmtime(dst_webp)):
                try:
                    thumb_src = dst_orig if os.path.exists(dst_orig) else src
                    with Image.open(thumb_src) as img:
                        if not os.path.exists(dst_orig):
                            img.thumbnail((600, 600), Image.Resampling.LANCZOS)
                        if img.mode in ('RGBA', 'P') and not f_lower.endswith('.png'):
                            img = img.convert('RGB')
                        img.save(dst_webp, 'WEBP', quality=80)
                        print(f"[{slug}] Generated WebP thumbnail: {stem}.webp")
                except Exception as e:
                    print(f"[{slug}] Error generating WebP thumbnail {stem}.webp: {e}")

    # 4. Check for videos to optimize
    for f in raw_files:
        if f.lower().endswith(VIDEO_EXTENSIONS):
            optimize_video_if_needed(os.path.join(folder_path, f))

    # 5. Collect media files
    raw_files.sort()
    photos = []
    videos = []

    for f in raw_files:
        f_lower = f.lower()
        if f_lower.endswith(('.mp4', '.mov', '.webm')):
            videos.append(f)
        elif f_lower.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            date_str, short_date = parse_photo_date(f)
            # Calculate aspect ratio
            src = os.path.join(folder_path, f)
            thumb = os.path.join(thumbs_dir, f)
            ar = 1.333
            try:
                img_path = thumb if os.path.exists(thumb) else src
                with Image.open(img_path) as img:
                    w, h = img.size
                    if h > 0:
                        ar = round(w / h, 3)
            except Exception:
                pass

            thumb_stem = os.path.splitext(f)[0]
            photos.append({
                'type': 'image',
                'filename': f,
                'full': f"{url_prefix}/{slug}/{f}",
                'thumb': f"{url_prefix}/{slug}/thumbs/{f}",
                'thumb_webp': f"{url_prefix}/{slug}/thumbs/{thumb_stem}.webp",
                'date': date_str,
                'short_date': short_date,
                'aspect_ratio': ar
            })

    # Sort photos chronologically (oldest first: start of build through completion)
    photos.sort(key=lambda p: get_photo_sort_key(p['filename']))

    # Determine cover image: check build.json config first, fallback to latest photo
    configured_cover = config.get('cover_image') or config.get('cover_img') or ''
    if configured_cover and os.path.exists(os.path.join(folder_path, configured_cover)):
        cover_img = configured_cover
    else:
        if configured_cover:
            print(f"[{slug}] Note: Configured cover_image '{configured_cover}' not found, defaulting.")
        cover_img = photos[-1]['filename'] if photos else ''

    # Determine hero video: check build.json config first
    configured_video = config.get('hero_video') or ''
    if configured_video and os.path.exists(os.path.join(folder_path, configured_video)):
        hero_video = configured_video
    elif configured_video:
        print(f"[{slug}] Note: Configured hero_video '{configured_video}' not found.")
        hero_video = ''
    elif videos:
        hero_video = videos[0]
    else:
        hero_video = ''

    # Extract first frame as hero video poster thumbnail.
    hero_video_poster = ''
    if hero_video:
        vid_src = os.path.join(folder_path, hero_video)
        hero_video_poster = ensure_video_poster(vid_src, thumbs_dir)

    # Add all videos (including hero video) to the chronological gallery.
    gallery_videos = []
    for video_fn in videos:
        video_path = os.path.join(folder_path, video_fn)
        poster_fn = ensure_video_poster(video_path, thumbs_dir)
        if not poster_fn:
            print(f"[{slug}] Warning: No poster generated for gallery video {video_fn}; skipping it.")
            continue
        date_str, short_date = parse_photo_date(video_fn)
        meta = get_video_metadata(video_path)
        poster_stem = os.path.splitext(poster_fn)[0]
        gallery_videos.append({
            'type': 'video',
            'filename': video_fn,
            'full': f"{url_prefix}/{slug}/{video_fn}",
            'thumb': f"{url_prefix}/{slug}/thumbs/{poster_fn}",
            'thumb_webp': f"{url_prefix}/{slug}/thumbs/{poster_stem}.webp",
            'date': date_str,
            'short_date': short_date,
            'aspect_ratio': meta['aspect_ratio'],
            'duration': meta.get('duration', ''),
            'mime_type': video_mime_type(video_fn)
        })

    gallery = photos + gallery_videos
    gallery.sort(key=lambda item: get_photo_sort_key(item['filename']))

    return {
        'slug': slug,
        'title': config.get('title', slug),
        'subtitle': config.get('subtitle', ''),
        'description': config.get('description', ''),
        'tags': config.get('tags', []),
        'dates': config.get('dates', ''),
        'order': config.get('order', 99),
        'story': config.get('story', ''),
        'status': config.get('status', ''),
        'engineering_highlights': config.get('engineering_highlights', []),
        'cover_img': cover_img,
        'hero_video': hero_video,
        'hero_video_poster': hero_video_poster,
        'next_steps': config.get('next_steps', []),
        'photos': photos,
        'videos': videos,
        'gallery': gallery,
        'url_prefix': url_prefix
    }

process_project_dir = process_build_dir

def sync_builds():
    if not os.path.exists(MAJOR_BUILDS_DIR):
        print(f"Major builds directory not found: {MAJOR_BUILDS_DIR}")
        return

    home_tmpl = load_template('home.html')
    major_build_tmpl = load_template('major_build.html')
    quick_build_tmpl = load_template('quick_build.html')

    # Collect Major Builds
    major_slugs = [d for d in os.listdir(MAJOR_BUILDS_DIR) 
                   if os.path.isdir(os.path.join(MAJOR_BUILDS_DIR, d)) and not d.startswith('.')]
    major_builds = [process_build_dir(MAJOR_BUILDS_DIR, s, '/major-builds') for s in major_slugs]
    major_builds.sort(key=lambda x: x['order'])

    # Collect Quick Builds
    quick_builds = []
    if os.path.exists(QUICK_BUILDS_DIR):
        quick_slugs = [d for d in os.listdir(QUICK_BUILDS_DIR)
                       if os.path.isdir(os.path.join(QUICK_BUILDS_DIR, d)) and not d.startswith('.')]
        quick_builds = [process_build_dir(QUICK_BUILDS_DIR, s, '/quick-builds') for s in quick_slugs]
        quick_builds.sort(key=lambda x: x['order'])

    # Build navigation helper
    def render_nav(active_type, active_slug=''):
        home_cls = ' class="nav-item-link active-nav"' if active_type == 'home' else ' class="nav-item-link"'
        major_trigger_cls = 'nav-item-link nav-dropdown-trigger active-nav' if active_type == 'major' else 'nav-item-link nav-dropdown-trigger'
        quick_trigger_cls = 'nav-item-link nav-dropdown-trigger active-nav' if active_type == 'quick' else 'nav-item-link nav-dropdown-trigger'

        # Major builds items
        major_items = []
        for b in major_builds:
            item_act = ' is-active' if (active_type == 'major' and b['slug'] == active_slug) else ''
            subtitle = b['subtitle'] if b['subtitle'] else 'Hardware Build'
            major_items.append(f'''
              <a href="/major-builds/{b['slug']}/" class="nav-dropdown-item{item_act}">
                <div class="dropdown-item-content">
                  <span class="dropdown-item-title">{b['title']}</span>
                  <span class="dropdown-item-desc">{subtitle}</span>
                </div>
                <svg class="dropdown-item-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
              </a>''')

        # Quick builds items
        quick_items = []
        for qb in quick_builds:
            item_act = ' is-active' if (active_type == 'quick' and qb['slug'] == active_slug) else ''
            subtitle = qb['subtitle'] if qb['subtitle'] else 'Quick Build'
            quick_items.append(f'''
              <a href="/quick-builds/{qb['slug']}/" class="nav-dropdown-item{item_act}">
                <div class="dropdown-item-content">
                  <span class="dropdown-item-title">{qb['title']}</span>
                  <span class="dropdown-item-desc">{subtitle}</span>
                </div>
                <svg class="dropdown-item-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
              </a>''')

        return f'''<a href="/"{home_cls}>Home</a>
        <div class="nav-dropdown" id="navMajorDropdown">
          <a href="/#major-builds" class="{major_trigger_cls}" aria-haspopup="true" aria-expanded="false">
            <span>Major Builds</span>
            <span class="nav-count-badge">{len(major_builds)}</span>
            <svg class="nav-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
          </a>
          <div class="nav-dropdown-panel">
            <div class="nav-dropdown-header">
              <span class="dropdown-header-title">Major Builds</span>
              <span class="dropdown-header-subtitle">{len(major_builds)} Systems</span>
            </div>
            <div class="nav-dropdown-list">
              {''.join(major_items)}
            </div>
            <div class="nav-dropdown-footer">
              <a href="/#major-builds" class="dropdown-footer-link">
                <span>View All Major Builds</span>
                <span class="footer-arrow">&rarr;</span>
              </a>
            </div>
          </div>
        </div>
        <div class="nav-dropdown" id="navQuickDropdown">
          <a href="/#quick-builds" class="{quick_trigger_cls}" aria-haspopup="true" aria-expanded="false">
            <span>Quick Builds</span>
            <span class="nav-count-badge">{len(quick_builds)}</span>
            <svg class="nav-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
          </a>
          <div class="nav-dropdown-panel">
            <div class="nav-dropdown-header">
              <span class="dropdown-header-title">Quick Builds</span>
              <span class="dropdown-header-subtitle">{len(quick_builds)} {'Make' if len(quick_builds) == 1 else 'Makes'}</span>
            </div>
            <div class="nav-dropdown-list">
              {''.join(quick_items)}
            </div>
            <div class="nav-dropdown-footer">
              <a href="/#quick-builds" class="dropdown-footer-link">
                <span>View All Quick Builds</span>
                <span class="footer-arrow">&rarr;</span>
              </a>
            </div>
          </div>
        </div>'''

    build_id = os.environ.get('BUILD_ID') or str(int(datetime.now().timestamp()))

    # 1. Render Major Build Cards for Homepage
    major_cards_html = []
    for b in major_builds:
        b_title = escape(b['title'])
        cover_base = os.path.splitext(b['cover_img'])[0] if b.get('cover_img') else ''
        thumb_src = f"/major-builds/{b['slug']}/thumbs/{b['cover_img']}" if b.get('cover_img') else ''
        thumb_webp_src = f"/major-builds/{b['slug']}/thumbs/{cover_base}.webp" if cover_base else ''
        tags_html = ''.join(f'<span class="tech-tag">{tag}</span>' for tag in b['tags'])
        if thumb_webp_src:
            picture_html = f'''<picture>
              <source type="image/webp" srcset="{thumb_webp_src}">
              <img src="{thumb_src}" alt="{b_title}" loading="lazy">
            </picture>'''
        else:
            picture_html = f'<img src="{thumb_src}" alt="{b_title}" loading="lazy">'
        major_cards_html.append(f'''
      <a href="/major-builds/{b['slug']}/" class="major-build-card-link">
        <div class="major-build-card">
          <div class="grid-card-media">
            <div class="card-media-backdrop" style="background-image: url('{thumb_src}');"></div>
            {picture_html}
            <div class="media-badges" style="justify-content: flex-end;">
              <span class="media-badge count-badge">{gallery_summary(b['gallery'])}</span>
            </div>
          </div>
          <div class="grid-card-body">
            <div class="grid-card-header">
              <h3 class="grid-card-title">{b['title']}</h3>
              <span class="grid-card-arrow">&rarr;</span>
            </div>
            <p class="grid-card-subtitle">{b['subtitle']}</p>
            <div class="grid-card-tags">
              {tags_html}
            </div>
          </div>
        </div>
      </a>''')

    # 2. Render Quick Build Cards for Homepage
    quick_cards_html = []
    for qb in quick_builds:
        qb_title = escape(qb['title'])
        tags_html = ''.join(f'<span class="tech-tag">{tag}</span>' for tag in qb['tags'])
        cover_base = os.path.splitext(qb['cover_img'])[0] if qb.get('cover_img') else ''
        thumb_src = f"/quick-builds/{qb['slug']}/thumbs/{qb['cover_img']}" if qb.get('cover_img') else ''
        thumb_webp_src = f"/quick-builds/{qb['slug']}/thumbs/{cover_base}.webp" if cover_base else ''
        if thumb_src:
            if thumb_webp_src:
                picture_html = f'''<picture>
              <source type="image/webp" srcset="{thumb_webp_src}">
              <img src="{thumb_src}" alt="{qb_title}" loading="lazy">
            </picture>'''
            else:
                picture_html = f'<img src="{thumb_src}" alt="{qb_title}" loading="lazy">'
            media_markup = f'''
          <div class="grid-card-media">
            <div class="card-media-backdrop" style="background-image: url('{thumb_src}');"></div>
            {picture_html}
            <div class="media-badges" style="justify-content: flex-end;">
              <span class="media-badge count-badge">{gallery_summary(qb['gallery'])}</span>
            </div>
          </div>'''
        else:
            media_markup = '''
          <div class="grid-card-media">
            <div class="quick-card-placeholder">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>
              <span class="quick-placeholder-label">3D Print / CAD Build</span>
            </div>
          </div>'''

        quick_cards_html.append(f'''
      <a href="/quick-builds/{qb['slug']}/" class="major-build-card-link">
        <div class="major-build-card">
          {media_markup}
          <div class="grid-card-body">
            <div class="grid-card-header">
              <h3 class="grid-card-title">{qb['title']}</h3>
              <span class="grid-card-arrow">&rarr;</span>
            </div>
            <p class="grid-card-subtitle">{qb['subtitle']}</p>
            <div class="grid-card-tags">
              {tags_html}
            </div>
          </div>
        </div>
      </a>''')

    rendered_home = (home_tmpl
        .replace('{{ NAV_LINKS }}', render_nav('home'))
        .replace('{{ BUILD_ID }}', build_id)
        .replace('{{ GA_MEASUREMENT_ID }}', GA_MEASUREMENT_ID)
        .replace('{{ MAJOR_BUILD_COUNT }}', f"{len(major_builds)} {'Build' if len(major_builds) == 1 else 'Builds'}")
        .replace('{{ MAJOR_BUILD_CARDS }}', '\n'.join(major_cards_html))
        .replace('{{ QUICK_BUILD_COUNT }}', f"{len(quick_builds)} {'Build' if len(quick_builds) == 1 else 'Builds'}")
        .replace('{{ QUICK_BUILD_CARDS }}', '\n'.join(quick_cards_html)))

    with open(os.path.join(BASE_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(rendered_home)
    print("Rendered root index.html")

    # 3. Render Major Build Pages (major-builds/{slug}/index.html)
    for b in major_builds:
        tags_html = '\n        '.join(f'<span class="tech-tag">{tag}</span>' for tag in b['tags'])
        
        story_box_html = render_story_box(b['story'])
        engineering_section_html = render_engineering_section(
            b.get('engineering_highlights', []),
            b.get('status', '')
        )
        next_steps_html = render_next_steps(b.get('next_steps', []))

        # Hero Video Section: Adaptive Portrait vs Landscape
        if b['hero_video']:
            video_fn = b['hero_video']
            video_path = os.path.join(MAJOR_BUILDS_DIR, b['slug'], video_fn)
            meta = get_video_metadata(video_path)
            if b.get('hero_video_poster'):
                poster_attr = f' poster="/major-builds/{b["slug"]}/thumbs/{b["hero_video_poster"]}"'
            elif b["cover_img"]:
                poster_attr = f' poster="/major-builds/{b["slug"]}/thumbs/{b["cover_img"]}"'
            else:
                poster_attr = ''

            if meta['is_portrait']:
                # Portrait Split Layout: Video alongside The Build Story
                hero_section_html = f'''
    <div class="hero-split-container">
      <div class="hero-portrait-col">
        <div class="hero-portrait-card">
          <div class="hero-portrait-header">
            <span class="hero-portrait-header-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              Build Demonstration
            </span>
          </div>
          <div class="hero-portrait-player-wrap">
            <video class="hero-portrait-player" controls preload="metadata" playsinline{poster_attr}>
              <source src="/major-builds/{b['slug']}/{video_fn}" type="video/mp4">
              Your browser does not support HTML5 video.
            </video>
          </div>
        </div>
      </div>
      <div class="hero-story-col">
        {story_box_html}
      </div>
    </div>'''
                story_section_html = ''
                next_steps_section_html = next_steps_html
            else:
                # Landscape Video: Custom fitted aspect-ratio container
                ar = meta['aspect_ratio']
                hero_section_html = f'''
    <div class="hero-video-wrapper landscape-hero" style="max-width: 960px; margin: 1.5rem auto 2.25rem auto;">
      <div class="landscape-video-box" style="aspect-ratio: {ar}; width: 100%;">
        <video class="video-actual-player" controls preload="metadata" playsinline{poster_attr} style="width: 100%; height: 100%; object-fit: contain;">
          <source src="/major-builds/{b['slug']}/{video_fn}" type="video/mp4">
          Your browser does not support HTML5 video.
        </video>
      </div>
    </div>'''
                story_section_html = story_box_html
                next_steps_section_html = next_steps_html
        else:
            # Placeholder Video
            hero_section_html = f'''
    <div class="hero-video-wrapper placeholder-hero">
      <div class="hero-video-placeholder">
        <div class="video-play-btn">
          <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
        </div>
        <div class="video-placeholder-title">Full Build &amp; Demonstration Video Coming Soon</div>
        <div class="video-placeholder-desc">A detailed walkthrough showing live operation, mechanical tolerances, and internal electronics.</div>
      </div>
    </div>'''
            story_section_html = story_box_html
            next_steps_section_html = next_steps_html

        # Google Photos style justified chronological media grid.
        media_html = [render_gallery_card(item, b['title'], idx)
                      for idx, item in enumerate(b['gallery'])]
        gallery_json = json.dumps(b['gallery'])

        og_image = f"https://cathalcoffey.com/major-builds/{b['slug']}/thumbs/{b['cover_img']}" if b.get('cover_img') else "https://cathalcoffey.com/major-builds/claw-machine/thumbs/PXL_20260906_064952583.jpg"

        rendered_build = (major_build_tmpl
            .replace('{{ TITLE }}', b['title'])
            .replace('{{ SUBTITLE }}', b['subtitle'])
            .replace('{{ SLUG }}', b['slug'])
            .replace('{{ OG_IMAGE_URL }}', og_image)
            .replace('{{ DATES }}', b['dates'])
            .replace('{{ TAGS }}', tags_html)
            .replace('{{ BUILD_ID }}', build_id)
            .replace('{{ GA_MEASUREMENT_ID }}', GA_MEASUREMENT_ID)
            .replace('{{ NAV_LINKS }}', render_nav('major', b['slug']))
            .replace('{{ HERO_SECTION }}', hero_section_html)
            .replace('{{ STORY_SECTION }}', story_section_html)
            .replace('{{ ENGINEERING_SECTION }}', engineering_section_html)
            .replace('{{ NEXT_STEPS_SECTION }}', next_steps_section_html)
            .replace('{{ GALLERY_SUMMARY }}', gallery_summary(b['gallery']))
            .replace('{{ PHOTO_GRID }}', '\n'.join(media_html))
            .replace('{{ GALLERY_JSON }}', gallery_json))

        build_out = os.path.join(MAJOR_BUILDS_DIR, b['slug'], 'index.html')
        with open(build_out, 'w', encoding='utf-8') as f:
            f.write(rendered_build)
        print(f"Rendered major-builds/{b['slug']}/index.html ({len(b['gallery'])} media items)")

    # 4. Render Quick Build Pages (quick-builds/{slug}/index.html)
    for qb in quick_builds:
        tags_html = '\n        '.join(f'<span class="tech-tag">{tag}</span>' for tag in qb['tags'])

        if qb['gallery']:
            gallery_markup = '\n'.join(
                render_gallery_card(item, qb['title'], idx)
                for idx, item in enumerate(qb['gallery'])
            )
        else:
            gallery_markup = '''
      <div class="empty-photos-box" style="grid-column: 1 / -1; width: 100%;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
        <div class="empty-photos-title">Photos In Progress</div>
        <div class="empty-photos-desc">Photos of the design, 3D printing process, and installed wall covers are being prepared.</div>
      </div>'''

        gallery_json = json.dumps(qb['gallery'])
        desc_html = f'<div class="build-description"><p>{qb["description"]}</p></div>' if qb.get('description') else ''
        og_image = f"https://cathalcoffey.com/quick-builds/{qb['slug']}/thumbs/{qb['cover_img']}" if qb.get('cover_img') else "https://cathalcoffey.com/major-builds/claw-machine/thumbs/PXL_20260906_064952583.jpg"

        rendered_qb = (quick_build_tmpl
            .replace('{{ TITLE }}', qb['title'])
            .replace('{{ SUBTITLE }}', qb['subtitle'])
            .replace('{{ SLUG }}', qb['slug'])
            .replace('{{ OG_IMAGE_URL }}', og_image)
            .replace('{{ DATES }}', qb['dates'])
            .replace('{{ DESCRIPTION }}', desc_html)
            .replace('{{ TAGS }}', tags_html)
            .replace('{{ BUILD_ID }}', build_id)
            .replace('{{ GA_MEASUREMENT_ID }}', GA_MEASUREMENT_ID)
            .replace('{{ NAV_LINKS }}', render_nav('quick', qb['slug']))
            .replace('{{ GALLERY_SUMMARY }}', gallery_summary(qb['gallery']))
            .replace('{{ PHOTO_GRID }}', gallery_markup)
            .replace('{{ GALLERY_JSON }}', gallery_json))

        qb_out = os.path.join(QUICK_BUILDS_DIR, qb['slug'], 'index.html')
        with open(qb_out, 'w', encoding='utf-8') as f:
            f.write(rendered_qb)
        print(f"Rendered quick-builds/{qb['slug']}/index.html ({len(qb['gallery'])} media items)")

    # 5. Generate sitemap.xml and robots.txt
    generate_sitemap(major_builds, quick_builds)
    generate_robots()

def generate_sitemap(major_builds, quick_builds):
    last_modified = os.environ.get('SITE_LASTMOD') or datetime.now().strftime('%Y-%m-%d')
    urls = [
        ('https://cathalcoffey.com/', '1.0', 'weekly'),
    ]
    for b in major_builds:
        urls.append((f"https://cathalcoffey.com/major-builds/{b['slug']}/", '0.8', 'monthly'))
    for qb in quick_builds:
        urls.append((f"https://cathalcoffey.com/quick-builds/{qb['slug']}/", '0.6', 'monthly'))

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    for loc, priority, changefreq in urls:
        lines.append('  <url>')
        lines.append(f'    <loc>{loc}</loc>')
        lines.append(f'    <lastmod>{last_modified}</lastmod>')
        lines.append(f'    <changefreq>{changefreq}</changefreq>')
        lines.append(f'    <priority>{priority}</priority>')
        lines.append('  </url>')
    lines.append('</urlset>')

    sitemap_path = os.path.join(BASE_DIR, 'sitemap.xml')
    with open(sitemap_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print("Generated sitemap.xml")

def generate_robots():
    content = '''User-agent: *
Allow: /

Sitemap: https://cathalcoffey.com/sitemap.xml
'''
    robots_path = os.path.join(BASE_DIR, 'robots.txt')
    with open(robots_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Generated robots.txt")

sync_projects = sync_builds

if __name__ == '__main__':
    sync_builds()
