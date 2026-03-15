Download all images and videos from a Reddit user account and automatically remove duplicates.

Changes vs original:
- youtube_dl → yt-dlp (youtube_dl is abandoned and broken)
- Pushshift API → PRAW (official Reddit API, Pushshift is unreliable/dead)
- Fixed duplicate removal logic edge cases
- Added Reddit API credential handling

Requirements:
    pip install praw yt-dlp opencv-python imagededup

Reddit API credentials:
    1. Go to https://www.reddit.com/prefs/apps
    2. Click "create another app" → choose "script"
    3. Fill in name + redirect URI (e.g. http://localhost:8080)
    4. Copy client_id (under app name) and client_secret
    5. Pass them via --client-id and --client-secret, or set env vars:
       REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET
